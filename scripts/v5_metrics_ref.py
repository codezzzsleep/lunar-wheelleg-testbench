"""SPEC_CORE_V5 §2.1–2.2 参考实现：2.5D 列填实 + 只在未知区内比较的隐藏指标。

网格 g 与现有 v4_admission.grid_from_V 相同：
    g = {'xs','ys','zs': 体素中心坐标, 'dims': (nx,ny,nz)}
候选、真值、扰动先验都必须用 column_fill_top，禁止再用奇偶配对填实候选。

自测（任意一份 GLB）：
    python3 -I v5_metrics_ref.py model.glb
预期：self 误差全为 0；背面截掉 10 cm 后 rear_err_m = -0.1。
"""
import numpy as np
import trimesh


def drop_small_fragments(mesh, min_face_frac=0.02):
    """丢掉面数少于总数 min_face_frac 的孤立碎片（Lux3D 常带漂浮小块）。"""
    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return mesh
    n = len(mesh.faces)
    keep = [p for p in parts if len(p.faces) >= min_face_frac * n]
    return trimesh.util.concatenate(keep) if keep else mesh


def column_fill_top(mesh, g, z_floor=0.0, z_ray=-1.0):
    """每列从地面 z_floor 填到该列最高交点。

    不做奇偶配对，不要求水密；开口外壳、重复壳、多碎片都得到同一个实心。
    对轮式机器人的通行判断，悬空部分按实心处理是保守的。
    """
    dims = tuple(int(x) for x in g['dims'])
    X, Y = np.meshgrid(np.asarray(g['xs']), np.asarray(g['ys']), indexing='ij')
    o = np.stack([X.ravel(), Y.ravel(), np.full(X.size, z_ray)], 1)
    d = np.tile([0.0, 0.0, 1.0], (len(o), 1))
    loc, ri, _ = trimesh.ray.ray_triangle.RayMeshIntersector(mesh).intersects_location(
        o, d, multiple_hits=True)
    top = np.full(X.size, -np.inf)
    if len(ri):
        np.maximum.at(top, ri, loc[:, 2])
    top = top.reshape(dims[:2])
    zc = np.asarray(g['zs'])
    return (zc[None, None, :] >= z_floor) & (zc[None, None, :] <= top[:, :, None])


def hidden_metrics(P, T, U, g, path_half_width=0.20, z_min=0.02):
    """H_c = P∩U，H_t = T∩U，只在未知区内比较。绝不在 V∪P 上量。

    P、T 都必须是 column_fill_top 的结果；U 为该场景自己的未知区（space==0）。
    """
    zs, xs, ys = (np.asarray(g[k]) for k in ('zs', 'xs', 'ys'))
    above = zs[None, None, :] > z_min
    Hc, Ht = P & U & above, T & U & above

    def rear(H):
        a = H.any(axis=(1, 2))
        return float(xs[a].max()) if a.any() else None

    def top(H):
        a = H.any(axis=(0, 1))
        return float(zs[a].max()) if a.any() else None

    def hmap(H):
        has = H.any(2)
        idx = H.shape[2] - 1 - np.argmax(H[:, :, ::-1], axis=2)
        return np.where(has, zs[idx], 0.0)

    lane = np.abs(ys) <= path_half_width
    hidden_cols = U.any(2)[:, lane]
    e = (hmap(Hc) - hmap(Ht))[:, lane][hidden_cols]
    r = {'rear_c': rear(Hc), 'rear_t': rear(Ht), 'top_c': top(Hc), 'top_t': top(Ht),
         'vox_c': int(Hc.sum()), 'vox_t': int(Ht.sum()),
         'path_mae_mm': float(np.abs(e).mean() * 1000) if e.size else None,
         'path_p95_mm': float(np.percentile(np.abs(e), 95) * 1000) if e.size else None}
    r['rear_err_m'] = None if None in (r['rear_c'], r['rear_t']) else round(r['rear_c'] - r['rear_t'], 4)
    r['top_err_m'] = None if None in (r['top_c'], r['top_t']) else round(r['top_c'] - r['top_t'], 4)
    return r


def free_intrusion(P, space, g, z_min=0.02):
    """侵入比 = P 落进已知空地（space==2）的体素 ÷ P 的实心体素；另报侵入深度 P95（mm）。"""
    zs = np.asarray(g['zs'])
    above = zs[None, None, :] > z_min
    Pa = P & above
    bad = Pa & (space == 2)
    n = int(Pa.sum())
    out = {'voxels': n, 'free_voxels': int(bad.sum()),
           'free_intrusion_frac': round(int(bad.sum()) / max(n, 1), 5), 'intrusion_depth_p95_mm': 0.0}
    if bad.any():
        from scipy import ndimage
        pitch = float(np.median(np.diff(zs)))
        # 侵入深度：侵入体素到最近"非空地"体素的距离
        dist = ndimage.distance_transform_edt(space == 2) * pitch
        out['intrusion_depth_p95_mm'] = round(float(np.percentile(dist[bad], 95) * 1000), 2)
    return out


if __name__ == '__main__':
    import sys
    sc = trimesh.load(sys.argv[1], force='scene')
    m = trimesh.util.concatenate(list(sc.dump()))
    m = drop_small_fragments(m)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))  # glTF Y-up -> Z-up
    m.apply_scale(0.30 / m.extents[2])
    m.apply_translation([0, 0, -m.bounds[0][2]])
    p = 0.004
    lo, hi = m.bounds
    g = {'xs': np.arange(lo[0], hi[0] + 0.2, p) + p / 2, 'ys': np.arange(lo[1], hi[1], p) + p / 2,
         'zs': np.arange(-0.05, hi[2] + p, p) + p / 2}
    g['dims'] = (len(g['xs']), len(g['ys']), len(g['zs']))
    P = column_fill_top(m, g)
    U = np.ones_like(P)
    U[g['xs'] < np.median(g['xs'][P.any((1, 2))]), :, :] = False  # 假设前半可见
    print('self   :', hidden_metrics(P, P, U, g))
    cut = m.slice_plane([hi[0] - 0.10, 0, 0], [-1, 0, 0], cap=False)
    print('cut10cm:', hidden_metrics(column_fill_top(cut, g), P, U, g))
