"""月面影子：用深度把"高出地面的石头"和"贴在地面上的影子"分开。

月球没有大气，影子几乎全黑、边缘锐利，低太阳角时拖得很长。只看二维照片，
紧贴石头的影子和背光的石头面分不开；把影子当成石头送进 Lux3D，想象出的石头会被拉长、变形。

机器人有深度相机：影子在地面上（离地高度≈0），石头高出地面。
  height_map        深度 -> 每个像素离地高度（RANSAC 拟合局部地面）
  rock_mask_depth   离地高度 > 阈值、位于车道前方的最大连通块 = 石头（不看亮度，影子天然被排除）
  shadow_mask       贴地且明显变暗的像素 = 影子（只用于展示与实验）
  naive_mask        只看二维亮度的做法：石头 + 与之相连的暗区（模拟"把影子当石头"）
"""
import numpy as np
from scipy import ndimage

import camera_io


def unproject_all(depth, snap, K=None):
    K = K or snap['intrinsics']
    R = np.asarray(snap['R_world_from_camera'], float).reshape(3, 3)
    t = np.asarray(snap['world_pos'], float)
    H, W = depth.shape
    ys, xs = np.mgrid[0:H, 0:W]
    z = depth.astype(np.float64)
    ok = np.isfinite(z) & (z > 0) & (z < 60.0)
    pc = np.stack([(xs - K['cx']) * z / K['fx'], -(ys - K['cy']) * z / K['fy'], -z], -1)
    P = pc @ R.T + t
    P[~ok] = np.nan
    return P, ok


def fit_ground(P, ok, max_range=4.0, iters=300, tol=0.008, seed=0):
    """RANSAC 平面：只用 max_range 内的点。返回 (n, d)，n·p + d = 离地高度（n 朝上）。"""
    rng = np.random.default_rng(seed)
    pts = P[ok]
    cam_dist = np.linalg.norm(pts - np.nanmean(pts, 0), axis=1)
    pts = pts[np.isfinite(cam_dist)]
    near = pts[(pts[:, 0] - np.nanmin(pts[:, 0])) < max_range] if len(pts) else pts
    if len(near) > 60000:
        near = near[rng.choice(len(near), 60000, replace=False)]
    best, best_n = None, -1
    for _ in range(iters):
        a, b, c = near[rng.choice(len(near), 3, replace=False)]
        n = np.cross(b - a, c - a); nn = np.linalg.norm(n)
        if nn < 1e-9:
            continue
        n /= nn
        if n[2] < 0:
            n = -n
        if n[2] < 0.9:                      # 地面应接近水平
            continue
        d = -n @ a
        cnt = int((np.abs(near @ n + d) < tol).sum())
        if cnt > best_n:
            best_n, best = cnt, (n, d)
    n, d = best
    inl = near[np.abs(near @ n + d) < tol]           # 最小二乘精修
    A = np.c_[inl[:, 0], inl[:, 1], np.ones(len(inl))]
    coef, *_ = np.linalg.lstsq(A, inl[:, 2], rcond=None)   # z = ax + by + c
    n = np.array([-coef[0], -coef[1], 1.0]); s = np.linalg.norm(n); n /= s
    return n, -coef[2] / s, {'inliers': int(len(inl)), 'tested': int(len(near))}


def _coords(depth, snap, K, stride=1):
    """低内存：按行列线性组合直接算世界 x、y 与相机深度（float32，不展开整幅点云）。"""
    K = K or snap['intrinsics']
    R = np.asarray(snap['R_world_from_camera'], np.float32).reshape(3, 3)
    t = np.asarray(snap['world_pos'], np.float32)
    H, W = depth.shape
    z = depth[::stride, ::stride].astype(np.float32)
    ok = np.isfinite(z) & (z > 0) & (z < 60.0)
    u = ((np.arange(0, W, stride, dtype=np.float32) - K['cx']) / K['fx'])[None, :]
    v = (-(np.arange(0, H, stride, dtype=np.float32) - K['cy']) / K['fy'])[:, None]
    return R, t, z, ok, u, v


def _world(R, t, z, u, v, row):
    """世界坐标第 row 维：R[row]·(u z, v z, -z) + t[row]。"""
    return (R[row, 0] * u + R[row, 1] * v - R[row, 2]) * z + t[row]


def height_map(depth, snap, K=None, plane=None):
    R, t, z, ok, u, v = _coords(depth, snap, K)
    if plane is None:
        Rs, ts, zs, oks, us, vs = _coords(depth, snap, K, stride=4)
        P = np.stack([_world(Rs, ts, zs, us, vs, i) for i in range(3)], -1)
        P[~oks] = np.nan
        n, d, info = fit_ground(P.astype(np.float64), oks)
    else:
        n, d, info = np.asarray(plane[0], float), float(plane[1]), {'reused_plane': True}
    a = (R.T @ n.astype(np.float32))                       # 离地高度 = n·(R pc + t) + d
    h = (a[0] * u + a[1] * v - a[2]) * z + float(n @ t + d)
    h[~ok] = np.nan
    X = _world(R, t, z, u, v, 0); Y = _world(R, t, z, u, v, 1)
    return h, (X, Y), ok, {'normal': np.asarray(n).tolist(), 'offset': float(d), **info}


def rock_mask_depth(depth, snap, K=None, h_thr=0.015, x_range=(0.3, 3.0), y_half=0.8, y_center=0.0, plane=None):
    """高出地面 h_thr 以上、位于车道前方的最大连通块。不使用任何亮度信息。"""
    h, (X, Y), ok, info = height_map(depth, snap, K, plane)
    cand = ok & (h > h_thr) & (X > x_range[0]) & (X < x_range[1]) & (np.abs(Y - y_center) < y_half)
    lab, n = ndimage.label(cand, structure=np.ones((3, 3)))
    if n == 0:
        return np.zeros_like(cand), h, info
    sizes = ndimage.sum(cand, lab, index=np.arange(1, n + 1))
    m = lab == (1 + int(np.argmax(sizes)))
    # 不做形态学闭运算：闭运算会把轮廓凹处的地面像素并进来，这些像素反投影后落在石头后方的地面上，
    # 会把可见宽度撑大、把配准拉偏（负责人实测：闭运算使真值形状的轮廓 IoU 从 0.99 掉到 0.81）。
    info['n_components'] = int(n)
    info['plane'] = [info['normal'], info['offset']]
    return m, h, info


def luminance(rgb):
    return (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float64)


def shadow_mask(rgb, h, ok=None, h_thr=0.01, dark=0.45):
    """贴地（|h|<h_thr）且亮度低于受光地面中位数 dark 倍的像素。"""
    L = luminance(rgb)
    ok = np.isfinite(h) if ok is None else ok
    ground = ok & (np.abs(h) < h_thr)
    med = float(np.median(L[ground])) if ground.any() else float(np.median(L))
    return ground & (L < dark * med), med


def naive_mask(rgb, rock, ground_median, dark=0.45):
    """只看二维亮度的分割：石头连同与它相连的暗区（影子、暗面）一起当成"物体"。"""
    L = luminance(rgb)
    darkpix = L < dark * ground_median
    seed = rock | darkpix
    lab, n = ndimage.label(seed, structure=np.ones((3, 3)))
    ids = np.unique(lab[rock & (lab > 0)])
    return np.isin(lab, ids[ids > 0])


def mask_iou(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def hi_intrinsics(snap, W, H):
    return camera_io.intrinsics(W, H, float(snap['fovy_deg']))
