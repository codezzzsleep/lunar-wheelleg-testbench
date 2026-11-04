"""G2 方法核对：去重位姿、观测相容条件、真值辅助多起点相似对齐参考、双方向隐藏误差。"""
import json, pathlib, sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_fuse

TASKS = ['4632564', '4632624']


def umeyama_sim(src, dst, max_scale=1.3, min_scale=0.7):
    mu_s = src.mean(0); mu_d = dst.mean(0)
    S = src - mu_s; D = dst - mu_d
    cov = D.T @ S / len(src)
    U, sv, Vt = np.linalg.svd(cov)
    Sfix = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        Sfix[2, 2] = -1
    R = U @ Sfix @ Vt
    var_s = (S ** 2).sum() / len(src)
    s = float(np.trace(np.diag(sv) @ Sfix) / max(var_s, 1e-12))
    s = float(np.clip(s, min_scale, max_scale))
    t = mu_d - s * R @ mu_s
    return s, R, t


def sim_icp(src, dst, init_M, iters=20, rel_min=0.8, rel_max=1.25):
    """相似 ICP：相对于初始位姿的尺度因子被约束在 [rel_min, rel_max]。"""
    M0 = np.array(init_M, float)
    M = M0.copy()
    tree = cKDTree(dst)
    rel = 1.0
    for _ in range(iters):
        X = src @ M[:3, :3].T + M[:3, 3]
        d, idx = tree.query(X, k=1)
        keep = d <= np.percentile(d, 80)          # 粗差修剪
        if keep.sum() < 20:
            break
        s, R, t = umeyama_sim(X[keep], dst[idx[keep]], max_scale=1.5, min_scale=0.5)
        want = float(np.clip(rel * s, rel_min, rel_max))
        s = want / max(rel, 1e-12)
        M[:3, :3] = s * R @ M[:3, :3]
        M[:3, 3] = s * R @ M[:3, 3] + t
        rel = want
        if np.median(d) < 1e-5:
            break
    X = src @ M[:3, :3].T + M[:3, 3]
    d, _ = tree.query(X, k=1)
    return M, float(np.median(d)), rel


def hidden_err(mc, mt, grid, U, pc_idx, pt_idx):
    pc = np.asarray(mc.vertices); pt = np.asarray(mt.vertices)
    pc = pc[in_U(pc, grid, U)]; pt = pt[in_U(pt, grid, U)]
    if len(pc) < 20 or len(pt) < 20:
        return None
    rng = np.random.default_rng(0)
    if len(pc) > 600:
        pc = pc[rng.choice(len(pc), 600, replace=False)]
    if len(pt) > 600:
        pt = pt[rng.choice(len(pt), 600, replace=False)]
    _, d_ct, _ = trimesh.proximity.closest_point(mt, pc)
    _, d_tc, _ = trimesh.proximity.closest_point(mc, pt)
    return {'c2t_median_mm': round(float(np.median(d_ct)) * 1000, 3),
            'c2t_p95_mm': round(float(np.percentile(d_ct, 95)) * 1000, 3),
            't2c_median_mm': round(float(np.median(d_tc)) * 1000, 3),
            't2c_p95_mm': round(float(np.percentile(d_tc, 95)) * 1000, 3),
            'n_candidate_pts': int(len(pc)), 'n_truth_pts': int(len(pt))}


def in_U(pts, grid, U):
    idx = np.floor((np.asarray(pts) - grid['origin']) / grid['pitch']).astype(int)
    ok = ((idx >= 0) & (idx < np.asarray(grid['dims']))).all(axis=1)
    sel = np.zeros(len(idx), bool)
    ii = idx[ok]
    sel[ok] = U[ii[:, 0], ii[:, 1], ii[:, 2]]
    return sel


def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    reg = ROOT / 'runs/v3/stage008/registered'
    zv = np.load(truth / 'fusion/V.npz')
    V = zv['shell']; space = zv['space']; o = np.asarray(zv['origin'], float); p = float(zv['pitch'])
    dims = tuple(int(x) for x in zv['dims'])
    grid = {'origin': o, 'pitch': p, 'dims': np.array(dims),
            'xs': o[0] + (np.arange(dims[0]) + 0.5) * p,
            'ys': o[1] + (np.arange(dims[1]) + 0.5) * p,
            'zs': o[2] + (np.arange(dims[2]) + 0.5) * p}
    U = (space == 0); FREE = (space == 2)
    tm = trimesh.load(str(truth / 'truth/body_world.stl'), force='mesh', process=False)
    tgt = np.asarray(trimesh.sample.sample_surface(tm, 6000, seed=0)[0], float)
    rep = {'schema': 'g2-method-verification/v1', 'candidates': {},
           'compat_rule': {'mask_iou_min': 0.45, 'depth_p95_max_mm': 20.0,
                           'depth_support_min': 0.5, 'known_free_violation_ratio_max': 0.02},
           'note': 'truth-aided similarity ICP is a diagnostic reference, not a global upper bound'}
    for t in TASKS:
        d = reg / f'task_{t}'
        asset = trimesh.load(str(d / 'asset.stl'), force='mesh', process=False)
        align = json.loads((d / 'align.json').read_text())
        seen = set(); poses = []
        for q in align['all']:
            M = np.asarray(q['M'], float)
            key = tuple(np.round(M, 5).ravel())
            if key in seen:
                continue
            seen.add(key)
            diag = q.get('diagnostics') or {}
            m = asset.copy(); m.apply_transform(M)
            Pc, _ = v3_fuse.voxelize_columns(m, grid)
            n_c = int(Pc.sum()); n_free = int((Pc & FREE).sum())
            poses.append({'rank': q.get('rank'), 'M': M.tolist(),
                          'mask_iou': diag.get('mask_iou'), 'depth_p95_mm': diag.get('depth_p95_mm'),
                          'visible_p95_mm': diag.get('visible_p95_mm'),
                          'known_free_violation_ratio': round(float(n_free / max(n_c, 1)), 4),
                          'hidden': hidden_err(m, tm, grid, U, None, None)})
        for q in poses:
            q['compatible'] = bool(
                (q['mask_iou'] or 0) >= 0.45 and (q['depth_p95_mm'] or 9e9) <= 20.0
                and q['known_free_violation_ratio'] <= 0.02 and q['hidden'] is not None)
        # 真值辅助参考：有限多起点（去重后的位姿 + 单位阵），相似变换约束在 [0.7,1.3]
        src = np.asarray(trimesh.sample.sample_surface(asset, 3500, seed=1)[0], float)
        best = None
        # 观测相容位姿为 0 时仍用去重后的全部位姿做有限多起点（明确记录起点集合）
        starts = sorted(poses, key=lambda q: -(q['mask_iou'] or 0))[:4]
        for q in starts + [{'M': np.eye(4).tolist()}]:
            M0 = np.asarray(q['M'], float)
            Mf, med, s = sim_icp(src, tgt, M0)
            if best is None or med < best[0]:
                best = (med, Mf, s, M0)
        med, Mf, s, M0 = best
        m = asset.copy(); m.apply_transform(Mf)
        ref = {'n_starts': len(starts) + 1, 'init_M': M0.tolist(), 'final_M': Mf.tolist(),
               'scale_relative_to_init': round(float(s), 5),
               'abs_scale': round(float(np.cbrt(np.linalg.det(Mf[:3, :3]))), 5),
               'overall_median_mm': round(med * 1000, 3),
               'hidden': hidden_err(m, tm, grid, U, None, None)}
        rep['candidates'][t] = {'n_poses_raw': len(align['all']), 'n_poses_dedup': len(poses),
                                'poses': poses, 'truth_aided_reference': ref}
        print(json.dumps({'task': t, 'raw': len(align['all']), 'dedup': len(poses),
                          'compatible': sum(q['compatible'] for q in poses),
                          'ref_hidden': ref['hidden']}, ensure_ascii=False))
    (ROOT / 'runs/v3/stage010/g2_method_verification.json').write_text(
        json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
