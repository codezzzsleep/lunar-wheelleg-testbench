"""T-as-parent 正对照：把真值网格当"父先验"走同一条融合/碰撞/预演链。

用途：如果连"完美的隐藏几何"都过不了这条链，问题在链；如果过了，问题在先验。
  python scripts/v3_tparent.py --state runs/v3/states/<sid> --protocol plans/v3_protocol.json
输出 runs/v3/states/<sid>/tparent/{result.json, occ_full.npz, coll/}
"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core
import v3_fuse as FZ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--no-rehearse', action='store_true')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    sd = (ROOT / a.state) if not pathlib.Path(a.state).is_absolute() else pathlib.Path(a.state)
    out = sd / 'tparent'
    out.mkdir(parents=True, exist_ok=True)
    art = FZ.load_v_artifact(sd / 'fusion')
    grid = art['grid']
    V, space = art['shell'], art['space']
    U, B, F = (space == 0), (space == 1), (space == 2)
    T, info, _ = FZ.truth_occupancy(sd, proto)
    gen_U = T & U
    FULL = V | gen_U
    # 与真实候选同样的合同断言
    ok_obs = bool(np.array_equal(V, V))
    diff_in_U = not (FULL & ~V & ~U).any()
    free_clear = int((FULL & F).sum()) == 0
    np.savez_compressed(out / 'occ_full.npz', occupied=FULL,
                        origin=np.asarray(grid['origin'], float),
                        pitch=np.float64(grid['pitch']),
                        dims=np.asarray(grid['dims'], int),
                        content_sha=np.array(FZ.arr_sha(FULL)),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    he = proto.get('hidden_error', {})
    half = float(he.get('corridor_half_m', 0.16))
    x_front = float(proto['scene'].get('obstacle_x', 1.35))
    extent = float(proto['visibility'].get('hidden_extent_m', 0.4))
    xs, ys = grid['xs'][:, None, None], grid['ys'][None, :, None]
    roi = np.broadcast_to(((xs >= x_front) & (xs <= x_front + extent)
                           & (np.abs(ys) <= half)), U.shape).copy() & U
    T_h, P_h = T & roi, gen_U & roi
    inter = int((T_h & P_h).sum()); miss = int((T_h & ~P_h).sum()); over = int((P_h & ~T_h).sum())
    res = {'schema': 'v3-tparent/v1', 'state_id': sd.name,
           'note': '真值网格直接当父先验（已在世界系，不做配准）',
           'n_truth_total': int(T.sum()), 'n_v': int(V.sum()),
           'n_generated_unknown': int(gen_U.sum()), 'n_full': int(FULL.sum()),
           'assertions': {'diff_subset_u': bool(diff_in_U), 'free_clear': bool(free_clear),
                          'obs_equals_v': ok_obs},
           'truth_hidden_roi': {'T': int(T_h.sum()), 'P': int(P_h.sum()),
                                'intersection': inter, 'missing': miss, 'overfill': over,
                                'missing_rate': round(miss / max(1, int(T_h.sum())), 5),
                                'overfill_rate': round(over / max(1, int(P_h.sum())), 5),
                                'iou': round(inter / max(1, int((T_h | P_h).sum())), 5)}}
    if not a.no_rehearse:
        coll = out / 'coll'
        r = v3_core.build_collision(out / 'occ_full.npz', coll,
                                    pitch=proto['collision']['pitch_m'],
                                    downsample=int(proto['collision'].get('box_downsample', 1)))
        res['collision'] = {'ok': r.get('ok'), 'n_boxes': r.get('n_boxes'),
                            'cache_key': r.get('cache_key')}
        st = v3_core.load_state(sd)
        rows, applic = v3_core.rehearse(st, {'T': str(coll)}, st['snapshot'], proto)
        dec = v3_core.aggregate(rows, ['T'], {'T': FZ.arr_sha(FULL)}, 'majority', proto,
                                applic={k: tuple(v) for k, v in applic.items()})
        res['decision'] = {'chosen': dec['chosen'], 'votes': dec['votes'],
                           'reason': dec['reason'], 'n_valid': dec['n_valid']}
        ex = v3_core.truth_execute(st, dec['chosen'], proto, out, 'TPARENT', mode='same_scene')
        res['execution'] = {'action': ex.get('action'), 'outcome': ex.get('outcome'),
                            'reason': ex.get('reason'), 'final_x': ex.get('final_x')}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False)[:900])


if __name__ == '__main__':
    main()
