"""
H5-F / B3-F：观测约束融合（V6.1 重写，fuse-observed/v2）。

物理语义（v2 修订，对应续批任务书工作包 A）：
  · 三类空间：已知自由 / 测量带 / 未知，逐体素判定并写入报告。
  · 深度用相机**轴向深度**（positive_camera_minus_z），与 align/freespace 度量同一约定；
    斜视 fixture 用于检出轴向深度与射线长度的混用。
  · 视野外、无效深度、NaN/Inf、相机后方一律“未知”，不得借边缘像素获得自由标签。
  · 形态学与掩码膨胀使用**非周期**边界（零填充），边界外按“未知/空”处理。
  · 网格统一为 cell-center：索引 i 的体素中心 = origin + (i+0.5)*pitch；
    等值面提取在相邻体素中心之间插值。
  · 不靠挪顶点制造通过：约束只在占据层施加，导出后不移动顶点。
  · 闭运算/保最大分量/填洞都记录删除与新增体素及体积变化。

输入只允许：observation 包、已配准父候选 world 网格、冻结的融合配置。
不读取任何真值网格、背面类别或评价结果。
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import camera_io

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 'fuse-observed/v2'

CUBE = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                 [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=np.int64)
TETS = [(0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6),
        (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6)]


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def sha_obj(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def _load_mesh(p):
    # process=True 合并重复顶点：闭合性判定与射线奇偶都依赖边/面一致性
    m = trimesh.load(str(p), force='mesh', process=True)
    if isinstance(m, trimesh.Scene):
        geoms = [g for g in m.geometry.values() if len(g.faces) > 0]
        m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
    return m


# ------------------------------------------------------------- 非周期形态学
def dilate6(a, mask=None):
    """6 邻域膨胀，零填充（非周期）。"""
    out = a.copy()
    for ax in range(3):
        for s in (1, -1):
            sh = np.roll(a, s, ax)
            sl = [slice(None)] * 3
            sl[ax] = 0 if s == 1 else -1
            sh[tuple(sl)] = False
            out |= sh
    if mask is not None:
        out &= mask
    return out


def erode6(a):
    """6 邻域腐蚀，边界外视为空（非周期）。"""
    out = a.copy()
    for ax in range(3):
        for s in (1, -1):
            sh = np.roll(a, s, ax)
            sl = [slice(None)] * 3
            sl[ax] = 0 if s == 1 else -1
            sh[tuple(sl)] = False
            out &= sh
    return out


def dilate2(mask, k=1):
    """图像掩码膨胀，非周期（边缘不绕回）。"""
    out = mask.copy()
    for _ in range(k):
        m = out.copy()
        for ax in (0, 1):
            for s in (1, -1):
                sh = np.roll(out, s, ax)
                sl = [slice(None)] * 2
                sl[ax] = 0 if s == 1 else -1
                sh[tuple(sl)] = False
                m |= sh
        out = m
    return out


# ------------------------------------------------------------- 网格与空间
def make_grid(parent, vis_pts, pitch, margin_cells=3):
    b = np.asarray(parent.bounds)
    lo = np.minimum(b[0], vis_pts.min(axis=0) if len(vis_pts) else b[0])
    hi = np.maximum(b[1], vis_pts.max(axis=0) if len(vis_pts) else b[1])
    m = margin_cells * pitch
    origin = np.array([lo[0] - m, lo[1] - m, 0.0], dtype=np.float64)
    top = max(hi[2] + m, pitch * 4)
    dims = np.ceil(np.array([(hi[0] + m - origin[0]),
                             (hi[1] + m - origin[1]),
                             (top - origin[2])]) / pitch).astype(int)
    dims = np.maximum(dims, 6)
    if np.prod(dims) > 40_000_000:
        raise SystemExit(f'体素网格过大 {dims.tolist()}，请增大 pitch')
    xs = origin[0] + (np.arange(dims[0]) + 0.5) * pitch
    ys = origin[1] + (np.arange(dims[1]) + 0.5) * pitch
    zs = origin[2] + (np.arange(dims[2]) + 0.5) * pitch
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    return {'origin': origin, 'pitch': float(pitch), 'dims': dims,
            'xs': xs, 'ys': ys, 'zs': zs, 'X': X, 'Y': Y, 'Z': Z}


def ray_parity_occupancy(mesh, grid):
    """闭合网格的精确占据：沿 +z 射线奇偶。"""
    pts = np.stack([grid['X'].ravel(), grid['Y'].ravel(), grid['Z'].ravel()], axis=1)
    inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    d = np.tile(np.array([0.0, 0.0, 1.0]), (len(pts), 1))
    _, ray_i, _ = inter.intersects_location(pts, d, multiple_hits=True)
    cnt = np.bincount(ray_i, minlength=len(pts))
    return (cnt % 2).astype(bool).reshape(grid['dims'])


def parent_solid(parent, grid, dilate_voxels=1):
    """
    父先验 -> 体素占据。
    闭合网格用射线奇偶（与网格体积一致）；非闭合才退回“采样壳 + flood fill”，
    并标 solid_method 以便报告该近似。
    """
    if bool(parent.is_watertight):
        occ = ray_parity_occupancy(parent, grid)
        return occ, {'solid_method': 'ray_parity', 'watertight_parent': True,
                     'n_inside_voxels': int(occ.sum())}
    pitch = grid['pitch']; dims = grid['dims']; origin = grid['origin']
    area = float(parent.area)
    n = int(np.clip(area / (pitch * pitch) * 2.0, 30000, 400000))
    pts, _ = trimesh.sample.sample_surface(parent, n, seed=0)
    shell = np.zeros(dims, dtype=bool)
    idx = np.floor((np.asarray(pts) - origin) / pitch).astype(np.int64)
    inb = ((idx >= 0) & (idx < dims)).all(axis=1)
    idx = idx[inb]
    shell[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    for _ in range(max(0, int(dilate_voxels))):
        shell = dilate6(shell)
    outside = np.zeros(dims, dtype=bool)
    from collections import deque
    q = deque()

    def push(i, j, k):
        if not shell[i, j, k] and not outside[i, j, k]:
            outside[i, j, k] = True
            q.append((i, j, k))

    for i in range(dims[0]):
        for j in range(dims[1]):
            push(i, j, 0); push(i, j, dims[2] - 1)
    for i in range(dims[0]):
        for k in range(dims[2]):
            push(i, 0, k); push(i, dims[1] - 1, k)
    for j in range(dims[1]):
        for k in range(dims[2]):
            push(0, j, k); push(dims[0] - 1, j, k)
    while q:
        i, j, k = q.popleft()
        for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            a, b_, c = i + di, j + dj, k + dk
            if 0 <= a < dims[0] and 0 <= b_ < dims[1] and 0 <= c < dims[2] \
                    and not shell[a, b_, c] and not outside[a, b_, c]:
                outside[a, b_, c] = True
                q.append((a, b_, c))
    inside = ~outside
    return inside, {'solid_method': 'shell_floodfill', 'watertight_parent': False,
                    'n_surface_samples': int(n), 'n_shell_voxels': int(shell.sum()),
                    'n_inside_voxels': int(inside.sum()),
                    'dilate_voxels': int(dilate_voxels)}


def depth_edge_mask(depth, thr):
    """深度不连续像素（前景/背景混合），不作为约束。"""
    d = np.asarray(depth, dtype=np.float64)
    ok = np.isfinite(d) & (d > 0) & (d < 100.0)
    du = np.zeros_like(d); dv = np.zeros_like(d)
    du[:, 1:] = np.abs(np.diff(d, axis=1)); du[:, 0] = du[:, 1]
    dv[1:, :] = np.abs(np.diff(d, axis=0)); dv[0, :] = dv[1, :]
    e = ((du > thr) | (dv > thr)) & ok
    return dilate2(e, 1)


def min_filter3(depth):
    """3x3 最小有效深度：不连续处只需知道“前方到较近表面为止”是自由。"""
    d = np.asarray(depth, dtype=np.float64)
    ok = np.isfinite(d) & (d > 0) & (d < 100.0)
    big = np.where(ok, d, np.inf)
    out = big.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out = np.minimum(out, np.roll(np.roll(big, dy, 0), dx, 1))
    out[~np.isfinite(out)] = np.nan
    return out


def classify_space(obs_dir, grid, free_eps_m, band_m, edge_thr=0.02):
    """0=未知 1=测量带 2=已知自由。"""
    obsd = json.loads((pathlib.Path(obs_dir) / 'observation.json').read_text())
    depth = np.load(pathlib.Path(obs_dir) / 'depth.npy').astype(np.float64)
    H, W = depth.shape
    dims = grid['dims']
    pts = np.stack([grid['X'].ravel(), grid['Y'].ravel(), grid['Z'].ravel()], axis=1)
    u, v, z = camera_io.project(pts, obsd['camera'])
    finite = np.isfinite(u) & np.isfinite(v) & np.isfinite(z)
    in_fov = finite & (u >= 0) & (u <= W - 1) & (v >= 0) & (v <= H - 1) & (z > 0)
    ui = np.clip(np.nan_to_num(u, nan=-1.0), 0, W - 1).astype(np.int64)
    vi = np.clip(np.nan_to_num(v, nan=-1.0), 0, H - 1).astype(np.int64)
    d = depth[vi, ui]
    use_edge = bool(edge_thr is not None and edge_thr > 0)
    d_near = min_filter3(depth)[vi, ui] if use_edge else d
    edge = depth_edge_mask(depth, edge_thr) if use_edge else np.zeros_like(depth, dtype=bool)
    valid = in_fov & np.isfinite(d) & (d > 0) & (d < 100.0)
    near_ok = in_fov & np.isfinite(d_near) & (d_near > 0)
    constrained = valid & ~edge[vi, ui]
    cls = np.zeros(len(pts), dtype=np.uint8)
    # 自由空间：到较近表面为止（不连续处保守），用 d_near
    cls[near_ok & (z < d_near - free_eps_m)] = 2
    # 测量带（表面约束）：只在非不连续像素上，用 d
    cls[constrained & (z >= d - free_eps_m) & (z <= d + band_m)] = 1
    out = cls.reshape(dims)
    stats = {'n_voxels': int(np.prod(dims)),
             'n_free': int((out == 2).sum()), 'n_band': int((out == 1).sum()),
             'n_unknown': int((out == 0).sum()),
             'n_in_fov': int(in_fov.sum()), 'n_valid_depth': int(valid.sum()),
             'n_depth_edge_px': int(edge.sum()),
             'n_constrained_px': int(constrained.sum()),
             'depth_edge_threshold_m': float(edge_thr),
             'valid_depth_frac': round(float(valid.mean()), 6),
             'depth_convention': 'positive_camera_minus_z (axis depth)',
             'free_eps_m': round(float(free_eps_m), 6),
             'band_m': round(float(band_m), 6)}
    return out, stats


def largest_component(occ):
    dims = occ.shape
    seen = np.zeros(dims, dtype=bool)
    best, best_n = [], 0
    from collections import deque
    for start in np.argwhere(occ):
        s = tuple(int(x) for x in start)
        if seen[s]:
            continue
        q = deque([s]); seen[s] = True; comp = []
        while q:
            i, j, k = q.popleft(); comp.append((i, j, k))
            for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                a, b, c = i + di, j + dj, k + dk
                if 0 <= a < dims[0] and 0 <= b < dims[1] and 0 <= c < dims[2] \
                        and occ[a, b, c] and not seen[a, b, c]:
                    seen[a, b, c] = True
                    q.append((a, b, c))
        if len(comp) > best_n:
            best_n, best = len(comp), comp
    keep = np.zeros(dims, dtype=bool)
    for q in best:
        keep[q] = True
    return keep, best_n


def marching_tets(occ, grid):
    """cell-center 采样 -> 等值面：位置 = origin + (index + 0.5 + t)*pitch。"""
    pitch = grid['pitch']; origin = grid['origin']; dims = occ.shape
    f = np.zeros((dims[0] + 2, dims[1] + 2, dims[2] + 2), dtype=np.uint8)
    f[1:-1, 1:-1, 1:-1] = occ.astype(np.uint8)
    nx, ny, nz = f.shape
    verts = {}
    tris = []

    def gid(i, j, k):
        return (i * ny + j) * nz + k

    def vpos(a, b, va, vb):
        key = (a, b) if a < b else (b, a)
        if key in verts:
            return verts[key]
        t = 0.5
        if va != vb:
            t = min(max((0.5 - float(va)) / (float(vb) - float(va)), 0.0), 1.0)
        pa = np.array(np.unravel_index(a, (nx, ny, nz)), dtype=np.float64)
        pb = np.array(np.unravel_index(b, (nx, ny, nz)), dtype=np.float64)
        p = pa + (pb - pa) * t
        p = origin + (p - 1.0 + 0.5) * pitch
        verts[key] = p
        return p

    tot = (f[:-1, :-1, :-1].astype(np.uint8) + f[1:, :-1, :-1] + f[:-1, 1:, :-1]
           + f[:-1, :-1, 1:] + f[1:, 1:, :-1] + f[1:, :-1, 1:]
           + f[:-1, 1:, 1:] + f[1:, 1:, 1:])
    for cell in np.argwhere((tot > 0) & (tot < 8)):
        i, j, k = (int(x) for x in cell)
        vals = np.array([f[i + c[0], j + c[1], k + c[2]] for c in CUBE], dtype=np.uint8)
        for tet in TETS:
            ids = [gid(i + CUBE[t][0], j + CUBE[t][1], k + CUBE[t][2]) for t in tet]
            vv = vals[list(tet)]
            ins = [n for n in range(4) if vv[n] >= 0.5]
            outs = [n for n in range(4) if vv[n] < 0.5]
            if len(ins) in (0, 4):
                continue
            if len(ins) == 1:
                a = ins[0]
                tris.append([vpos(ids[a], ids[outs[m]], vv[a], vv[outs[m]]) for m in range(3)])
            elif len(ins) == 3:
                a = outs[0]
                tris.append([vpos(ids[a], ids[ins[m]], vv[a], vv[ins[m]]) for m in range(3)])
            else:
                a, b = ins
                c, d_ = outs
                p_ac = vpos(ids[a], ids[c], vv[a], vv[c])
                p_ad = vpos(ids[a], ids[d_], vv[a], vv[d_])
                p_bc = vpos(ids[b], ids[c], vv[b], vv[c])
                p_bd = vpos(ids[b], ids[d_], vv[b], vv[d_])
                tris.append([p_ac, p_ad, p_bd])
                tris.append([p_ac, p_bd, p_bc])
    uniq, index, faces = [], {}, []
    for tri in tris:
        ids = []
        for p in tri:
            key = tuple(np.round(p, 9))
            if key not in index:
                index[key] = len(uniq); uniq.append(p)
            ids.append(index[key])
        if len(set(ids)) == 3:
            faces.append(ids)
    m = trimesh.Trimesh(np.asarray(uniq), np.asarray(faces), process=True)
    trimesh.repair.fix_normals(m)
    return m


def hidden_retention(parent, fused, grid, space, parent_inside, fused_occ):
    """未知区域内父先验保留情况 + 父/融合表面双向距离（父相对替代指标）。"""
    pitch = grid['pitch']
    unknown = (space == 0)
    core = unknown & parent_inside
    kept = core & fused_occ
    removed = core & ~fused_occ
    added = unknown & fused_occ & ~parent_inside
    carved = parent_inside & (space == 2)      # 被已知自由空间切掉的父先验
    out = {'unknown_core_parent_voxels': int(core.sum()),
           'kept_voxels': int(kept.sum()),
           'removed_voxels': int(removed.sum()),
           'added_voxels': int(added.sum()),
           'kept_ratio': round(float(kept.sum() / core.sum()), 5) if core.sum() else None,
           'removed_ratio': round(float(removed.sum() / core.sum()), 5) if core.sum() else None,
           'added_volume_m3': round(float(added.sum()) * pitch ** 3, 9),
           'carved_free_voxels': int(carved.sum()),
           'carved_free_volume_m3': round(float(carved.sum()) * pitch ** 3, 9)}
    try:
        from meshdist import point_to_mesh_distance
        pv, _ = trimesh.sample.sample_surface(parent, 1500, seed=0)
        idx = np.floor((pv - grid['origin']) / pitch).astype(np.int64)
        inb = ((idx >= 0) & (idx < np.asarray(grid['dims']))).all(axis=1)
        idx = np.clip(idx, 0, np.asarray(grid['dims']) - 1)
        pv = pv[inb & (space[idx[:, 0], idx[:, 1], idx[:, 2]] == 0)]
        if len(pv) > 5:
            d1 = point_to_mesh_distance(fused, pv, chunk=64) * 1000
            fv, _ = trimesh.sample.sample_surface(fused, 1500, seed=0)
            d2 = point_to_mesh_distance(parent, fv, chunk=64) * 1000
            out['parent_hidden_to_fused_mm'] = {'n': int(len(d1)),
                                                'med': round(float(np.median(d1)), 3),
                                                'p95': round(float(np.percentile(d1, 95)), 3)}
            out['fused_to_parent_mm'] = {'n': int(len(d2)),
                                         'med': round(float(np.median(d2)), 3),
                                         'p95': round(float(np.percentile(d2, 95)), 3)}
    except Exception as e:
        out['surface_distance_error'] = f'{type(e).__name__}: {e}'
    return out


def fuse(observation, parent_world, parent_id, out_dir, cfg, method='H5_F', seed=0):
    t0 = time.time()
    observation = pathlib.Path(observation)
    # 多父候选：并集先验（H5_F_multi）。单个父候选时行为不变。
    pw_list = ([pathlib.Path(parent_world)] if isinstance(parent_world, (str, pathlib.Path))
               else [pathlib.Path(x) for x in parent_world])
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    pitch = float(cfg['pitch_m'])
    meshes = [_load_mesh(p / 'body.stl') for p in pw_list]
    for i, mm in enumerate(meshes):
        if len(mm.faces) == 0:
            raise SystemExit(f'父候选没有三角面：{pw_list[i]}')
    parent = (meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes))
    vis = np.load(observation / 'visible_points.npy')
    if vis.ndim != 2 or vis.shape[1] != 3 or len(vis) < 10:
        raise SystemExit(f'visible_points 形状异常 {getattr(vis, "shape", None)}')
    grid = make_grid(parent, vis, pitch, int(cfg['margin_cells']))
    _d = np.load(observation / 'depth.npy')
    _valid = np.isfinite(_d) & (_d > 0) & (_d < 100.0)
    if _valid.mean() < 0.01:
        raise SystemExit(
            f'深度图有效像素比例 {_valid.mean():.4f} < 1%，拒绝融合（不要把坏观测当成全未知）')
    space, space_stats = classify_space(observation, grid,
                                        float(cfg['free_epsilon_m']),
                                        float(cfg['band_m']),
                                        (float(cfg['depth_edge_threshold_m'])
                                         if cfg.get('use_depth_edge_exclusion') else 0.0))
    space_stats['front_error_bound_mm'] = round(
        (float(cfg['free_epsilon_m']) + pitch / 2.0) * 1000, 3)
    parent_inside = np.zeros(grid['dims'], dtype=bool)
    parent_stats = {'parents': [], 'solid_method': []}
    for mm, pp in zip(meshes, pw_list):
        pi, st = parent_solid(mm, grid, int(cfg['parent_dilate_voxels']))
        parent_inside |= pi
        parent_stats['parents'].append(str(pp))
        parent_stats['solid_method'].append(st.get('solid_method'))
        parent_stats['watertight_parent'] = bool(parent_stats.get('watertight_parent', True)
                                                 and st.get('watertight_parent'))
    parent_stats['n_inside_voxels'] = int(parent_inside.sum())
    parent_stats['n_parents'] = len(meshes)
    keep_p = parent_inside & (space != 2)          # 未知区保留父先验，自由区被 carve
    from PIL import Image
    mask = np.array(Image.open(observation / 'mask.png').convert('L')) > 127
    mask_d = dilate2(mask, int(cfg['mask_dilate_px']))
    obsd = json.loads((observation / 'observation.json').read_text())
    H, W = mask.shape
    u, v, z = camera_io.project(
        np.stack([grid['X'].ravel(), grid['Y'].ravel(), grid['Z'].ravel()], axis=1),
        obsd['camera'])
    in_fov = (np.isfinite(u) & np.isfinite(v) & (z > 0)
              & (u >= 0) & (u <= W - 1) & (v >= 0) & (v <= H - 1))
    ui = np.clip(np.nan_to_num(u, nan=-1), 0, W - 1).astype(np.int64)
    vi = np.clip(np.nan_to_num(v, nan=-1), 0, H - 1).astype(np.int64)
    in_mask = in_fov & mask_d[vi, ui]
    # 可见面壳层：放在测量面之后（0.5 体素偏移），保证提取出的等值面不在观测面前方
    off = float(cfg.get('shell_offset_voxels', 0.5)) * pitch
    d_at = np.full(len(in_fov), np.nan)
    _valid = in_fov & np.isfinite(z)
    d_at[_valid] = np.load(observation / 'depth.npy')[vi[_valid], ui[_valid]]
    # 表面约束只在**测量邻域**内有效：下界 = 测量面 - eps + 偏移，上界 = 测量面 + band。
    # 更深的未知区域由父先验决定，不能沿轮廓一路填满（否则会把未知区变成实体）。
    band_m = float(cfg['band_m'])
    behind = (_valid & np.isfinite(d_at)
              & (z >= d_at - float(cfg['free_epsilon_m']) + off)
              & (z <= d_at + band_m + off))
    shell = (in_mask & behind).reshape(grid['dims'])
    occ = keep_p | shell
    before = occ.copy()
    occ, _ = largest_component(occ)
    comp_removed = int(before.sum() - occ.sum())
    mesh = marching_tets(occ, grid)
    if len(mesh.faces) == 0:
        raise SystemExit('融合后没有面')
    vol_before = abs(float(mesh.volume)) if mesh.is_watertight else None
    repaired = False
    if not mesh.is_watertight and cfg.get('fill_holes', True):
        trimesh.repair.fill_holes(mesh)
        trimesh.repair.fix_normals(mesh)
        repaired = True
    vol_after = abs(float(mesh.volume)) if mesh.is_watertight else None
    body = out / 'body.stl'
    mesh.export(body)
    # 检查点：网格一落盘就写 partial，进程在后面的度量/渲染里挂掉也能续跑
    (out / 'partial.json').write_text(json.dumps(
        {'schema': 'fusion-partial/v1', 'world_sha': sha_file(body),
         'pitch_m': pitch, 'parent_id': parent_id, 'method': method,
         'effective_config_sha': cfg.get('_sha'), 'ts': time.time(),
         'n_faces': int(len(mesh.faces)),
         'note': '网格已导出；manifest 尚未写出。可据此续跑度量而不重算融合。'},
        ensure_ascii=False, indent=2))
    retention = hidden_retention(parent, mesh, grid, space, parent_inside, occ)
    retention['n_parents'] = len(meshes)
    retention['shell_rule'] = {'lower': 'depth - eps + offset', 'upper': 'depth + band + offset',
                              'eps_m': float(cfg['free_epsilon_m']), 'band_m': band_m,
                              'offset_m': off}
    retention['shell_voxels'] = int(shell.sum())
    retention['shell_outside_parent_voxels'] = int((shell & ~parent_inside).sum())
    tmp = out / '_metric.stl'; mesh.export(tmp)
    metrics = {}
    try:
        import align
        # 面数超过 MuJoCo 单 mesh 上限时，用同场景多视觉 mesh 渲染（§11.3）：
        # 几何不变、相机不变，只是把同一个网格拆成若干块放进同一场景。
        _posed = None
        try:
            import v7_multimesh as _MM
            if len(mesh.faces) > _MM.MAX_FACES_DEFAULT:
                _pd = out / '_visual_parts'
                _parts, _meta = _MM.split_mesh(mesh, _MM.MAX_FACES_DEFAULT)
                _MM.write_world(_parts, _pd, sha_file(body), len(mesh.faces), {'split': _meta})
                _posed = str(_pd)
                metrics['visual_parts'] = _meta
        except Exception as _e:
            metrics['visual_parts_error'] = f'{type(_e).__name__}: {_e}'
        metrics = align.render_eval(mesh, str(observation), tmpdir=str(tmp),
                                    W=None, H=None, want_vis_pt=False,
                                    posed_dir=_posed)
        from meshdist import point_to_mesh_distance
        pw = vis
        if len(pw) > 1200:
            pw = pw[np.random.default_rng(0).choice(len(pw), 1200, replace=False)]
        nn = point_to_mesh_distance(mesh, pw, chunk=64)
        metrics['vis_pt_med_mm'] = round(float(np.median(nn)) * 1000, 3)
        metrics['vis_pt_p95_mm'] = round(float(np.percentile(nn, 95)) * 1000, 3)
        metrics['vis_pt_n'] = int(len(nn))
        metrics['vis_pt_strategy'] = 'deterministic_subset(n=1200,seed=0,chunk=64)'
    except Exception as e:
        metrics['error'] = f'{type(e).__name__}: {e}'
    finally:
        tmp.unlink(missing_ok=True)
    h_vis = float(obsd['visible']['H_vis'])
    thr_p95 = max(5.0, 0.03 * h_vis * 1000)
    strict = (metrics.get('mask_iou', 0) >= 0.85
              and metrics.get('vis_pt_p95_mm', 1e9) <= thr_p95
              and metrics.get('freespace_violation', 1) <= 0.05)
    if (out / 'partial.json').exists():
        try:
            (out / 'partial.json').unlink()
        except OSError:
            pass
    man = {
        'schema': 'fused-asset/v2', 'version': VERSION, 'method': method,
        'parent_id': parent_id, 'source_kind': method,
        'parent_source_kind': 'lux3d' if method == 'H5_F' else 'mirror',
        'coordinate_frame': 'world', 'parts': ['body.stl'],
        'world_sha': sha_file(body),
        'inputs': {'observation': str(observation),
                   'parent_world': [str(x) for x in pw_list],
                   'parent_mesh_sha': [sha_file(x / 'body.stl') for x in pw_list],
                   'effective_config_sha': cfg.get('_sha')},
        'grid': {'convention': 'cell-center',
                 'origin': [float(x) for x in grid['origin']],
                 'pitch_m': pitch, 'dims': [int(x) for x in grid['dims']],
                 'n_voxels': int(np.prod(grid['dims']))},
        'space': space_stats,
        'parent_solid': parent_stats,
        'growth': {'component_removed_voxels': comp_removed,
                   'component_kept_voxels': int(occ.sum()),
                   'shell_voxels': int(shell.sum()),
                   'filled_holes': repaired,
                   'volume_before_repair_m3': vol_before,
                   'volume_after_repair_m3': vol_after},
        'retention': retention,
        'watertight': bool(mesh.is_watertight),
        'volume_m3': round(abs(float(mesh.volume)), 9) if mesh.is_watertight else None,
        'bounds': [[float(x) for x in mesh.bounds[0]], [float(x) for x in mesh.bounds[1]]],
        'metrics': metrics,
        'strict': {'pass': bool(strict), 'iou_min': 0.85,
                   'p95_mm_threshold': round(thr_p95, 3),
                   'freespace_max': 0.05, 'h_vis_m': h_vis},
        'no_generated_hidden_contribution': bool(retention.get('kept_voxels', 0) == 0),
        'seconds': round(time.time() - t0, 2),
        'note': ('H5-F = 观测约束 + Lux3D 父候选隐藏几何；可见面由构造得到，'
                 '不证明 Lux3D 自己重建准确。' if method == 'H5_F' else
                 'B3-F = 镜像先验 + 同一观测约束；镜像来自可见点云，不是 Lux3D 生成。'),
    }
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    return man


def build_mirror(observation, out):
    obs = pathlib.Path(observation)
    pts = np.load(obs / 'visible_points.npy')
    x_min = float(pts[:, 0].min()); x_max = float(pts[:, 0].max())
    mir = pts.copy(); mir[:, 0] = 2.0 * x_max - pts[:, 0]
    both = np.vstack([pts, mir])
    import manifold3d as m3
    hm = m3.Manifold.hull_points(np.asarray(both, dtype=np.float32)).to_mesh()
    hull = trimesh.Trimesh(np.asarray(hm.vert_properties)[:, :3],
                           np.asarray(hm.tri_verts), process=True)
    hull.apply_translation([0, 0, -float(hull.bounds[0][2])])
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    body = out / 'body.stl'; hull.export(body)
    (out / 'manifest.json').write_text(json.dumps(
        {'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
         'parts': ['body.stl'], 'world_sha': sha_file(body),
         'source_kind': 'mirror_hypothesis',
         'split_plane_x': round(x_max, 5), 'front_x': round(x_min, 5),
         'visible_depth_m': round(x_max - x_min, 5),
         'note': 'B3-F mirror prior: visible points mirrored about deepest visible x'},
        indent=2))
    return out


def load_effective_config(base_path, overrides=None):
    """基准配置 + CLI 覆盖 -> 有效配置 + 身份哈希。缺失键直接报错。"""
    base = json.loads((ROOT / base_path).read_text())
    eff = {k: base[k] for k in ('pitch_m', 'margin_cells', 'free_epsilon_m',
                                'band_m', 'parent_dilate_voxels',
                                'mask_dilate_px', 'fill_holes',
                                'depth_edge_threshold_m',
                                'use_depth_edge_exclusion', 'shell_offset_voxels')}
    opts = dict(overrides or {})
    for k, v in opts.items():
        if v is not None:
            eff[k] = v
    eff['version'] = VERSION
    eff['base_config'] = base_path
    eff['base_config_sha256'] = sha_file(ROOT / base_path)
    eff['cli_overrides'] = {k: v for k, v in opts.items() if v is not None}
    if float(eff['band_m']) + float(eff['free_epsilon_m']) < float(eff['pitch_m']):
        raise SystemExit(
            'band_m + free_epsilon_m < pitch_m：可见面约束可能整列落空，出现缺口。'
            f"band={eff['band_m']} eps={eff['free_epsilon_m']} pitch={eff['pitch_m']}")
    eff['sha256'] = sha_obj({k: eff[k] for k in
                             ('pitch_m', 'margin_cells', 'free_epsilon_m',
                              'band_m', 'parent_dilate_voxels',
                              'mask_dilate_px', 'fill_holes',
                              'depth_edge_threshold_m',
                              'use_depth_edge_exclusion', 'shell_offset_voxels',
                              'version')})
    return eff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--observation', required=True)
    ap.add_argument('--parent-world', default=None, action='append',
                    help='可重复：多父候选按并集先验融合（H5_F_multi）')
    ap.add_argument('--parent-id', default='parent')
    ap.add_argument('--method', choices=['H5_F', 'B3_F'], required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--config', default='configs/unseen_v6_1_fusion.json')
    ap.add_argument('--pitch', type=float, default=None)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    eff = load_effective_config(a.config, {'pitch_m': a.pitch})
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / 'effective_config.json').write_text(json.dumps(eff, ensure_ascii=False, indent=2))
    cfg = dict(eff); cfg['_sha'] = eff['sha256']
    if a.method == 'B3_F' and not a.parent_world:
        mirror_dir = out.parent / f'{a.parent_id}_mirror_parent'
        build_mirror(a.observation, mirror_dir)
        a.parent_world = [str(mirror_dir)]
    if not a.parent_world:
        raise SystemExit('H5_F 需要 --parent-world')
    man = fuse(a.observation, (a.parent_world if len(a.parent_world) > 1 else a.parent_world[0]),
               a.parent_id, a.out, cfg,
               method=a.method, seed=a.seed)
    print(json.dumps({k: man[k] for k in ('version', 'method', 'parent_id', 'world_sha',
                                          'watertight', 'volume_m3', 'space',
                                          'retention', 'metrics', 'strict', 'seconds')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
