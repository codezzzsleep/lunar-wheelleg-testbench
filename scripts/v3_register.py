"""v3 配准：粗初始化 + 观测可见面多尺度鲁棒 ICP，输出唯一放置矩阵。

与旧实现的差别：
  · align24 只作粗初始化；这里自己做 silhouette+depth 的粗搜索（24 朝向 × 多尺度 × 多 yaw），
    再对 top-K 个**不同朝向**分别做精配准，不只精修同一个朝向附近；
  · 精配准用"观测点 ↔ 候选从同一相机可见的表面"的射线对应，点到面/鲁棒 Huber，
    尺度只允许**正等比**，不允许非刚性扭曲，也不允许拿完整真值当配准目标；
  · 输出 M = T_world_from_asset（含尺度），下游评估/导出/融合/碰撞全部只用这一个矩阵。

  python scripts/v3_register.py --candidate model.glb --obs <state>/observation \
      --out <dir> --protocol plans/v3_protocol.json
  python scripts/v3_register.py --known-answer <state> --protocol plans/v3_protocol.json
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import camera_io

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 'v3-register/v1'


def sha256_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_mesh(path):
    m = trimesh.load(path, force='mesh', process=True)
    if isinstance(m, trimesh.Scene):
        m = m.to_geometry()
    if len(m.faces) == 0:
        raise SystemExit(f'候选没有三角面：{path}')
    return m


def rotations24():
    """24 个轴对齐真旋转（与 align24 同一族）。"""
    out = []
    for perm in [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]:
        for sx in (1, -1):
            for sy in (1, -1):
                for sz in (1, -1):
                    R = np.zeros((3, 3))
                    for i, p in enumerate(perm):
                        R[i, p] = 1.0
                    R[0] *= sx
                    R[1] *= sy
                    R[2] *= sz
                    if np.linalg.det(R) > 0.5:
                        out.append(R)
    # 去重
    uniq = []
    for R in out:
        if not any(np.allclose(R, U, atol=1e-8) for U in uniq):
            uniq.append(R)
    return uniq


def load_observation(obs_dir):
    obs_dir = pathlib.Path(obs_dir)
    d = json.loads((obs_dir / 'observation.json').read_text())
    depth = np.load(obs_dir / 'depth.npy').astype(np.float64)
    from PIL import Image
    mask = np.array(Image.open(obs_dir / 'mask.png').convert('L')) > 127
    pts = np.load(obs_dir / 'visible_points.npy')
    return {'json': d, 'depth': depth, 'mask': mask, 'points': np.asarray(pts, float),
            'camera': d['camera'], 'K': d['intrinsics'], 'dir': obs_dir}


def _rim(mask, width=2):
    """掩码边缘带：粗搜索更看重轮廓贴合。"""
    from scipy.ndimage import binary_dilation, binary_erosion
    return binary_dilation(mask, iterations=width) & ~binary_erosion(mask, iterations=width)


def _project(pts, cam):
    u, v, z = camera_io.project(pts, cam)
    return u, v, z


def _rasterize(u, v, z, W, H, radius=1):
    """点云栅格化：返回 (mask, min_depth_map)。"""
    ok = np.isfinite(u) & np.isfinite(v) & (z > 0)
    ui = np.round(u[ok]).astype(np.int64)
    vi = np.round(v[ok]).astype(np.int64)
    inside = (ui >= 0) & (ui < W) & (vi >= 0) & (vi < H)
    ui, vi, zz = ui[inside], vi[inside], z[ok][inside]
    m = np.zeros((H, W), dtype=bool)
    m[vi, ui] = True
    if radius > 0:
        from scipy.ndimage import binary_dilation
        m = binary_dilation(m, iterations=radius)
    d = np.full((H, W), np.inf)
    np.minimum.at(d, (vi, ui), zz)
    return m, d


def _downsample_mask(mask, depth, k=4):
    """低分辨率评分网格：mask 取 any，depth 取 min。"""
    H, W = mask.shape
    H4, W4 = H // k, W // k
    m = mask[:H4 * k, :W4 * k].reshape(H4, k, W4, k).any(axis=(1, 3))
    d = depth[:H4 * k, :W4 * k].reshape(H4, k, W4, k)
    d = np.where(np.isfinite(d), d, np.inf).min(axis=(1, 3))
    return m, d, W4, H4


def coarse_search(mesh, obs, cfg, n_points=4000, top_k=6):
    """24 朝向 × 尺度 × yaw 的低分辨率 silhouette+depth 粗搜索。"""
    rng = np.random.default_rng(0)
    P = np.asarray(trimesh.sample.sample_surface(mesh, int(n_points), seed=0)[0],
                   dtype=np.float64)
    cam = obs['camera']
    K = obs['K']
    W, H = int(K['width']), int(K['height'])
    mask, depth, W4, H4 = _downsample_mask(obs['mask'], obs['depth'], 4)
    vis = obs['points']
    x_front = float(vis[:, 0].min())
    y_center = float((vis[:, 1].min() + vis[:, 1].max()) / 2.0)
    H_vis = float(vis[:, 2].max() - vis[:, 2].min())
    W_vis = float(vis[:, 1].max() - vis[:, 1].min())
    mask_flat = mask.ravel()
    n_mask = max(1, int(mask.sum()))
    yaws = np.deg2rad(np.arange(0, 360, float(cfg.get('coarse_yaw_step_deg', 5.0))))
    out = []
    for ri, R0 in enumerate(rotations24()):
        Q = P @ R0.T
        e = Q.max(0) - Q.min(0)
        if np.any(e < 1e-9):
            continue
        for s0 in {H_vis / e[2], W_vis / e[1]}:
            Qs = Q * s0
            for yaw in yaws:
                c, si = np.cos(yaw), np.sin(yaw)
                Rz = np.array([[c, -si, 0], [si, c, 0], [0, 0, 1]])
                Qy = Qs @ Rz.T
                t = np.array([x_front - Qy[:, 0].min(),
                              y_center - (Qy[:, 1].min() + Qy[:, 1].max()) / 2.0,
                              -Qy[:, 2].min()])
                Qw = Qy + t
                u, v, z = _project(Qw, cam)
                ok = np.isfinite(u) & np.isfinite(v) & (z > 0)
                ui = np.floor(u[ok] / 4.0).astype(np.int64)
                vi = np.floor(v[ok] / 4.0).astype(np.int64)
                inb = (ui >= 0) & (ui < W4) & (vi >= 0) & (vi < H4)
                if inb.sum() < 20:
                    continue
                idx = vi[inb] * W4 + ui[inb]
                zz = z[ok][inb]
                occ = np.zeros(W4 * H4, dtype=bool)
                occ[idx] = True
                inter = int((occ & mask_flat).sum())
                union = int((occ | mask_flat).sum())
                if union == 0:
                    continue
                iou = inter / union
                # 粗搜索只看轮廓 IoU（深度差在 ICP 阶段用射线对应精确优化；
                # 逐像素 min 会退化成 Python 循环，慢两个数量级）
                score = float(iou)
                M = np.eye(4)
                M[:3, :3] = (Rz @ R0) * s0
                M[:3, 3] = t
                out.append({'score': score, 'iou': float(iou), 'depth_err_m': None,
                            'R_index': ri, 'R0': R0, 'yaw_deg': float(np.rad2deg(yaw)),
                            'scale': float(s0), 'M': M})
    out.sort(key=lambda r: -r['score'])
    seen, picked = set(), []
    for r in out:
        if r['R_index'] in seen:
            continue
        seen.add(r['R_index'])
        picked.append(r)
        if len(picked) >= top_k:
            break
    return picked, len(out)


def _rays_from_mask(obs, n_rays, rng):
    mask = obs['mask']
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise SystemExit('观测掩码为空，无法配准')
    sel = rng.choice(len(xs), min(n_rays, len(xs)), replace=False)
    xs, ys = xs[sel], ys[sel]
    K = obs['K']
    depth = obs['depth'][ys, xs]
    ok = np.isfinite(depth) & (depth > 0) & (depth < 100.0)
    xs, ys, depth = xs[ok], ys[ok], depth[ok]
    cam = obs['camera']
    R = np.asarray(cam['R_world_from_camera'], float).reshape(3, 3)
    t = np.asarray(cam['world_pos'], float)
    dirs_cam = np.stack([(xs - K['cx']) / K['fx'],
                         -(ys - K['cy']) / K['fy'],
                         -np.ones_like(xs, dtype=np.float64)], axis=1)
    dirs_cam /= np.linalg.norm(dirs_cam, axis=1, keepdims=True)
    dirs_w = dirs_cam @ R.T
    origins = np.tile(t, (len(xs), 1))
    targets = origins + dirs_w * depth[:, None]
    return origins, dirs_w, targets, xs, ys, depth


def _cast(mesh, origin, direction):
    inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    loc, ray_i, _ = inter.intersects_location(origin, direction, multiple_hits=False)
    return loc, ray_i


def _similarity_from_corr(Q, P, w, *, fix_scale=None, scale_bounds=None):
    """加权 Umeyama：返回 (s, R, t) 使 s R q + t ≈ p。"""
    w = w / max(w.sum(), 1e-12)
    mu_q = (Q * w[:, None]).sum(0)
    mu_p = (P * w[:, None]).sum(0)
    Qc = Q - mu_q
    Pc = P - mu_p
    C = (Qc * w[:, None]).T @ Pc
    U, S, Vt = np.linalg.svd(C)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1] *= -1
        R = Vt.T @ U.T
    if fix_scale is not None:
        s = float(fix_scale)
    else:
        var_q = float((w * (Qc ** 2).sum(1)).sum())
        var_p = float((w * (Pc ** 2).sum(1)).sum())
        s = float(np.sqrt(max(var_p, 1e-18) / max(var_q, 1e-18)))
        if scale_bounds:
            s = float(np.clip(s, scale_bounds[0], scale_bounds[1]))
    t = mu_p - s * R @ mu_q
    return s, R, t


def _unproject_pixels(pix, depth_vals, cam, K):
    W = int(K['width'])
    ui = (pix % W).astype(np.float64)
    vi = (pix // W).astype(np.float64)
    z = np.asarray(depth_vals, dtype=np.float64)
    R = np.asarray(cam['R_world_from_camera'], float).reshape(3, 3)
    t = np.asarray(cam['world_pos'], float)
    pc = np.stack([(ui - K['cx']) * z / K['fx'],
                   -(vi - K['cy']) * z / K['fy'], -z], axis=1)
    return pc @ R.T + t


def refine_icp(mesh, obs, M0, cfg, rng):
    """投影式多尺度鲁棒 ICP：候选可见表面 ↔ 观测点云，尺度只在粗值附近小范围优化。

    为什么不用射线：trimesh 的逐射线求交约 0.3 ms/条，12k 条/次要 3.6 s；
    投影 + 逐像素最近点等价于"从同一相机看到的对应"，全向量化后每步 ~10 ms。
    """
    import trimesh as _tm
    n_samp = int(cfg.get('surface_samples', 24000))
    surf = np.asarray(_tm.sample.sample_surface(mesh, n_samp, seed=0)[0], dtype=np.float64)
    cam = obs['camera']
    K = obs['K']
    W, H = int(K['width']), int(K['height'])
    depth = obs['depth']
    mask = obs['mask']
    ys, xs = np.nonzero(mask)
    pix_mask = (ys.astype(np.int64) * W + xs.astype(np.int64))
    depth_mask = depth[ys, xs]
    ok_pix = np.isfinite(depth_mask) & (depth_mask > 0) & (depth_mask < 100)
    pix_mask, depth_mask = pix_mask[ok_pix], depth_mask[ok_pix]
    pix_mask_sorted = np.sort(pix_mask)
    M = np.array(M0, dtype=np.float64)
    s0 = float(np.cbrt(np.linalg.det(M[:3, :3])))
    hist = []
    levels = list(zip(cfg['scales'], cfg['huber_delta_m'], cfg['iterations']))
    for li, (vox, delta, iters) in enumerate(levels):
        for it in range(int(iters)):
            s_cur = float(np.cbrt(np.linalg.det(M[:3, :3])))
            Qw = surf @ M[:3, :3].T + M[:3, 3]
            u, v, z = _project(Qw, cam)
            good = np.isfinite(u) & np.isfinite(v) & (z > 0)
            ui = np.round(u[good]).astype(np.int64)
            vi = np.round(v[good]).astype(np.int64)
            inb = (ui >= 0) & (ui < W) & (vi >= 0) & (vi < H)
            zi = z[good][inb]
            pix = vi[inb].astype(np.int64) * W + ui[inb].astype(np.int64)
            src = np.nonzero(good)[0][inb]
            if len(pix) < 50:
                break
            # 每个像素只保留最近表面点
            order = np.argsort(zi, kind='stable')
            pix_s = pix[order]
            src_s = src[order]
            uniq, first = np.unique(pix_s, return_index=True)
            sel = src_s[first]
            # 只保留落在观测掩码像素上的对应
            pos = np.searchsorted(pix_mask_sorted, uniq)
            pos = np.clip(pos, 0, len(pix_mask) - 1)
            hit = pix_mask_sorted[pos] == uniq
            uniq, sel = uniq[hit], sel[hit]
            if len(uniq) < 50:
                break
            dep = depth[(uniq // W).astype(np.int64), (uniq % W).astype(np.int64)]
            p_obs = _unproject_pixels(uniq, dep, cam, K)
            q = Qw[sel]
            r = np.linalg.norm(q - p_obs, axis=1)
            w = np.where(r <= delta, 1.0, delta / np.maximum(r, 1e-9))
            keep = r < max(4.0 * delta, 0.04)
            if keep.sum() < 50:
                break
            # 注意：对应点是"当前 world 点 q -> 观测点 p"的**增量**变换，
            # 必须左乘到当前 M 上，不能直接当作 M（旧实现的错误）。
            # 尺度在这里**固定**为粗搜索的估计：部分可见面对相似变换的尺度是病态的，
            # 自由优化会系统性地缩小物体（实测每步都往小走）。尺度另用一次性扫描定。
            # 增量变换是**刚体**（尺度 1）：q 已经在世界尺度上，再乘 s_cur 会把物体放大 s 倍。
            _, R_d, t_d = _similarity_from_corr(q[keep], p_obs[keep], w[keep],
                                                fix_scale=1.0)
            Td = np.eye(4)
            Td[:3, :3] = R_d
            Td[:3, 3] = t_d
            M = Td @ M
            s_total = s_cur
            hist.append({'level': li, 'iter': it, 'n_corr': int(keep.sum()),
                         'median_mm': round(float(np.median(r[keep])) * 1000, 3),
                         'p95_mm': round(float(np.percentile(r[keep], 95)) * 1000, 3),
                         'scale': round(s_total, 6)})
    return M, hist


def _depth_residual(mesh, obs, M, samples=20000):
    """候选表面投影后的逐像素最近深度与观测深度的中位绝对差（米）。"""
    import trimesh as _tm
    P = np.asarray(_tm.sample.sample_surface(mesh, samples, seed=1)[0], float)
    Q = P @ M[:3, :3].T + M[:3, 3]
    u, v, z = _project(Q, obs['camera'])
    K = obs['K']
    W, H = int(K['width']), int(K['height'])
    good = np.isfinite(u) & np.isfinite(v) & (z > 0)
    ui = np.round(u[good]).astype(np.int64)
    vi = np.round(v[good]).astype(np.int64)
    inb = (ui >= 0) & (ui < W) & (vi >= 0) & (vi < H)
    if inb.sum() < 50:
        return 1.0
    pix = vi[inb] * W + ui[inb]
    zz = z[good][inb]
    order = np.argsort(zz, kind='stable')
    pix, zz = pix[order], zz[order]
    uniq, first = np.unique(pix, return_index=True)
    zmin = zz[first]
    obs_d = obs['depth'][(uniq // W), (uniq % W)]
    ok = np.isfinite(obs_d) & (obs_d > 0) & (obs_d < 100)
    if ok.sum() < 50:
        return 1.0
    return float(np.median(np.abs(zmin[ok] - obs_d[ok])))


def local_polish(mesh, obs, M, cfg):
    """在 ICP 之后做一次局部坐标下降（dx,dy,dz,dyaw），目标=可见点云到候选表面的中位距离。

    这一步直接优化"观测可见面 ↔ 候选可见面"的贴合度，修正 15° 粗网格留下的残差；
    只用观测点云，不读真值，也不改尺度。
    """
    import trimesh as _tm
    from scipy.spatial import cKDTree
    surf = np.asarray(_tm.sample.sample_surface(mesh, int(cfg.get('polish_samples', 20000)),
                                                seed=0)[0], float)
    tree = cKDTree(np.asarray(obs['points'], float))
    mask4, _, W4, H4 = _downsample_mask(obs['mask'], obs['depth'], 4)
    flat = mask4.ravel()

    def score(Mx):
        Q = surf @ Mx[:3, :3].T + Mx[:3, 3]
        d, _ = tree.query(Q)
        med = float(np.median(d))
        # 轮廓项：单视角下光滑正面存在"沿面滑动"的歧义，靠轮廓把横向自由度和深度项一起约束
        u, v, z = _project(Q, obs['camera'])
        ok = np.isfinite(u) & np.isfinite(v) & (z > 0)
        ui = np.floor(u[ok] / 4.0).astype(np.int64)
        vi = np.floor(v[ok] / 4.0).astype(np.int64)
        inb = (ui >= 0) & (ui < W4) & (vi >= 0) & (vi < H4)
        occ = np.zeros(W4 * H4, dtype=bool)
        if inb.any():
            occ[vi[inb] * W4 + ui[inb]] = True
        inter = int((occ & flat).sum()); union = int((occ | flat).sum())
        iou = inter / max(1, union)
        return med * 1000.0 + 30.0 * (1.0 - iou)

    def score_mm(Mx):
        Q = surf @ Mx[:3, :3].T + Mx[:3, 3]
        d, _ = tree.query(Q)
        return float(np.median(d)) * 1000.0

    bb = np.asarray(mesh.bounds.mean(0), float)
    best_M = M.copy()
    best = score(best_M)
    steps = {'dx': 0.004, 'dy': 0.004, 'dz': 0.003,
             'dyaw': float(np.deg2rad(cfg.get('polish_yaw_step_deg', 2.0)))}
    for _ in range(int(cfg.get('polish_rounds', 3))):
        improved = False
        for key, st in steps.items():
            for f in (-1.0, -0.5, 0.5, 1.0):
                c = best_M.copy()
                if key == 'dyaw':
                    ang = st * f
                    Rz = np.array([[np.cos(ang), -np.sin(ang), 0],
                                   [np.sin(ang), np.cos(ang), 0], [0, 0, 1]])
                    cw = bb @ best_M[:3, :3].T + best_M[:3, 3]
                    c[:3, :3] = Rz @ best_M[:3, :3]
                    c[:3, 3] = cw - Rz @ best_M[:3, :3] @ bb
                else:
                    d = np.zeros(3)
                    d['xyz'.index(key[1])] = st * f
                    c[:3, 3] = best_M[:3, 3] + d
                sc = score(c)
                if sc < best - 1e-6:
                    best, best_M, improved = sc, c, True
        if not improved:
            break
    return best_M, {'score': round(best, 3),
                    'visible_median_mm': round(score_mm(best_M), 3),
                    'steps': {k: float(v) for k, v in steps.items()}}


def scan_scale(mesh, obs, M, cfg, span=0.10, steps=9):
    """一次性等比尺度扫描：在 ±span 内按深度残差选最优（避免把尺度混进 ICP）。"""
    s0 = float(np.cbrt(np.linalg.det(M[:3, :3])))
    c = M[:3, 3] + M[:3, :3] @ np.zeros(3)
    best, rows = None, []
    for k in range(steps):
        f = 1.0 - span + 2.0 * span * k / max(1, steps - 1)
        cand = M.copy()
        cand[:3, :3] = M[:3, :3] * f
        # 以物体包围盒中心缩放，避免整体平移
        bb = np.asarray(mesh.bounds.mean(0), float)
        cw = bb @ M[:3, :3].T + M[:3, 3]
        cand[:3, 3] = cw - (M[:3, :3] * f) @ bb
        r = _depth_residual(mesh, obs, cand, cfg.get('scale_scan_samples', 16000))
        rows.append({'factor': round(f, 4), 'depth_median_m': round(r, 6)})
        if best is None or r < best[0]:
            best = (r, cand, f)
    return best[1], {'span': span, 'steps': steps, 'best_factor': round(best[2], 4),
                     'best_depth_median_m': round(best[0], 6), 'rows': rows}


def evaluate_matrix(mesh, obs, M):
    """投影评估：掩码 IoU、深度 P95、可见点 P95。"""
    V = np.asarray(trimesh.sample.sample_surface(mesh, 30000, seed=0)[0], dtype=np.float64)
    Q = V @ M[:3, :3].T + M[:3, 3]
    u, v, z = _project(Q, obs['camera'])
    m, dm = _rasterize(u, v, z, obs['mask'].shape[1], obs['mask'].shape[0], radius=1)
    mask = obs['mask']
    iou = float((m & mask).sum()) / max(1, int((m | mask).sum()))
    depth = obs['depth']
    both = m & mask & np.isfinite(dm) & np.isfinite(depth)
    if both.sum() > 20:
        dd = np.abs(dm[both] - depth[both]) * 1000
        depth_p95 = float(np.percentile(dd, 95))
        depth_med = float(np.median(dd))
    else:
        depth_p95 = depth_med = float('nan')
    # 可见点 -> 候选表面距离（近似：最近顶点）
    vis = obs['points']
    if len(vis) > 0 and len(Q) > 0:
        from scipy.spatial import cKDTree
        tree = cKDTree(Q[::max(1, len(Q) // 20000)])
        d, _ = tree.query(vis)
        d = d * 1000
        vis_p95 = float(np.percentile(d, 95))
        vis_med = float(np.median(d))
    else:
        vis_p95 = vis_med = float('nan')
    return {'mask_iou': round(iou, 4), 'depth_median_mm': round(depth_med, 3),
            'depth_p95_mm': round(depth_p95, 3),
            'visible_median_mm': round(vis_med, 3),
            'visible_p95_mm': round(vis_p95, 3),
            'n_candidate_pixels': int(m.sum()), 'n_mask_pixels': int(mask.sum())}


def register(candidate_path, obs_dir, proto, out_dir, *, coarse=None, top_k=None):
    cfg = proto['registration']
    obs = load_observation(obs_dir)
    mesh = load_mesh(candidate_path)
    rng = np.random.default_rng(0)
    if coarse is None:
        picked, n_eval = coarse_search(mesh, obs, cfg, top_k=int(top_k or 8))
    else:
        picked = [{'M': np.asarray(coarse, float), 'R_index': -1, 'score': None,
                   'iou': None, 'rim_hit': None, 'depth_err_m': None,
                   'yaw_deg': None, 'scale': None}]
        n_eval = 0
    results = []
    for j, pose in enumerate(picked):
        M, hist = refine_icp(mesh, obs, pose['M'], cfg, rng)
        M, polish = local_polish(mesh, obs, M, cfg)
        scan = polish
        ev = evaluate_matrix(mesh, obs, M)
        results.append({'rank': j, 'coarse': {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                                   for k, v in pose.items() if k not in ('M', 'R0')},
                        'M': M.tolist(), 'diagnostics': ev, 'icp_history': hist[-6:],
                        'scale_scan': scan,
                        'n_icp_steps': len(hist)})
    results.sort(key=lambda r: (-r['diagnostics']['mask_iou'],
                                r['diagnostics']['visible_median_mm']))
    best = results[0]
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rec = {'schema': 'v3-registration/v1', 'version': VERSION,
           'candidate': str(candidate_path), 'candidate_sha256': sha256_file(candidate_path),
           'observation': str(obs_dir),
           'observation_sha256': sha256_file(pathlib.Path(obs_dir) / 'observation.json'),
           'n_coarse_evaluated': int(n_eval), 'n_refined': len(results),
           'distinct_orientations': len({r['coarse']['R_index'] for r in results}),
           'best': best, 'all': results,
           'M': best['M'], 'diagnostics': best['diagnostics'],
           'note': 'M = T_world_from_asset（含尺度）；只允许刚体 + 正等比尺度；'
                   '下游唯一放置，不再二次贴地/缩放'}
    (out / 'align.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


# ---------------------------------------------------------------- known answer
def known_answer(state_dir, proto, out_dir=None, *, rot_deg=(0, 0, 6), scale=0.37,
                 trans=(0.01, -0.008, 0.0), seed=0):
    """已知答案：把真实扫描件放进**任意局部坐标系**（非 1 的尺度 + 任意朝向），
    用状态自己的真实观测，走同一生产链恢复世界位姿。

    候选局部系 = 资产系 × 0.37（并加一点旋转），已知变换 = 1/scale 的相似变换；
    配准只看观测，不看真值。恢复误差在候选表面点上比较 T_known 与 T_recovered。
    """
    import v3_fuse
    state_dir = pathlib.Path(state_dir)
    st = json.loads((state_dir / 'state.json').read_text())
    man = json.loads((state_dir / 'truth' / 'manifest.json').read_text())
    # 资产网格（资产系）：由 scene_spec 里记录的 meta 路径定位
    spec_st = json.loads((state_dir / 'scene_spec.json').read_text())
    meta_p = ROOT / spec_st['v3']['asset_meta']
    meta = json.loads(meta_p.read_text())
    body = ROOT / meta['body_stl']
    mesh_asset = trimesh.load(body, force='mesh', process=False)
    # 候选局部系：缩放 0.37 + 绕 z 转 -11°，模拟生成网格的任意尺度/朝向
    S = float(scale)
    Rloc = np.array([[np.cos(np.deg2rad(-11.0)), -np.sin(np.deg2rad(-11.0)), 0],
                     [np.sin(np.deg2rad(-11.0)), np.cos(np.deg2rad(-11.0)), 0],
                     [0, 0, 1]])
    cand = mesh_asset.copy()
    cand.apply_transform(np.block([[Rloc * S, np.zeros((3, 1))], [0, 0, 0, 1]]))
    out = pathlib.Path(out_dir or (state_dir / 'registration' / 'known_answer'))
    out.mkdir(parents=True, exist_ok=True)
    cand.export(out / 'candidate.stl')
    # 已知世界变换：资产 -> 世界（与 env 放置一致）
    yaw = np.deg2rad(float(man['placement']['yaw_deg']))
    Rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    # T_asset = Rz + translate，使世界网格与 truth/body_world.stl 一致
    tw = trimesh.load(state_dir / 'truth' / 'body_world.stl', force='mesh', process=False)
    c_asset = np.asarray(mesh_asset.bounds.mean(0), float)
    P_asset = np.asarray(mesh_asset.vertices, float)
    P_world_expected = P_asset @ Rz.T + np.array([man['placement']['x'], man['placement']['y'], 0.0])
    t_asset = np.array([man['placement']['x'], man['placement']['y'], 0.0])
    t_asset[2] = float(tw.bounds[0][2] - (P_asset @ Rz.T)[:, 2].min())
    # 资产 -> 世界 = 局部系(×S,Rloc) 之后的相似变换
    M_known = np.eye(4)
    M_known[:3, :3] = Rz @ Rloc.T / S
    M_known[:3, 3] = t_asset - M_known[:3, :3] @ np.zeros(3)
    # 校验：已知变换把候选映射到世界真值网格
    err = np.abs((np.asarray(cand.vertices) @ M_known[:3, :3].T + M_known[:3, 3])
                 - (P_asset @ Rz.T + t_asset)).max()
    obs_dir = state_dir / 'observation'
    rec = register(out / 'candidate.stl', obs_dir, proto, out)
    M_rec = np.asarray(rec['M'], float)
    # 恢复误差（候选表面点）
    sp = np.asarray(trimesh.sample.sample_surface(cand, 4000, seed=seed)[0], float)
    p_known = sp @ M_known[:3, :3].T + M_known[:3, 3]
    p_rec = sp @ M_rec[:3, :3].T + M_rec[:3, 3]
    d = np.linalg.norm(p_known - p_rec, axis=1) * 1000
    s_known = float(np.cbrt(np.linalg.det(M_known[:3, :3])))
    s_rec = float(np.cbrt(np.linalg.det(M_rec[:3, :3])))
    Rk = M_known[:3, :3] / s_known
    Rr = M_rec[:3, :3] / s_rec
    cosang = float(np.clip((np.trace(Rk.T @ Rr) - 1.0) / 2.0, -1, 1))
    rot_err = float(np.rad2deg(np.arccos(cosang)))
    # 再测一个扰动初值下的精配准能力
    c_world = np.asarray(cand.bounds.mean(0), float) @ M_known[:3, :3].T + M_known[:3, 3]
    ang = np.deg2rad(6.0)
    Rb = np.array([[np.cos(ang), -np.sin(ang), 0], [np.sin(ang), np.cos(ang), 0], [0, 0, 1]])
    M0 = M_known.copy()
    M0[:3, :3] = Rb @ M_known[:3, :3]
    M0[:3, 3] = c_world - Rb @ c_world + M_known[:3, 3] + np.array([0.008, -0.006, 0.0])
    mesh_c = load_mesh(out / 'candidate.stl')
    obs_c = load_observation(obs_dir)
    M_ref, hist_ref = refine_icp(mesh_c, obs_c, M0, proto['registration'],
                                 np.random.default_rng(0))
    ev_ref = evaluate_matrix(mesh_c, obs_c, M_ref)
    p_ref = sp @ M_ref[:3, :3].T + M_ref[:3, 3]
    d_ref = np.linalg.norm(p_known - p_ref, axis=1) * 1000
    ka = {'schema': 'v3-known-answer/v1', 'state_id': st['state_id'],
          'candidate_local_frame': {'scale_from_asset': S, 'yaw_deg': -11.0},
          'known_transform': {'scale': round(s_known, 6),
                              'M': M_known.tolist()},
          'candidate_to_world_check_max_mm': round(float(err) * 1000, 6),
          'recovered_scale': round(s_rec, 6), 'known_scale': round(s_known, 6),
          'scale_error_pct': round(100.0 * abs(s_rec - s_known) / s_known, 4),
          'rotation_error_deg': round(rot_err, 4),
          'surface_error_mm': {'median': round(float(np.median(d)), 3),
                               'p95': round(float(np.percentile(d, 95)), 3),
                               'max': round(float(d.max()), 3)},
          'visible_diagnostics': rec['diagnostics'],
          'perturbed_init': {'yaw_deg': 6.0, 'translation_m': [8e-3, -6e-3, 0.0],
                             'surface_p95_mm': round(float(np.percentile(d_ref, 95)), 3),
                             'diagnostics_after_icp': ev_ref},
          'n_refined': rec['n_refined'],
          'pass': bool(np.percentile(d, 95) <= float(proto['registration'].get(
              'known_answer_p95_mm', 8.0)) and rot_err <= 3.0
              and abs(s_rec - s_known) / s_known <= 0.02)}
    (out / 'known_answer.json').write_text(json.dumps(ka, ensure_ascii=False, indent=2))
    return ka


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--candidate')
    ap.add_argument('--obs')
    ap.add_argument('--out', required=True)
    ap.add_argument('--known-answer', default=None)
    ap.add_argument('--top-k', type=int, default=8)
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    if a.known_answer:
        rec = known_answer(ROOT / a.known_answer, proto, ROOT / a.out)
        print(json.dumps(rec, ensure_ascii=False))
        return
    rec = register(a.candidate, a.obs, proto, ROOT / a.out, top_k=a.top_k)
    print(json.dumps({'best': rec['best']['diagnostics'],
                      'M': rec['M'], 'n_refined': rec['n_refined']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
