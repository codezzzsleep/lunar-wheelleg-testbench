"""
精确点到三角面距离（纯 numpy，不引入 scipy/rtree）。

  from meshdist import point_to_mesh_distance
  d = point_to_mesh_distance(mesh, points, chunk=256)

实现 Ericson《Real-Time Collision Detection》里的最近点算法，向量化到
(点块 × 三角面) 上计算，返回每个点到网格表面的精确最近距离。
"""
import numpy as np


def _closest_on_triangle(P, A, B, C):
    """
    P: (N,1,3)  A/B/C: (1,M,3) -> (N,M) 距离
    标准分区判定：顶点、边、面内。
    """
    ab = B - A
    ac = C - A
    ap = P - A
    d1 = (ab * ap).sum(-1)
    d2 = (ac * ap).sum(-1)
    bp = P - B
    d3 = (ab * bp).sum(-1)
    d4 = (ac * bp).sum(-1)
    cp = P - C
    d5 = (ab * cp).sum(-1)
    d6 = (ac * cp).sum(-1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    denom = np.where(np.abs(denom) < 1e-20, 1e-20, denom)
    v = vb / denom
    w = vc / denom

    # 面内
    dist = np.sqrt(((P - (A + ab * v[..., None] + ac * w[..., None])) ** 2).sum(-1))
    # 顶点 A 区
    m = (d1 <= 0) & (d2 <= 0)
    if m.any():
        dist = np.where(m, np.sqrt(((P - A) ** 2).sum(-1)), dist)
    # 顶点 B 区
    m = (d3 >= 0) & (d4 <= d3)
    if m.any():
        dist = np.where(m, np.sqrt(((P - B) ** 2).sum(-1)), dist)
    # 顶点 C 区
    m = (d6 >= 0) & (d5 <= d6)
    if m.any():
        dist = np.where(m, np.sqrt(((P - C) ** 2).sum(-1)), dist)
    # 边 AB
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    if m.any():
        t = np.clip(d1 / np.where(np.abs(d1 - d3) < 1e-20, 1e-20, d1 - d3), 0, 1)
        dist = np.where(m, np.sqrt(((P - (A + ab * t[..., None])) ** 2).sum(-1)), dist)
    # 边 AC
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    if m.any():
        t = np.clip(d2 / np.where(np.abs(d2 - d6) < 1e-20, 1e-20, d2 - d6), 0, 1)
        dist = np.where(m, np.sqrt(((P - (A + ac * t[..., None])) ** 2).sum(-1)), dist)
    # 边 BC
    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    if m.any():
        den = (d4 - d3) + (d5 - d6)
        t = np.clip((d4 - d3) / np.where(np.abs(den) < 1e-20, 1e-20, den), 0, 1)
        dist = np.where(m, np.sqrt(((P - (B + (C - B) * t[..., None])) ** 2).sum(-1)), dist)
    return dist


def point_to_mesh_distance(mesh, points, chunk=256, face_chunk=None,
                           max_cells=2_000_000, return_stats=False):
    """返回每个点到网格表面的精确最近距离（米）。

    内存受控：**两级分块**（点块 × 面块），任何时刻只持有 `max_cells` 量级的
    「点 × 面」临时数组；逐面向最小值归约并立即释放。语义与不分块的实现完全一致
    （P95 由完整距离数组计算，不能对各块 P95 求平均）。
    """
    V = np.asarray(mesh.vertices, dtype=np.float64)
    F = np.asarray(mesh.faces)
    M = len(F)
    P = np.asarray(points, dtype=np.float64)
    out = np.empty(len(P))
    # 面块大小：让 点块 × 面块 <= max_cells
    if face_chunk is None:
        face_chunk = max(1, int(max_cells // max(1, chunk)))
        face_chunk = min(face_chunk, M)
    peak_cells = 0
    for i in range(0, len(P), chunk):
        blk = P[i:i + chunk][:, None, :]
        best = np.full(blk.shape[0], np.inf)
        for j in range(0, M, face_chunk):
            A = V[F[j:j + face_chunk, 0]][None, :, :]
            B = V[F[j:j + face_chunk, 1]][None, :, :]
            C = V[F[j:j + face_chunk, 2]][None, :, :]
            d = _closest_on_triangle(blk, A, B, C)
            peak_cells = max(peak_cells, int(d.size))
            best = np.minimum(best, d.min(axis=1))
            del d, A, B, C
        out[i:i + chunk] = best
    if return_stats:
        return out, {'n_points': int(len(P)), 'n_faces': int(M),
                     'chunk': int(chunk), 'face_chunk': int(face_chunk),
                     'max_cells': int(max_cells), 'peak_cells': int(peak_cells),
                     'peak_cells_bytes': int(peak_cells * 8)}
    return out
