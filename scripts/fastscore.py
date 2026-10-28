"""
快速位姿打分：纯 numpy，在小样本上直接算成对距离（无字典/KD 树依赖）。

用于 24 朝向搜索阶段；最终验收仍由 align.render_eval 在原生分辨率给官方指标。
"""
import numpy as np

N_OBS = 700          # 搜索用的观测点数
N_CAND = 1500        # 搜索用的候选表面点数
TOL = 0.02           # 20 mm 视为"覆盖"


def sample_surface(mesh, n=N_CAND, seed=0):
    v = np.asarray(mesh.vertices); f = np.asarray(mesh.faces)
    if len(f) == 0:
        return v[:n]
    tri = v[f]
    a = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
    if a.sum() <= 0:
        return v[:n]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(f), size=n, p=a / a.sum())
    u = rng.random((n, 2))
    m = u.sum(1) > 1
    u[m] = 1 - u[m]
    t = tri[idx]
    return (t[:, 0] + u[:, :1] * (t[:, 1] - t[:, 0])
            + u[:, 1:2] * (t[:, 2] - t[:, 0]))


def prep_obs(obs_pts, n=N_OBS, seed=0):
    if len(obs_pts) > n:
        obs_pts = obs_pts[np.random.default_rng(seed).choice(len(obs_pts), n, replace=False)]
    return np.ascontiguousarray(obs_pts)


def score(cand_pts, obs_pts):
    """
    返回 (obs->cand 中位距离 mm, 双向覆盖)。
    距离越小越好；覆盖越大越好。
    """
    q = np.asarray(cand_pts, dtype=np.float64)
    o = np.asarray(obs_pts, dtype=np.float64)
    d2 = ((o[:, None, :] - q[None, :, :]) ** 2).sum(-1)     # (N_OBS, N_CAND)
    d = np.sqrt(d2)
    med = float(np.median(d.min(1))) * 1000.0
    c1 = float(np.mean(d.min(1) < TOL))
    c2 = float(np.mean(d.min(0) < TOL))
    return med, min(c1, c2)
