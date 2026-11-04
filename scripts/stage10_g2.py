"""G2：真值辅助理想对齐 vs 仅观测对齐；隐藏区误差与观测歧义。"""
import json, pathlib, sys
import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_fuse

TASKS = ['4632564','4632603','4632618','4632621','4632624','4632627']


def in_U(pts, grid, U):
    idx = np.floor((np.asarray(pts) - grid['origin']) / grid['pitch']).astype(int)
    ok = ((idx >= 0) & (idx < np.asarray(grid['dims']))).all(axis=1)
    sel = np.zeros(len(idx), bool)
    ii = idx[ok]
    sel[ok] = U[ii[:, 0], ii[:, 1], ii[:, 2]]
    return sel


def hidden_surface(mc, mt, grid, U):
    """隐藏区表面误差（候选/真值都是网格表面，避免壳-实体体素 IoU 的偏差）。"""
    pc = np.asarray(mc.vertices); pt = np.asarray(mt.vertices)
    pc = pc[in_U(pc, grid, U)]; pt = pt[in_U(pt, grid, U)]
    if len(pc) < 20 or len(pt) < 20:
        return None
    rng = np.random.default_rng(0)
    if len(pc) > 700:
        pc = pc[rng.choice(len(pc), 700, replace=False)]
    if len(pt) > 700:
        pt = pt[rng.choice(len(pt), 700, replace=False)]
    _, d_ct, _ = trimesh.proximity.closest_point(mt, pc)
    _, d_tc, _ = trimesh.proximity.closest_point(mc, pt)
    return {'n_candidate_pts': int(len(pc)), 'n_truth_pts': int(len(pt)),
            'c2t_median_mm': round(float(np.median(d_ct)) * 1000, 3),
            'c2t_p95_mm': round(float(np.percentile(d_ct, 95)) * 1000, 3),
            't2c_median_mm': round(float(np.median(d_tc)) * 1000, 3),
            't2c_p95_mm': round(float(np.percentile(d_tc, 95)) * 1000, 3)}


def hidden_iou(Pc, Pt, U):
    a = Pc & U; b = Pt & U
    inter = int((a & b).sum()); uni = int((a | b).sum())
    return (inter / uni if uni else None), int(a.sum()), int(b.sum())


def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    reg = ROOT / 'runs/v3/stage008/registered'
    zv = np.load(truth / 'fusion/V.npz')
    V = zv['shell']; space = zv['space']; vo = np.asarray(zv['origin'], float); vp = float(zv['pitch'])
    dims = tuple(int(x) for x in zv['dims'])
    grid = {'origin': vo, 'pitch': vp, 'dims': np.array(dims)}
    grid['xs'] = vo[0] + (np.arange(dims[0]) + 0.5) * vp
    grid['ys'] = vo[1] + (np.arange(dims[1]) + 0.5) * vp
    grid['zs'] = vo[2] + (np.arange(dims[2]) + 0.5) * vp
    U = (space == 0)
    tm = trimesh.load(str(truth / 'truth/body_world.stl'), force='mesh', process=False)
    Pt, _ = v3_fuse.voxelize_columns(tm, grid)
    res = {'schema': 'g2-alignment/v1', 'candidates': {},
           'note': 'truth-aided ICP is diagnostic only and never enters decisions'}
    for t in TASKS:
        d = reg / f'task_{t}'
        asset = trimesh.load(str(d / 'asset.stl'), force='mesh', process=False)
        align = json.loads((d / 'align.json').read_text())
        poses = []
        for p in align['all']:
            M = np.asarray(p['M'], float)
            m = asset.copy(); m.apply_transform(M)
            Pc, _ = v3_fuse.voxelize_columns(m, grid)
            iou, na, nb = hidden_iou(Pc, Pt, U)
            surf = hidden_surface(m, tm, grid, U)
            diag = p.get('diagnostics') or {}
            poses.append({'rank': p.get('rank'), 'M': M.tolist(),
                          'mask_iou': diag.get('mask_iou'), 'depth_p95_mm': diag.get('depth_p95_mm'),
                          'hidden_surface': surf,
                          'hidden_iou_shell_vs_solid': round(iou, 4) if iou is not None else None})
        # 诊断用真值辅助 ICP：仅用于测量“理想对齐”的隐藏区误差
        best = np.asarray(align['M'], float)
        mt = asset.copy(); mt.apply_transform(best)
        try:
            T, transformed_pts, cost = trimesh.registration.icp(
                np.asarray(mt.vertices), np.asarray(tm.vertices),
                max_iterations=30, threshold=1e-4)
            transformed = mt.copy(); transformed.apply_transform(T)
            Pi, _ = v3_fuse.voxelize_columns(transformed, grid)
            iou_i, nai, nbi = hidden_iou(Pi, Pt, U)
            ideal = {'icp_cost': float(cost), 'hidden_surface': hidden_surface(transformed, tm, grid, U),
                     'hidden_iou_shell_vs_solid': round(iou_i, 4) if iou_i is not None else None}
        except Exception as e:  # noqa: BLE001
            ideal = {'error': f'{type(e).__name__}: {e}'}
        good = [p for p in poses if p['mask_iou'] is not None and p['mask_iou'] >= 0.45]
        vals = [p['hidden_surface']['c2t_median_mm'] for p in good
                if p.get('hidden_surface')]
        amb = {'n_observation_plausible': len(good),
               'c2t_median_mm_min': min(vals) if vals else None,
               'c2t_median_mm_max': max(vals) if vals else None,
               'c2t_median_spread_mm': (max(vals) - min(vals)) if len(vals) > 1 else None,
               'ambiguous': bool(len(vals) > 1 and (max(vals) - min(vals)) > 5.0)}
        res['candidates'][t] = {'observation_poses': poses, 'ideal_truth_aided': ideal,
                                'ambiguity': amb}
        print(json.dumps({'task': t, 'c2t_best_mm': min(vals) if vals else None,
                          'c2t_worst_mm': max(vals) if vals else None,
                          'ideal': (ideal.get('hidden_surface') or {}).get('c2t_median_mm'),
                          'n_plausible': len(good), 'ambiguous': amb['ambiguous']}, ensure_ascii=False))
    (ROOT / 'runs/v3/stage010/g2_result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
