"""
H5-F / B3-F：观测约束融合（V6 工作包 C）。

只允许输入：
  - 首视角 observation（RGB-D / mask / camera / visible points）；
  - 已配准的父候选 world 网格（Lux3D 或 mirror 先验）；
  - 冻结的融合参数。
不读取任何 truth 网格、背面类别或评价结果。

实现：
  1. 世界坐标体素占据：父候选射线奇偶 + 小闭运算；
  2. 沿有效深度射线 carving 相机—已测表面之间的已知自由空间；
  3. 已测表面附近强制实体壳；
  4. 地面 cap 闭合；
  5. marching tetrahedra 输出水密实体；
  6. 区域来源标签 observed_surface / generated_hidden / ground_cap / unknown。

用法：
  MUJOCO_GL=osmesa .venv/bin/python scripts/fuse_observed.py \
    --observation runs/unseen/recovery_r3/obs_R01 \
    --parent-world runs/unseen/delivery_v5/v5_20261029/candidates/C_R01_face12k/world/align \
    --parent-id C_R01_face12k --method H5_F \
    --out runs/unseen/delivery_v6/v6_.../fusion/C_R01_face12k_H5F \
    --pitch 0.004
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
CUBE = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                 [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=np.int64)
# 立方体 6 个四面体（共享 0-6 对角线）
TETS = [(0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6),
        (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6)]


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _load_mesh(p):
    m = trimesh.load(str(p), force='mesh', process=False)
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate([g for g in m.geometry.values() if len(g.faces)])
    return m


def _dilate6(a):
    out = a.copy()
    for ax in range(3):
        out |= np.roll(a, 1, ax)
        out |= np.roll(a, -1, ax)
    return out


def _erode6(a):
    out = a.copy()
    for ax in range(3):
        out &= np.roll(a, 1, ax)
        out &= np.roll(a, -1, ax)
    return out


def _closing(a):
    return _erode6(_dilate6(a))


def _ray_parity(mesh, pts):
    """世界点沿 +z 射线的奇偶；返回 bool inside。"""
    inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    d = np.tile(np.array([0.0, 0.0, 1.0]), (len(pts), 1))
    loc, ray_i, tri_i = inter.intersects_location(pts, d, multiple_hits=True)
    cnt = np.bincount(ray_i, minlength=len(pts))
    return (cnt % 2).astype(bool)


def _parent_solid(mesh, origin, dims, pitch):
    """
    父候选占据：三角面采样成体素壳 -> 膨胀封小孔 -> 从边界 flood fill 外部。
    比射线奇偶更稳，适合有水密缺陷的生成网格；同时保留表面形状。
    """
    area = float(mesh.area)
    n = int(np.clip(area / (pitch * pitch) * 2.0, 20000, 250000))
    pts, _ = trimesh.sample.sample_surface(mesh, n, seed=0)
    shell = np.zeros(dims, dtype=bool)
    idx = np.floor((np.asarray(pts) - origin) / pitch).astype(np.int64)
    inb = ((idx >= 0) & (idx < dims)).all(axis=1)
    idx = idx[inb]
    shell[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    for _ in range(1):
        shell = _dilate6(shell)
    # flood fill 外部（6 邻域）
    from collections import deque
    outside = np.zeros(dims, dtype=bool)
    q = deque()
    for i in range(dims[0]):
        for j in range(dims[1]):
            for k in (0, dims[2] - 1):
                if not shell[i, j, k] and not outside[i, j, k]:
                    outside[i, j, k] = True; q.append((i, j, k))
    for i in (0, dims[0] - 1):
        for j in range(dims[1]):
            for k in range(dims[2]):
                if not shell[i, j, k] and not outside[i, j, k]:
                    outside[i, j, k] = True; q.append((i, j, k))
    for j in (0, dims[1] - 1):
        for i in range(dims[0]):
            for k in range(dims[2]):
                if not shell[i, j, k] and not outside[i, j, k]:
                    outside[i, j, k] = True; q.append((i, j, k))
    while q:
        i, j, k = q.popleft()
        for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            a, b, c = i + di, j + dj, k + dk
            if 0 <= a < dims[0] and 0 <= b < dims[1] and 0 <= c < dims[2] \
                    and not shell[a, b, c] and not outside[a, b, c]:
                outside[a, b, c] = True
                q.append((a, b, c))
    inside = ~outside
    if inside.sum() < 100 or inside.sum() > 0.98 * np.prod(dims):
        # 退化时回退射线奇偶
        pts2 = np.stack(np.meshgrid(
            origin[0] + np.arange(dims[0]) * pitch,
            origin[1] + np.arange(dims[1]) * pitch,
            origin[2] + np.arange(dims[2]) * pitch, indexing='ij'), -1).reshape(-1, 3)
        inside = _ray_parity(mesh, pts2).reshape(dims)
    return inside


def _grid(observation, parent, pitch, margin_cells=3):
    obsd = json.loads((observation / 'observation.json').read_text())
    pts = np.load(observation / 'visible_points.npy')
    b = parent.bounds
    lo = np.minimum(b[0], pts.min(axis=0) if len(pts) else b[0])
    hi = np.maximum(b[1], pts.max(axis=0) if len(pts) else b[1])
    lo = np.minimum(lo, [0.0, 0.0, 0.0])
    hi = np.maximum(hi, [0.0, 0.0, 0.0])
    margin = margin_cells * pitch
    origin = lo - margin
    # 地面从 z=0 起，不把体素沉到地下；否则底盖会落到 -margin
    origin[2] = 0.0
    dims = np.ceil((hi + margin - origin) / pitch).astype(int) + 1
    dims = np.maximum(dims, 8)
    if np.prod(dims) > 8_000_000:
        raise SystemExit(f'体素网格过大 {dims.tolist()}，请增大 pitch')
    xs = origin[0] + np.arange(dims[0]) * pitch
    ys = origin[1] + np.arange(dims[1]) * pitch
    zs = origin[2] + np.arange(dims[2]) * pitch
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    return {'obsd': obsd, 'origin': origin, 'pitch': pitch, 'dims': dims,
            'xs': xs, 'ys': ys, 'zs': zs, 'X': X, 'Y': Y, 'Z': Z}


def _mark_free(g, grid, step_px=8, chunk=1800, n_samples=240):
    """沿每条有效深度射线标记相机到表面之前的自由体素。"""
    obsd = g['obsd']
    depth = np.load(g['observation'] / 'depth.npy').astype(np.float64)
    snap = obsd['camera']
    K = obsd['intrinsics']
    R = np.asarray(snap['R_world_from_camera'], dtype=np.float64).reshape(3, 3)
    cam = np.asarray(snap['world_pos'], dtype=np.float64)
    H, W = depth.shape
    vs, us = np.mgrid[0:H:step_px, 0:W:step_px]
    us = us.ravel(); vs = vs.ravel()
    d = depth[vs, us]
    ok = np.isfinite(d) & (d > 0.05) & (d < 20.0)
    us, vs, d = us[ok], vs[ok], d[ok]
    zmax = np.minimum(d - 0.006, 4.0)
    # 对每条射线用相同数量的 z 采样；无效尾部靠 mask
    ts = np.linspace(0.04, 1.0, n_samples)[None, :]
    z = 0.04 + (zmax[:, None] - 0.04) * ts
    z = np.where(z <= (zmax[:, None] - 1e-6), z, np.nan)
    x = (us[:, None] - K['cx']) / K['fx'] * z
    y = -(vs[:, None] - K['cy']) / K['fy'] * z
    pc = np.stack([x, y, -z], axis=-1)                 # (N,S,3)
    pw = pc @ R.T + cam
    free = np.zeros(g['dims'], dtype=bool)
    origin = g['origin']; pitch = g['pitch']; dims = g['dims']
    for i in range(0, len(pw), chunk):
        p = pw[i:i + chunk].reshape(-1, 3)
        valid = np.isfinite(p).all(axis=1)
        p = p[valid]
        if not len(p):
            continue
        idx = np.floor((p - origin) / pitch).astype(np.int64)
        inb = ((idx >= 0) & (idx < dims)).all(axis=1)
        idx = idx[inb]
        free[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return free


def _free_by_projection(g):
    """逐体素投影：相机到已测表面之前的体素标为已知自由空间。
    这比稀疏射线采样更完整；未知深度像素不标自由。"""
    obsd = g['obsd']; depth = np.load(g['observation'] / 'depth.npy')
    pts = np.stack([g['X'].ravel(), g['Y'].ravel(), g['Z'].ravel()], axis=1)
    u, v, z = camera_io.project(pts, obsd['camera'])
    ok = np.isfinite(u) & np.isfinite(v) & np.isfinite(z) & (z > 0.01)
    ui = np.clip(np.round(np.nan_to_num(u, nan=-1e9)).astype(int), 0, depth.shape[1] - 1)
    vi = np.clip(np.round(np.nan_to_num(v, nan=-1e9)).astype(int), 0, depth.shape[0] - 1)
    dd = depth[vi, ui]
    valid = ok & np.isfinite(dd) & (dd > 0) & (dd < 100.0)
    free = np.zeros(g['dims'], dtype=bool)
    hit = valid & (z < dd + 0.006)
    free.reshape(-1)[np.nonzero(hit)[0]] = True
    return free


def _observed_shell(g, grid, step_px=2, radius=1):
    obsd = g['obsd']; depth = np.load(g['observation'] / 'depth.npy')
    mask = np.array(__import__('PIL.Image', fromlist=['Image']).open(
        g['observation'] / 'mask.png').convert('L')) > 127
    K = obsd['intrinsics']; snap = obsd['camera']
    R = np.asarray(snap['R_world_from_camera'], dtype=np.float64).reshape(3, 3)
    cam = np.asarray(snap['world_pos'], dtype=np.float64)
    vs, us = np.mgrid[0:depth.shape[0]:step_px, 0:depth.shape[1]:step_px]
    vs = vs.ravel(); us = us.ravel()
    sel = mask[vs, us] & np.isfinite(depth[vs, us]) & (depth[vs, us] > 0)
    us, vs = us[sel], vs[sel]
    z = depth[vs, us]
    x = (us - K['cx']) / K['fx'] * z
    y = -(vs - K['cy']) / K['fy'] * z
    pc = np.stack([x, y, -z], axis=1)
    pw = pc @ R.T + cam
    # 观测壳放到测量点后方（远离相机）0.75 voxel，避免 marching 表面比观测更靠前
    d = pw - cam
    n = np.linalg.norm(d, axis=1, keepdims=True)
    n[n == 0] = 1.0
    pw = pw + (d / n) * (1.0 * g['pitch'])
    shell = np.zeros(g['dims'], dtype=bool)
    origin = g['origin']; pitch = g['pitch']; dims = g['dims']
    idx = np.floor((pw - origin) / pitch).astype(np.int64)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                q = idx + [dx, dy, dz]
                inb = ((q >= 0) & (q < dims)).all(axis=1)
                q = q[inb]
                shell[q[:, 0], q[:, 1], q[:, 2]] = True
    return shell


def _marching_tets(occ, origin, pitch):
    """占据体素 -> 水密三角网格（marching tetrahedra，纯 numpy）。"""
    f = np.zeros((occ.shape[0] + 2, occ.shape[1] + 2, occ.shape[2] + 2), dtype=np.uint8)
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
            t = (0.5 - float(va)) / (float(vb) - float(va))
            t = min(max(t, 0.0), 1.0)
        pa = np.array(np.unravel_index(a, (nx, ny, nz)), dtype=np.float64)
        pb = np.array(np.unravel_index(b, (nx, ny, nz)), dtype=np.float64)
        p = pa + (pb - pa) * t
        # padding 偏移 -1
        p = origin + (p - 1.0) * pitch
        verts[key] = p
        return p

    active = np.argwhere(
        (f[:-1, :-1, :-1] + f[1:, :-1, :-1] + f[:-1, 1:, :-1] + f[:-1, :-1, 1:] +
         f[1:, 1:, :-1] + f[1:, :-1, 1:] + f[:-1, 1:, 1:] + f[1:, 1:, 1:] > 0) &
        (f[:-1, :-1, :-1] + f[1:, :-1, :-1] + f[:-1, 1:, :-1] + f[:-1, :-1, 1:] +
         f[1:, 1:, :-1] + f[1:, :-1, 1:] + f[:-1, 1:, 1:] + f[1:, 1:, 1:] < 8))
    for (i, j, k) in active:
        vals = np.array([f[i + c[0], j + c[1], k + c[2]] for c in CUBE], dtype=np.uint8)
        for tet in TETS:
            ids = [gid(i + CUBE[t][0], j + CUBE[t][1], k + CUBE[t][2]) for t in tet]
            vv = vals[list(tet)]
            inside = [n for n in range(4) if vv[n] >= 0.5]
            outside = [n for n in range(4) if vv[n] < 0.5]
            if len(inside) in (0, 4):
                continue
            if len(inside) == 1:
                a = inside[0]; bs = outside
                p0 = vpos(ids[a], ids[bs[0]], vv[a], vv[bs[0]])
                p1 = vpos(ids[a], ids[bs[1]], vv[a], vv[bs[1]])
                p2 = vpos(ids[a], ids[bs[2]], vv[a], vv[bs[2]])
                tri = [p0, p1, p2]
                n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                if np.dot(n, np.mean(tri, axis=0) - p0) < 0:
                    tri = [p0, p2, p1]
                tris.append(tri)
            elif len(inside) == 3:
                a = outside[0]; bs = inside
                p0 = vpos(ids[a], ids[bs[0]], vv[a], vv[bs[0]])
                p1 = vpos(ids[a], ids[bs[1]], vv[a], vv[bs[1]])
                p2 = vpos(ids[a], ids[bs[2]], vv[a], vv[bs[2]])
                tri = [p0, p1, p2]
                n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                if np.dot(n, np.mean(tri, axis=0) - p0) < 0:
                    tri = [p0, p2, p1]
                tris.append(tri)
            else:  # 2-2
                a, b = inside
                c, d = outside
                p_ac = vpos(ids[a], ids[c], vv[a], vv[c])
                p_ad = vpos(ids[a], ids[d], vv[a], vv[d])
                p_bc = vpos(ids[b], ids[c], vv[b], vv[c])
                p_bd = vpos(ids[b], ids[d], vv[b], vv[d])
                for tri in ([p_ac, p_ad, p_bd], [p_ac, p_bd, p_bc]):
                    n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                    if np.dot(n, (p_bd + p_ac) / 2 - (p_ac + p_ad + p_bd) / 3) < 0:
                        pass
                    tris.append(tri)
    # 去重顶点
    uniq = []
    index = {}
    faces = []
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


def _silhouette_constrain(g, occ, dilate_px=2):
    """物体从该相机看必须落在观测轮廓内；否则就是自由空间里的多出面。"""
    from PIL import Image
    mask = np.array(Image.open(g['observation'] / 'mask.png').convert('L')) > 127
    for _ in range(dilate_px):
        mask = (mask | np.roll(mask, 1, 0) | np.roll(mask, -1, 0)
                | np.roll(mask, 1, 1) | np.roll(mask, -1, 1))
    pts = np.stack([g['X'].ravel(), g['Y'].ravel(), g['Z'].ravel()], axis=1)
    u, v, z = camera_io.project(pts, g['obsd']['camera'])
    ok = np.isfinite(u) & np.isfinite(v) & np.isfinite(z) & (z > 0)
    ui = np.clip(np.round(np.nan_to_num(u, nan=-1e9)).astype(int), 0, mask.shape[1] - 1)
    vi = np.clip(np.round(np.nan_to_num(v, nan=-1e9)).astype(int), 0, mask.shape[0] - 1)
    inside = ok & mask[vi, ui]
    keep = inside.reshape(g['dims'])
    return occ & keep


def _clamp_visible(mesh, g):
    """把仍在观测表面前方的融合顶点沿相机射线压回到表面后方 1 mm。"""
    depth = np.load(g['observation'] / 'depth.npy')
    from PIL import Image
    mask = np.array(Image.open(g['observation'] / 'mask.png').convert('L')) > 127
    u, v, z = camera_io.project(mesh.vertices, g['obsd']['camera'])
    ok = np.isfinite(u) & np.isfinite(v) & np.isfinite(z) & (z > 1e-6)
    ui = np.clip(np.round(np.nan_to_num(u, nan=-1e9)).astype(int), 0, depth.shape[1] - 1)
    vi = np.clip(np.round(np.nan_to_num(v, nan=-1e9)).astype(int), 0, depth.shape[0] - 1)
    dd = depth[vi, ui]
    valid = ok & mask[vi, ui] & np.isfinite(dd) & (dd > 0)
    bad = valid & (z < dd - 0.001)
    if bad.any():
        cam = np.asarray(g['obsd']['camera']['world_pos'], dtype=float)
        scale = (dd[bad] + 0.006) / z[bad]
        mesh.vertices[bad] = cam + (mesh.vertices[bad] - cam) * scale[:, None]
    return mesh


def _labels(g, grid, occ_parent, free, shell, ground):
    lab = np.zeros(g['dims'], dtype=np.uint8)
    lab[occ_parent & ~free] = 1          # generated / parent hidden (candidate)
    lab[shell] = 2                       # observed surface
    lab[ground] = 3                      # ground cap
    lab[~ (occ_parent | shell | ground)] = 0
    return lab


def _classify_vertices(mesh, g, grid, lab):
    # 最近体素标签
    idx = np.floor((np.asarray(mesh.vertices) - g['origin']) / g['pitch']).astype(np.int64)
    idx = np.clip(idx, 0, np.asarray(g['dims']) - 1)
    l = lab[idx[:, 0], idx[:, 1], idx[:, 2]]
    # 用投影深度再确认 observed surface（体素标签可能受邻居影响）
    obsd = g['obsd']; depth = np.load(g['observation'] / 'depth.npy')
    from PIL import Image
    mask = np.array(Image.open(g['observation'] / 'mask.png').convert('L')) > 127
    u, v, z = camera_io.project(mesh.vertices, obsd['camera'])
    ok = np.isfinite(u) & np.isfinite(v) & np.isfinite(z) & (z > 0)
    u = np.nan_to_num(u, nan=-1e9); v = np.nan_to_num(v, nan=-1e9)
    ui = np.clip(np.round(u).astype(int), 0, depth.shape[1] - 1)
    vi = np.clip(np.round(v).astype(int), 0, depth.shape[0] - 1)
    dd = depth[vi, ui]
    obs = ok & mask[vi, ui] & np.isfinite(dd) & (np.abs(z - dd) < 3 * g['pitch'])
    l = np.where(obs, 2, l)
    return l


def fuse(observation, parent_world, method, parent_id, out, pitch, seed=0,
         step_px=8, keep_two_res=False):
    t0 = time.time()
    observation = pathlib.Path(observation)
    parent_world = pathlib.Path(parent_world)
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    pm = _load_mesh(parent_world / 'body.stl')
    if len(pm.faces) == 0:
        raise SystemExit('父候选没有三角面')
    g = _grid(observation, pm, pitch)
    g['observation'] = observation
    X, Y, Z = g['X'], g['Y'], g['Z']
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    parent_occ = _parent_solid(pm, g['origin'], g['dims'], pitch)
    free = _free_by_projection(g)
    shell = _observed_shell(g, None, step_px=1, radius=0)
    ground = np.zeros(g['dims'], dtype=bool)
    # 只用自由空间 carving 父候选；观测壳强制实体；地面不做扩展板
    hidden = parent_occ & ~free
    occ = hidden | shell
    occ = _silhouette_constrain(g, occ, dilate_px=1)
    lab = _labels(g, None, parent_occ, free, shell, ground)
    # 最小连通体：保留最大 6-连通分量（避免孤立噪点）
    seen = np.zeros_like(occ, dtype=bool)
    best = None
    for start in np.argwhere(occ):
        if seen[tuple(start)]:
            continue
        stack = [tuple(start)]; comp = []
        seen[tuple(start)] = True
        while stack:
            q = stack.pop(); comp.append(q)
            i, j, k = q
            for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                a, b, c = i + di, j + dj, k + dk
                if 0 <= a < occ.shape[0] and 0 <= b < occ.shape[1] and 0 <= c < occ.shape[2] \
                        and occ[a, b, c] and not seen[a, b, c]:
                    seen[a, b, c] = True
                    stack.append((a, b, c))
        if best is None or len(comp) > len(best):
            best = comp
    keep = np.zeros_like(occ)
    for q in (best or []):
        keep[q] = True
    occ = keep
    mesh = _marching_tets(occ, g['origin'], pitch)
    if len(mesh.faces) == 0:
        raise SystemExit('融合后没有面')
    try:
        trimesh.repair.fill_holes(mesh)
        trimesh.repair.fix_normals(mesh)
    except Exception:
        pass
    mesh = _clamp_visible(mesh, g)
    trimesh.repair.fix_normals(mesh)
    body = out / 'body.stl'
    mesh.export(body)
    labv = _classify_vertices(mesh, g, None, lab)
    counts = {int(k): int((labv == k).sum()) for k in (0, 1, 2, 3)}
    # 面来源：三顶点多数
    fl = labv[mesh.faces]
    fam = np.array([np.bincount(r, minlength=4).argmax() for r in fl])
    fcounts = {int(k): int((fam == k).sum()) for k in (0, 1, 2, 3)}
    metrics = None
    tmp = out / 'metric_tmp.stl'
    mesh.export(tmp)
    try:
        import align
        # 先用 render_eval 的轮廓/自由空间/深度，P95 单独用 chunk=64 计算，避免 4 mm 内存峰值
        metrics = align.render_eval(mesh, str(observation), tmpdir=str(tmp),
                                    W=None, H=None, want_vis_pt=False)
        try:
            from meshdist import point_to_mesh_distance
            pw = np.load(observation / 'visible_points.npy')
            rng = np.random.default_rng(0)
            if len(pw) > 1200:
                pw = pw[rng.choice(len(pw), 1200, replace=False)]
            nn = point_to_mesh_distance(mesh, pw, chunk=64)
            metrics['vis_pt_med_mm'] = round(float(np.median(nn)) * 1000, 3)
            metrics['vis_pt_p95_mm'] = round(float(np.percentile(nn, 95)) * 1000, 3)
            metrics['vis_pt_n'] = int(len(nn))
            metrics['vis_pt_strategy'] = 'deterministic_subset(n=1200,seed=0,chunk=64)'
        except Exception as e:
            metrics['vis_pt_error'] = f'{type(e).__name__}: {e}'
    except Exception as e:
        metrics = {'error': f'{type(e).__name__}: {e}'}
    man = {
        'schema': 'fused-asset/v1', 'method': method, 'parent_id': parent_id,
        'source_kind': method, 'parent_source_kind': 'lux3d' if method == 'H5_F' else 'mirror',
        'coordinate_frame': 'world', 'parts': ['body.stl'],
        'world_sha': sha(body), 'pitch_m': pitch,
        'fusion_version': 'fuse-observed/v1',
        'inputs': {
            'observation': str(observation),
            'observation_sha': json.loads((observation / 'observation.json').read_text())
                               .get('observation_sha'),
            'parent_world': str(parent_world),
            'parent_world_sha': json.loads((parent_world / 'manifest.json').read_text())
                                .get('world_sha') if (parent_world / 'manifest.json').exists() else None,
            'parent_mesh_sha': sha(parent_world / 'body.stl'),
        },
        'grid': {'origin': [float(x) for x in g['origin']],
                 'dims': [int(x) for x in g['dims']], 'pitch_m': pitch,
                 'n_voxels': int(np.prod(g['dims']))},
        'regions': {'vertex_counts': counts, 'face_counts': fcounts,
                    'observed_surface': 'camera-constrained shell',
                    'generated_hidden': 'parent interior outside observed free space',
                    'ground_cap': 'z<=1.5 pitch', 'unknown_or_unassigned': 'else'},
        'watertight': bool(mesh.is_watertight),
        'volume_m3': round(abs(float(mesh.volume)), 9) if mesh.is_watertight else None,
        'bounds': [[float(x) for x in mesh.bounds[0]], [float(x) for x in mesh.bounds[1]]],
        'metrics': metrics,
        'no_generated_hidden_contribution': bool(fcounts.get(1, 0) == 0),
        'seconds': round(time.time() - t0, 2),
        'note': ('H5-F：观测约束 + Lux3D 父候选隐藏几何；可见面部分由构造得到，'
                 '不证明 Lux3D 自己重建准确。不能标成纯 lux3d strict pass。'
                 if method == 'H5_F' else
                 'B3-F：镜像先验 + 同一观测约束。镜像来自可见点云，不是 Lux3D 生成。'),
    }
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    (out / 'fusion.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    return man


def build_mirror(observation, out):
    """B3-F 父先验：可见点云关于最深可见 x 镜像 -> manifold hull。"""
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
    man = {'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
           'parts': ['body.stl'], 'world_sha': sha(body),
           'source_kind': 'mirror_hypothesis',
           'split_plane_x': round(x_max, 5), 'front_x': round(x_min, 5),
           'visible_depth_m': round(x_max - x_min, 5),
           'note': 'B3-F mirror prior: visible points mirrored about deepest visible x'}
    (out / 'manifest.json').write_text(json.dumps(man, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--observation', required=True)
    ap.add_argument('--parent-world', default=None)
    ap.add_argument('--parent-id', default='parent')
    ap.add_argument('--method', choices=['H5_F', 'B3_F'], required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--pitch', type=float, default=0.004)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    if a.method == 'B3_F' and not a.parent_world:
        a.parent_world = str(pathlib.Path(a.out).parent / 'B3F_parent')
        build_mirror(a.observation, a.parent_world)
    if not a.parent_world:
        raise SystemExit('H5_F 需要 --parent-world')
    man = fuse(a.observation, a.parent_world, a.method, a.parent_id, a.out, a.pitch, a.seed)
    print(json.dumps({k: man[k] for k in ('method', 'parent_id', 'world_sha',
                                          'watertight', 'volume_m3', 'regions',
                                          'no_generated_hidden_contribution', 'seconds')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
