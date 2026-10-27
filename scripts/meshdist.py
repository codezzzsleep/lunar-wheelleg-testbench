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


def point_to_mesh_distance(mesh, points, chunk=256):
    """返回每个点到网格表面的精确最近距离（米）。"""
    V = np.asarray(mesh.vertices, dtype=np.float64)
    F = np.asarray(mesh.faces)
    A = V[F[:, 0]][None, :, :]
    B = V[F[:, 1]][None, :, :]
    C = V[F[:, 2]][None, :, :]
    P = np.asarray(points, dtype=np.float64)
    out = np.empty(len(P))
    for i in range(0, len(P), chunk):
        blk = P[i:i + chunk][:, None, :]
        out[i:i + chunk] = _closest_on_triangle(blk, A, B, C).min(axis=1)
    return out
