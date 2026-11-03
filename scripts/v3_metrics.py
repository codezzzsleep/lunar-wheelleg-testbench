"""v3 隐藏区误差：占据 / 沿路径顶面 / 背面结构（同一栅格、同一 ROI、同一采样）。

固定评估域（冻结在协议里）：
  ROI = U（未知）∩ 通行走廊（|y-y_center| ≤ corridor_half）∩ x∈[x_front, x_front+back_window]
        ∩ z ≥ 0
地面与可见区不计入隐藏误差；FULL / OBS_ONLY / 真值用同一 world grid 与同一采样。

三类量：
  A 隐藏占据：漏填率、过填率、IoU、真值隐藏体素数、评估域大小；
  B 沿路径顶面：按 2 mm 纵向采样与机器人通行宽度带取顶面高度，报 MAE/P95/高估/低估；
  C 背面结构：后缘位置/前后长度误差，后坡落差与下降位置误差；未形成可测后缘时写 missing。

OBS_ONLY 没有物体的格在物理规划中等同可通行地面：顶面计分按公共地面高（z=0）处理，
并另报"无隐藏表面"比例。

  python scripts/v3_metrics.py --state runs/v3/states/<sid>
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import v3_fuse

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_occ(p):
    d = np.load(p)
    return np.asarray(d['occupied'], dtype=bool), {
        'origin': np.asarray(d['origin'], float), 'pitch': float(d['pitch']),
        'dims': np.asarray(d['dims'], int)}


def _roi(art, proto, vis):
    grid = art['grid']
    U = (art['space'] == 0)
    pitch = grid['pitch']
    xs = grid['origin'][0] + (np.arange(grid['dims'][0]) + 0.5) * pitch
    ys = grid['origin'][1] + (np.arange(grid['dims'][1]) + 0.5) * pitch
    ch = float(proto['hidden_error']['corridor_half_width_m'])
    y_c = float(vis['y_center'])
    x0 = float(vis['x_front']) - 0.01
    x1 = float(vis['x_front']) + float(proto['visibility']['grid_hidden_extent_m'])
    mx = (xs >= x0) & (xs <= x1)
    my = np.abs(ys - y_c) <= ch
    roi = np.zeros(grid['dims'], dtype=bool)
    roi[np.ix_(mx, my, np.ones(grid['dims'][2], dtype=bool))] = True
    return U & roi, mx, my, xs, ys


def _profile(occ, mx, my, zs):
    """走廊内每个 x 的顶面高度（无实体返回 None）。"""
    sub = occ[np.ix_(mx, my, np.ones(occ.shape[2], dtype=bool))]
    anyz = sub.any(axis=(1, 2))
    top = np.full(sub.shape[0], np.nan)
    if anyz.any():
        idx = np.where(anyz)[0]
        for k in idx:
            z = np.where(sub[k].any(axis=1))[0]
            if len(z):
                top[k] = zs[z.max()]
            else:
                top[k] = 0.0
        top[~anyz] = 0.0
    return top


def compute(state_dir, cand_id, proto):
    state_dir = pathlib.Path(state_dir)
    st = json.loads((state_dir / 'state.json').read_text())
    vis = st['visible']
    art = v3_fuse.load_v_artifact(state_dir / 'fusion')
    grid = art['grid']
    T, _ = _load_occ(state_dir / 'truth' / 'truth_occ.npz')
    V = np.asarray(art['shell'], bool)
    fused_p = state_dir / 'candidates' / cand_id / 'fused' / 'occ_full.npz'
    F, _ = _load_occ(fused_p) if fused_p.is_file() else (None, None)
    roi, mx, my, xs, ys = _roi(art, proto, vis)
    zs = grid['origin'][2] + (np.arange(grid['dims'][2]) + 0.5) * grid['pitch']
    out = {'schema': 'v3-hidden-error/v1', 'state_id': st['state_id'],
           'candidate_id': cand_id, 'roi_voxels': int(roi.sum()),
           'corridor_half_width_m': float(proto['hidden_error']['corridor_half_width_m'])}
    T_h = T & roi
    out['truth_hidden_voxels'] = int(T_h.sum())
    if F is not None:
        F_h = F & roi
        inter = int((T_h & F_h).sum())
        missing = int((T_h & ~F_h).sum())
        over = int((F_h & ~T_h).sum())
        out['A_hidden_occupancy'] = {
            'missing_rate': round(missing / max(1, int(T_h.sum())), 5),
            'overfill_rate': round(over / max(1, int(F_h.sum())), 5) if F_h.sum() else None,
            'iou': round(inter / max(1, int((T_h | F_h).sum())), 5),
            'truth_hidden_voxels': int(T_h.sum()),
            'pred_hidden_voxels': int(F_h.sum()),
            'eval_domain_voxels': int(roi.sum()),
            'applicable': bool(T_h.sum() > 0),
        }
        if not T_h.any():
            out['A_hidden_occupancy']['note'] = 'not_applicable（真值隐藏体素为 0）'
    else:
        out['A_hidden_occupancy'] = {'applicable': False, 'note': 'no_fused_geometry'}
    # B 沿路径顶面
    top_T = _profile(T, mx, my, zs)
    top_F = _profile(F, mx, my, zs) if F is not None else None
    top_V = _profile(V, mx, my, zs)
    x_band = xs[mx]
    ok = np.isfinite(top_T)
    out['B_path_top'] = {'n_samples': int(ok.sum()), 'sample_step_m': float(grid['pitch'])}
    if F is not None and ok.any():
        d = (top_F[ok] - top_T[ok]) * 1000.0
        out['B_path_top'].update({
            'mae_mm': round(float(np.mean(np.abs(d))), 3),
            'p95_mm': round(float(np.percentile(np.abs(d), 95)), 3),
            'over_mm': round(float(np.mean(np.clip(d, 0, None))), 3),
            'under_mm': round(float(np.mean(np.clip(-d, 0, None))), 3),
            'no_hidden_surface_frac': round(float(np.mean(top_F[ok] <= 1e-9)), 4),
            'profile_x_m': [round(float(x), 4) for x in x_band[ok][::10]],
            'profile_truth_m': [round(float(x), 4) for x in top_T[ok][::10]],
            'profile_pred_m': [round(float(x), 4) for x in top_F[ok][::10]],
            'profile_obs_m': [round(float(x), 4) for x in top_V[ok][::10]],
        })
    # C 背面结构
    def back_struct(top):
        if not np.isfinite(top).any():
            return {'missing': True}
        idx = np.where(np.isfinite(top) & (top > 0.002))[0]
        if len(idx) < 3:
            return {'missing': True, 'reason': 'no_measurable_back_edge'}
        i_rear = int(idx[-1])
        x_rear = float(x_band[i_rear])
        top_max = float(np.nanmax(top))
        drop_thr = top_max - 0.5 * max(1e-6, top_max)
        below = np.where(np.isfinite(top) & (top < drop_thr))[0]
        below = below[below < i_rear]
        x_drop = float(x_band[below[-1]]) if len(below) else None
        return {'rear_edge_x_m': round(x_rear, 4),
                'length_from_front_m': round(x_rear - float(vis['x_front']), 4),
                'top_max_m': round(top_max, 4),
                'back_drop_m': round(float(top_max - np.nanmin(top[idx])), 4),
                'drop_position_x_m': (round(x_drop, 4) if x_drop is not None else None),
                'missing': False}

    cT = back_struct(top_T)
    out['C_back_structure'] = {'truth': cT}
    if F is not None:
        cF = back_struct(top_F)
        out['C_back_structure']['pred'] = cF
        if not cT.get('missing') and not cF.get('missing'):
            out['C_back_structure'].update({
                'rear_edge_x_error_mm': round(1000 * (cF['rear_edge_x_m'] - cT['rear_edge_x_m']), 2),
                'length_error_mm': round(1000 * (cF['length_from_front_m']
                                                 - cT['length_from_front_m']), 2),
                'back_drop_error_mm': round(1000 * (cF['back_drop_m'] - cT['back_drop_m']), 2),
                'drop_position_error_mm': (
                    round(1000 * (cF['drop_position_x_m'] - cT['drop_position_x_m']), 2)
                    if (cF.get('drop_position_x_m') is not None
                        and cT.get('drop_position_x_m') is not None) else None),
            })
        elif cF.get('missing'):
            out['C_back_structure']['missing'] = 'pred_no_measurable_back_edge'
    # OBS_ONLY 的另一份口径（V 本身）
    top_V_ok = np.isfinite(top_V)
    if ok.any() and top_V_ok.any():
        dV = (top_V[ok] - top_T[ok]) * 1000.0
        out['OBS_ONLY_B'] = {'mae_mm': round(float(np.mean(np.abs(dV))), 3),
                             'p95_mm': round(float(np.percentile(np.abs(dV), 95)), 3),
                             'no_hidden_surface_frac': round(float(np.mean(top_V[ok] <= 1e-9)), 4)}
        out['OBS_ONLY_A'] = {'iou': 0.0, 'pred_hidden_voxels': 0,
                             'note': 'OBS_ONLY 在 U 内没有实体，IoU 定义为 0（不是缺失）'}
        out['OBS_ONLY_C'] = {'missing': True, 'reason': 'obs_only_has_no_back_structure'}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    state_dir = ROOT / a.state
    cands = sorted(p.name for p in (state_dir / 'candidates').glob('*')
                   if (p / 'fused' / 'occ_full.npz').is_file())
    out_dir = state_dir / 'metrics'
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in cands:
        r = compute(state_dir, c, proto)
        (out_dir / f'{c}.json').write_text(json.dumps(r, ensure_ascii=False, indent=2))
        rows.append({'candidate': c,
                     'A': r.get('A_hidden_occupancy'),
                     'B': {k: r.get('B_path_top', {}).get(k)
                           for k in ('mae_mm', 'p95_mm', 'over_mm', 'under_mm')},
                     'C': {k: r.get('C_back_structure', {}).get(k)
                           for k in ('rear_edge_x_error_mm', 'length_error_mm',
                                     'back_drop_error_mm', 'drop_position_error_mm',
                                     'missing')}})
    (out_dir / 'summary.json').write_text(json.dumps(
        {'schema': 'v3-hidden-error-summary/v1', 'state_id': state_dir.name,
         'rows': rows}, ensure_ascii=False, indent=2))
    print(json.dumps({'state': state_dir.name, 'n': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
