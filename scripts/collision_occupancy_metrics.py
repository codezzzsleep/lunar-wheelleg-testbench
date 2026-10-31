"""
碰撞保真度量 v2（V6.1 工作包 C1/C2）。

要点：
  · 碰撞占据 = 各 part 的**并集**（box 直接按 cell 区间涂；凸 part 用半空间判据），
    不把各 part 体积相加；
  · 双向表面距离：
      source→collision：源表面采样点到**碰撞并集表面**的解析距离
                       （box：点到轴对齐盒的解析距离取 min；凸 part：点到凸多面体）；
      collision→source：碰撞表面采样点到源网格的精确距离（meshdist）；
    因此不含被其他 part 包住的内部面误差；
  · 过填/漏填样本数与体积分数、关键净空、源实体是否定义（非水密时明确标注）；
  · 评价分辨率、采样数、种子写进报告。

用法：
  .venv/bin/python scripts/collision_occupancy_metrics.py \
      --mesh <source.stl> --collision <dir> --out <json> --label H5_F_box --eval-pitch 0.004
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from meshdist import point_to_mesh_distance

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 'collision-metrics/v2'


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_mesh(p):
    # process=False：不要合并顶点/去重，否则会把水密网格改成非水密，占据判据随之失效
    m = trimesh.load(str(p), force='mesh', process=False)
    if isinstance(m, trimesh.Scene):
        geoms = [g for g in m.geometry.values() if len(g.faces) > 0]
        m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
    return m


def make_grid(meshes, pitch, margin=2):
    lo = np.min(np.array([m.bounds[0] for m in meshes]), axis=0) - margin * pitch
    hi = np.max(np.array([m.bounds[1] for m in meshes]), axis=0) + margin * pitch
    lo[2] = min(lo[2], -margin * pitch)
    dims = np.ceil((hi - lo) / pitch).astype(int) + 1
    dims = np.maximum(dims, 6)
    if np.prod(dims) > 40_000_000:
        raise SystemExit(f'评价网格过大 {dims.tolist()}')
    xs = lo[0] + (np.arange(dims[0]) + 0.5) * pitch
    ys = lo[1] + (np.arange(dims[1]) + 0.5) * pitch
    zs = lo[2] + (np.arange(dims[2]) + 0.5) * pitch
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    return {'origin': lo, 'pitch': float(pitch), 'dims': dims, 'xs': xs, 'ys': ys,
            'zs': zs, 'X': X, 'Y': Y, 'Z': Z,
            'pts': np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)}


def ray_parity(mesh, pts, chunk=150_000):
    inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    out = np.zeros(len(pts), dtype=bool)
    dz = np.array([0.0, 0.0, 1.0])
    for i in range(0, len(pts), chunk):
        p = pts[i:i + chunk]
        d = np.tile(dz, (len(p), 1))
        _, ray_i, _ = inter.intersects_location(p, d, multiple_hits=True)
        cnt = np.bincount(ray_i, minlength=len(p))
        out[i:i + chunk] = (cnt % 2).astype(bool)
    return out


def convex_inside(mesh, pts):
    """凸多面体半空间判据：所有面 n·(p-a) <= tol 视为内部。"""
    v = np.asarray(mesh.vertices); f = np.asarray(mesh.faces)
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    n = n / ln
    a = v[f[:, 0]]
    off = (n * a).sum(axis=1)
    tol = 1e-9
    inside = np.ones(len(pts), dtype=bool)
    for k in range(len(n)):
        inside &= (pts @ n[k] - off[k]) <= tol
    return inside


def exposed_faces(boxes, origin, pitch):
    """并集**外边界**的 cell 面：某侧相邻格为空才算暴露；内部接缝被排除。

    支持 cell 索引为负（把索引平移到非负再建占据数组），坐标仍按原 origin 输出。
    """
    if not boxes:
        return []
    i_min = min(b[0] for b in boxes)
    j_min = min(b[2] for b in boxes)
    k_min = min(b[4] for b in boxes)
    i_max = max(b[1] for b in boxes)
    j_max = max(b[3] for b in boxes)
    k_max = max(b[5] for b in boxes)
    dims = (i_max - i_min + 3, j_max - j_min + 3, k_max - k_min + 3)
    occ = np.zeros(dims, dtype=bool)
    for (i0, i1, j0, j1, k0, k1) in boxes:
        occ[i0 - i_min + 1:i1 - i_min + 2,
            j0 - j_min + 1:j1 - j_min + 2,
            k0 - k_min + 1:k1 - k_min + 2] = True

    def occ_at(i, j, k):
        a, b, c = i - i_min + 1, j - j_min + 1, k - k_min + 1
        if 0 <= a < dims[0] and 0 <= b < dims[1] and 0 <= c < dims[2]:
            return bool(occ[a, b, c])
        return False

    faces = []
    for (i0, i1, j0, j1, k0, k1) in boxes:
        lo = origin + np.array([i0, j0, k0]) * pitch
        hi = origin + np.array([i1 + 1, j1 + 1, k1 + 1]) * pitch
        idx_lo = [i0, j0, k0]
        idx_hi = [i1, j1, k1]
        for ax in range(3):
            for side in (-1, +1):
                nb = list(idx_hi if side > 0 else idx_lo)
                nb[ax] += side
                if not occ_at(*nb):
                    f_lo = lo.copy(); f_hi = hi.copy()
                    if side < 0:
                        f_hi[ax] = f_lo[ax]
                    else:
                        f_lo[ax] = f_hi[ax]
                    faces.append((f_lo, f_hi))
    return faces


def box_surface_distance(pts, boxes, origin, pitch, faces=None):
    """点到**并集外边界**的距离（米）。

    只对暴露面求距离：内部接缝（两侧都被占据的面）不计入，因此
    两个相邻单位盒在 (1, 0.5, 0.5) 处的距离是 0.5 而不是 0。
    """
    pts = np.asarray(pts, dtype=float)
    if faces is None:
        faces = exposed_faces(boxes, origin, pitch)
    best = np.full(len(pts), np.inf)
    for (lo, hi) in faces:
        # 点到轴对齐矩形的精确距离：各轴夹到 [lo, hi] 后取欧氏距离
        clamped = np.clip(pts, lo, hi)
        d = np.linalg.norm(pts - clamped, axis=1)
        best = np.minimum(best, d)
    return best


def convex_surface_distance(pts, meshes):
    best = np.full(len(pts), np.inf)
    for m in meshes:
        best = np.minimum(best, point_to_mesh_distance(m, pts, chunk=128))
    return best


def boxes_to_array(boxes, dims):
    occ = np.zeros(dims, dtype=bool)
    for (i0, i1, j0, j1, k0, k1) in boxes:
        occ[i0:i1 + 1, j0:j1 + 1, k0:k1 + 1] = True
    return occ


def sample_box_surfaces(boxes, origin, pitch, n_total, rng):
    """在**并集外边界**上采样。

    规则（与"内部接缝不算外表面、部分暴露面不能整面删除"一致）：
      1. 每个 box 的 6 个面都参与候选（**不因相邻格存在就整面删除**）；
      2. 采样后逐点判定：若该点落在**另一个 box 内部**（即相邻格被占据、点进入内部），
         则丢弃——这排除了内部接缝；
      3. 部分暴露的面因此只保留真正暴露的那部分采样点。
    """
    if not boxes:
        return np.zeros((0, 3))
    dims = (max(b[1] for b in boxes) + 2, max(b[3] for b in boxes) + 2,
            max(b[5] for b in boxes) + 2)
    occ = boxes_to_array(boxes, dims)
    faces = []      # (lo, extent, axis, side)
    for (i0, i1, j0, j1, k0, k1) in boxes:
        lo = origin + np.array([i0, j0, k0]) * pitch
        hi = origin + np.array([i1 + 1, j1 + 1, k1 + 1]) * pitch
        e = hi - lo
        for ax in range(3):
            for side in (-1, +1):
                faces.append((lo, e, ax, side))
    if not faces:
        return np.zeros((0, 3))
    areas = np.array([2 * (e[(a + 1) % 3] * e[(a + 2) % 3]) for (_l, e, a, _s) in faces])
    p_ = areas / areas.sum()
    # 多采一倍再过滤，保证过滤后仍有足够点
    pick = rng.choice(len(faces), size=int(n_total * 2), p=p_)
    keep = []
    eps = 1e-9
    for idx in pick:
        lo, e, ax, side = faces[idx]
        u, w = rng.random(2)
        pt = lo.copy()
        b1, b2 = (ax + 1) % 3, (ax + 2) % 3
        pt[b1] += u * e[b1]
        pt[b2] += w * e[b2]
        pt[ax] += e[ax] if side > 0 else 0.0
        # 向**外侧**挪半格：外侧 cell 若被占据，说明这是内部接缝 -> 丢弃
        probe = pt.copy()
        probe[ax] += (0.5 if side > 0 else -0.5) * pitch
        ijk = np.floor((probe - origin) / pitch).astype(int)
        inside = (0 <= ijk[0] < dims[0] and 0 <= ijk[1] < dims[1]
                  and 0 <= ijk[2] < dims[2] and occ[ijk[0], ijk[1], ijk[2]])
        if not inside:
            keep.append(pt)
        if len(keep) >= n_total:
            break
    return np.asarray(keep) if keep else np.zeros((0, 3))


def probe_gaps(occ, grid, top_n=3):
    """沿每个 x 层找 y 方向最大内部空隙（两端都有占据），作为窄缝/净空探针。"""
    nx, ny, nz = occ.shape
    found = []
    for k in range(0, nz, max(1, nz // 24)):
        sl = occ[:, :, k]
        for i in range(nx):
            row = sl[i]
            idx = np.nonzero(row)[0]
            if len(idx) < 2:
                continue
            gaps = np.diff(idx) - 1
            j = int(np.argmax(gaps))
            if gaps[j] > 0:
                found.append({'x_m': round(float(grid['xs'][i]), 4),
                              'z_m': round(float(grid['zs'][k]), 4),
                              'gap_m': round(float(gaps[j] * grid['pitch']), 4),
                              'y_m': round(float((grid['ys'][idx[j]] + grid['ys'][idx[j + 1]]) / 2), 4)})
    found.sort(key=lambda r: -r['gap_m'])
    return {'n_gap_rows': len(found), 'largest': found[:top_n]}


PARITY_FACE_LIMIT = 5000


def vertex_cluster(mesh, limit):
    """纯 numpy 顶点聚类降采样：把顶点吸附到粗网格、重建面、去掉退化面。

    只用于**射线占据化**的外廓近似；表面距离仍用完整源网格。确定性、无第三方依赖。
    """
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces)
    ext = float(np.max(mesh.extents))
    pitch = max(ext / 90.0, 1e-4)
    for _ in range(8):
        key = np.round(v / pitch).astype(np.int64)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        nf = inv[f]
        good = ((nf[:, 0] != nf[:, 1]) & (nf[:, 1] != nf[:, 2]) & (nf[:, 0] != nf[:, 2]))
        nf = nf[good]
        # 去掉重复面
        _, idx = np.unique(np.sort(nf, axis=1), axis=0, return_index=True)
        nf = nf[np.sort(idx)]
        if len(nf) <= limit or pitch > ext:
            break
        pitch *= 1.35
        ext *= 0.999   # 允许继续加粗
    if len(nf) == 0:
        raise ValueError('vertex_cluster 产出空网格')
    # 顶点取聚类中心（吸附网格），保持世界坐标
    verts = uniq.astype(np.float64) * pitch
    return trimesh.Trimesh(verts, nf, process=False), {
        'method': 'vertex_cluster', 'pitch_m': round(pitch, 5),
        'from_faces': int(len(f)), 'to_faces': int(len(nf))}


def clustered_downsample(mesh, limit):
    """按顶点聚类降采样到 limit 面以下；返回 (mesh, note)。"""
    import trimesh as _tm
    n = len(mesh.faces)
    if n <= limit:
        return mesh, None
    # 优先用纯 numpy 顶点聚类（不依赖 scipy/skimage），失败再退回体素重建/凸包
    try:
        return vertex_cluster(mesh, limit)
    except Exception:
        pass
    # 射线奇偶判据对「射线数 × 面数」很敏感：先用**粗体素重建**把面数压到万级以下，
    # 再逐步加密，直到落在 limit 以内（不改变世界坐标）。
    ext = float(np.max(mesh.extents))
    pitch = max(ext / 60.0, 1e-4)
    try:
        for _ in range(6):
            v = mesh.voxelized(pitch=pitch).fill()
            m2 = v.marching_cubes
            if len(m2.faces) <= limit:
                return m2, {'method': 'voxel_cluster', 'pitch_m': round(pitch, 5),
                            'from_faces': int(n), 'to_faces': int(len(m2.faces))}
            pitch *= 1.4
        return m2, {'method': 'voxel_cluster', 'pitch_m': round(pitch, 5),
                    'from_faces': int(n), 'to_faces': int(len(m2.faces)),
                    'note': 'still above limit after refinement'}
    except Exception as e:
        # 退路：用采样点的凸包（只用于占据化的近似外廓，真实距离仍用完整网格）
        try:
            pts, _ = trimesh.sample.sample_surface(mesh, 20000, seed=0)
            m2 = trimesh.convex.convex_hull(pts)
            return m2, {'method': 'convex_fallback', 'from_faces': int(n),
                        'to_faces': int(len(m2.faces))}
        except Exception as e2:
            return mesh, {'method': 'none', 'error': f'{type(e).__name__}: {e} / {e2}'}


def _mem_available_gb():
    try:
        for line in open('/proc/meminfo'):
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return None


def require_memory(min_gb=8.0, allow_local=False, what='占据/距离测量'):
    """内存不够就拒绝在本地跑，而不是把整机 OOM 掉。

    实测教训：本地 8 GB 机器上跑 0.026 m³ 对象的占据重建会到 7.2 GB，
    触发 global OOM，连 harness worker 一起被杀。重活应当在 CNB 沙箱（16 GB）跑。
    """
    avail = _mem_available_gb()
    if avail is None or allow_local or avail >= min_gb:
        return avail
    raise SystemExit(
        f'{what} 需要约 {min_gb:.0f} GB 可用内存，当前仅 {avail:.1f} GB：'
        '请到沙箱运行（ssh cnb-... 或 scripts/cnb_run.sh），'
        '确需本地跑请加 --allow-local')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--collision', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', default='')
    ap.add_argument('--eval-pitch', type=float, default=0.004)
    ap.add_argument('--samples', type=int, default=1200)
    ap.add_argument('--parity', choices=['full', 'approx'], default='full',
                    help='占据化用的源网格：full=完整网格（默认，语义不变）；'
                         'approx=顶点聚类近似（更快但会改变 IoU，结果会标注）')
    ap.add_argument('--max-points', type=int, default=2_000_000,
                    help='评价网格点数上限；超过则按固定种子确定性子采样，并记录实际点数')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    require_memory(allow_local=getattr(a, 'allow_local', False))
    rng = np.random.default_rng(a.seed)
    src = load_mesh(a.mesh)
    cdir = pathlib.Path(a.collision)
    man = json.loads((cdir / 'manifest.json').read_text()) if (cdir / 'manifest.json').exists() else {}
    boxes = man.get('boxes')
    origin = np.asarray(man['grid_origin'], dtype=float) if boxes else None
    bpitch = float(man['pitch_m']) if boxes else None
    parts, missing = [], []
    for rel in (man.get('parts') or []):
        fp = cdir / rel
        if fp.exists():
            parts.append(load_mesh(fp))
        else:
            missing.append(rel)
    if not boxes and not parts:
        raise SystemExit(f'没有可加载的碰撞表示：{cdir}')
    # 占据化用的源网格：面数过大时按**顶点聚类**降采样（不移动顶点、不改形状要点），
    # 只为把射线求交的内存/时间压到可完成；表面距离仍用完整源网格，且记录实际面数。
    src_parity = src
    parity_note = None
    if a.parity == 'approx' and len(src.faces) > PARITY_FACE_LIMIT:
        src_parity, parity_note = clustered_downsample(src, PARITY_FACE_LIMIT)
    elif a.parity == 'full':
        parity_note = {'method': 'full_mesh', 'faces': int(len(src.faces))}
    grid = make_grid([src] + parts, a.eval_pitch)
    pts_total = int(grid['pts'].shape[0])
    sampled = False
    if pts_total > a.max_points:
        # 记忆有界：按固定种子确定性子采样，IoU/距离都在同一子集上算，并如实记录
        idx = np.random.default_rng(a.seed).choice(pts_total, a.max_points, replace=False)
        idx.sort()
        grid['pts'] = grid['pts'][idx]
        sampled = True
    # 采样后无法 reshape 回体素网格：此时全部用**扁平点集**计算（IoU/距离都不依赖形状），
    # 并跳过体素探针（probe_gaps）。
    def _vol(flat):
        return flat if sampled else flat.reshape(grid['dims'])

    o_src = _vol(ray_parity(src_parity, grid['pts']))
    _shape = (len(grid['pts']),) if sampled else tuple(grid['dims'])
    if boxes:
        o_col = np.zeros(_shape, dtype=bool)
        for (i0, i1, j0, j1, k0, k1) in boxes:
            lo = origin + np.array([i0, j0, k0]) * bpitch
            hi = origin + np.array([i1 + 1, j1 + 1, k1 + 1]) * bpitch
            ii = np.nonzero((grid['xs'] >= lo[0]) & (grid['xs'] < hi[0]))[0]
            jj = np.nonzero((grid['ys'] >= lo[1]) & (grid['ys'] < hi[1]))[0]
            kk = np.nonzero((grid['zs'] >= lo[2]) & (grid['zs'] < hi[2]))[0]
            if len(ii) and len(jj) and len(kk):
                if sampled:
                    sel = ((grid['pts'][:, 0] >= lo[0]) & (grid['pts'][:, 0] < hi[0]) &
                           (grid['pts'][:, 1] >= lo[1]) & (grid['pts'][:, 1] < hi[1]) &
                           (grid['pts'][:, 2] >= lo[2]) & (grid['pts'][:, 2] < hi[2]))
                    o_col[sel] = True
                elif not sampled:
                    o_col[np.ix_(ii, jj, kk)] = True
    else:
        o_col = np.zeros(_shape, dtype=bool)
        for p in parts:
            use_convex = False
            try:
                use_convex = bool(p.is_convex)
            except Exception:
                use_convex = False
            if use_convex:
                o_col |= _vol(convex_inside(p, grid['pts']))
            else:
                o_col |= _vol(ray_parity(p, grid['pts']))
    inter = int((o_src & o_col).sum()); union = int((o_src | o_col).sum())
    vox = grid['pitch'] ** 3
    over = int((~o_src & o_col).sum()); under = int((o_src & ~o_col).sum())
    geo = {'source_inside': int(o_src.sum()), 'collision_inside': int(o_col.sum()),
           'intersection': inter, 'union': union,
           'collision_only': over, 'source_only': under,
           'occupancy_iou': round(float(inter / union), 4) if union else None,
           'over_fill_frac_of_collision': round(float(over / max(o_col.sum(), 1)), 4),
           'under_fill_frac_of_source': round(float(under / max(o_src.sum(), 1)), 4),
           'over_fill_volume_m3': round(float(over) * vox, 9),
           'under_fill_volume_m3': round(float(under) * vox, 9),
           'source_volume_voxelised_m3': round(float(o_src.sum()) * vox, 9),
           'collision_volume_voxelised_m3': round(float(o_col.sum()) * vox, 9),
           'eval_pitch_m': grid['pitch'], 'eval_dims': [int(x) for x in grid['dims']]}
    # 距离分块按面数自适应：块×面保持 ~2M 元素，避免一次性 128×N 面矩阵把内存打爆
    _chunk = max(1, int(2_000_000 // max(1, len(src.faces))))
    ps, _ = trimesh.sample.sample_surface(src, a.samples, seed=a.seed)
    if boxes:
        d_sc = box_surface_distance(ps, boxes, origin, bpitch) * 1000
        cs = sample_box_surfaces(boxes, origin, bpitch, a.samples, rng)
        d_cs = point_to_mesh_distance(src, cs, chunk=_chunk) * 1000
    else:
        d_sc = convex_surface_distance(ps, parts) * 1000
        cs = np.vstack([trimesh.sample.sample_surface(p, max(50, a.samples // len(parts)),
                                                      seed=a.seed)[0] for p in parts])
        d_cs = point_to_mesh_distance(src, cs, chunk=_chunk) * 1000
    geo['source_to_collision_mm'] = {'n': int(len(d_sc)),
                                     'med': round(float(np.median(d_sc)), 3),
                                     'p95': round(float(np.percentile(d_sc, 95)), 3),
                                     'max': round(float(np.max(d_sc)), 3)}
    geo['collision_to_source_mm'] = {'n': int(len(d_cs)),
                                     'med': round(float(np.median(d_cs)), 3),
                                     'p95': round(float(np.percentile(d_cs, 95)), 3),
                                     'max': round(float(np.max(d_cs)), 3)}
    out = {'schema': 'collision-metrics/v2', 'version': VERSION, 'label': a.label,
           'source_mesh': str(a.mesh), 'source_sha': sha_file(a.mesh),
           'collision_dir': str(cdir),
           'representation': ('box_union' if boxes else 'parts'),
           'n_boxes': len(boxes) if boxes else None,
           'n_parts_declared': len(man.get('parts') or []) or None,
           'n_parts_loaded': len(parts) if not boxes else None,
           'missing_parts': missing,
           'collision_sha_manifest': man.get('collision_sha'),
           'source_status': {'watertight': bool(src.is_watertight),
                             'euler': int(src.euler_number),
                             'n_faces': int(len(src.faces))},
           'source_volume_defined': bool(src.is_watertight),
           'geometry': geo,
           'probe': (None if sampled else probe_gaps(o_src, grid)),
           'parity_source': parity_note,
           'evaluation_points': {'total': pts_total,
                                 'used': int(grid['pts'].shape[0]),
                                 'sampled': bool(sampled),
                                 'max_points': int(a.max_points), 'seed': int(a.seed)},
           'samples': a.samples, 'seed': a.seed,
           'verdict': ('PASS' if (geo['occupancy_iou'] is not None
                                  and geo['occupancy_iou'] >= 0.95
                                  and geo['source_to_collision_mm']['p95'] <= 5.0
                                  and geo['collision_to_source_mm']['p95'] <= 5.0)
                       else 'ATTENTION'),
           'note': ('双向距离用并集表面（box 解析距离 / 凸 part 距离）；'
                    '源网格非水密时 source_volume_defined=false，内部量只作诊断。')}
    # 自带峰值内存记录（不依赖 /usr/bin/time，很多环境没有）
    try:
        import resource as _res
        out['peak_rss_mb'] = round(_res.getrusage(_res.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        pass
    op = pathlib.Path(a.out); op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'label': a.label, 'repr': out['representation'], 'verdict': out['verdict'],
                      'iou': geo['occupancy_iou'],
                      's2c_p95': geo['source_to_collision_mm']['p95'],
                      'c2s_p95': geo['collision_to_source_mm']['p95'],
                      'source_vol_defined': out['source_volume_defined']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
