"""v3 筛选：只用完整真值判定 hidden_sensitive / complete_feasible。

对每个预定状态：
  1. 在**完整真值** T 上规划（同一动作集/控制器/nominal 土壤/30 s/同一代价规则）；
  2. 在**观测体** V 上规划（同一口径）；
  3. 把两条选择都放到完整真值上执行，比较三结局；
  4. hidden_sensitive = 动作不同 或 结局不同；complete_feasible = 真值至少有一条通行动作。

筛选阶段**不加载任何 Lux3D 候选/结果**；真值只用于筛选、离线误差和最终揭晓。

  python scripts/v3_screen.py --states all --workers 4
  python scripts/v3_screen.py --state runs/v3/states/<sid>
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import v3_core
import v3_fuse

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'runs/v3/screen'


def _boxes(state_dir, occ_npz, out_dir, proto):
    if (out_dir / 'manifest.json').is_file():
        return json.loads((out_dir / 'manifest.json').read_text())
    r = v3_core.build_collision(occ_npz, out_dir, pitch=proto['collision']['pitch_m'],
                                downsample=int(proto['collision'].get('box_downsample', 1)))
    if not r['ok']:
        raise RuntimeError(f'boxes failed: {r.get("error")}')
    return r['manifest']


def screen_state(state_dir, proto):
    state_dir = pathlib.Path(state_dir)
    st = json.loads((state_dir / 'state.json').read_text())
    sid = st['state_id']
    t0 = time.time()
    rec = {'schema': 'v3-screen/v1', 'state_id': sid, 'rock_id': st['rock_id'],
           'level': st['level'], 'view': st['view'], 'height_m': st['height_m'],
           'hr_ratio': st['hr_ratio']}
    # 公共观测体 V 与真值占据
    if not (state_dir / 'fusion' / 'V.npz').is_file():
        v3_fuse.write_v_artifact(state_dir, proto)
    art = v3_fuse.load_v_artifact(state_dir / 'fusion')
    if not (state_dir / 'truth' / 'truth_occ.npz').is_file():
        v3_fuse.write_truth_occ(state_dir, proto)
    truth_man = _boxes(state_dir, state_dir / 'truth' / 'truth_occ.npz',
                       state_dir / 'truth' / 'coll', proto)
    # OBS_ONLY 的碰撞由 occ_obs_only 生成（与 V 逐体素相同）
    if not (state_dir / 'fusion' / 'obs_only_occ.npz').is_file():
        import numpy as np
        import hashlib
        np.savez_compressed(
            state_dir / 'fusion' / 'obs_only_occ.npz',
            occupied=art['shell'],
            origin=np.asarray(art['grid']['origin'], float),
            pitch=np.float64(art['grid']['pitch']),
            dims=np.asarray(art['grid']['dims'], int),
            content_sha=np.array(hashlib.sha256(
                np.ascontiguousarray(art['shell']).tobytes()).hexdigest()[:32]),
            convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    obs_man = _boxes(state_dir, state_dir / 'fusion' / 'obs_only_occ.npz',
                     state_dir / 'obs_only' / 'coll', proto)
    core = v3_core.load_state(state_dir)
    # 真值规划
    # 真值规划直接跑真值网格场景（与执行同一表示），不用粗 box 近似
    rows_t, app_t = v3_core.rehearse_on_spec(core, v3_core.truth_spec(core),
                                            core['snapshot'], proto, mode='same_scene')
    dec_t = v3_core.aggregate(rows_t, ['truth'], {}, 'majority', proto,
                              applic={k: tuple(v) for k, v in app_t.items()})
    # 观测体规划
    rows_v, app_v = v3_core.rehearse(core, {'obs': str(state_dir / 'obs_only' / 'coll')},
                                     core['snapshot'], proto)
    dec_v = v3_core.aggregate(rows_v, ['obs'], {}, 'majority', proto,
                              applic={k: tuple(v) for k, v in app_v.items()})
    # 两条选择都在完整真值上执行
    ex_t = v3_core.truth_execute(core, dec_t['chosen'], proto, state_dir / 'screen_exec',
                                 'TRUTH')
    ex_v = v3_core.truth_execute(core, dec_v['chosen'], proto, state_dir / 'screen_exec',
                                 'OBS')
    traverse = {a: {'success': r['success'], 'reason': r['reason'], 'cost': r['cost']}
                for a, r in dec_t['per_candidate']['truth'].items() if a != 'A0'}
    complete_feasible = any(v['success'] for v in traverse.values())
    action_diff = dec_t['chosen'] != dec_v['chosen']
    outcome_diff = ex_t.get('outcome') != ex_v.get('outcome')
    hidden_sensitive = bool(action_diff or outcome_diff)
    rec.update({
        'truth_plan': {'chosen': dec_t['chosen'], 'costs': dec_t['mean_cost_s'],
                       'votes': dec_t['votes'], 'reason': dec_t['reason']},
        'obs_plan': {'chosen': dec_v['chosen'], 'costs': dec_v['mean_cost_s'],
                     'votes': dec_v['votes'], 'reason': dec_v['reason']},
        'truth_exec': {'action': dec_t['chosen'], 'outcome': ex_t.get('outcome'),
                       'reason': ex_t.get('reason'), 'final_x': ex_t.get('final_x'),
                       't_end': ex_t.get('t_end')},
        'obs_exec': {'action': dec_v['chosen'], 'outcome': ex_v.get('outcome'),
                     'reason': ex_v.get('reason'), 'final_x': ex_v.get('final_x'),
                     't_end': ex_v.get('t_end')},
        'traverse': traverse,
        'complete_feasible': bool(complete_feasible),
        'action_differs': bool(action_diff),
        'outcome_differs': bool(outcome_diff),
        'hidden_sensitive': hidden_sensitive,
        'selected': bool(hidden_sensitive and complete_feasible),
        'layer': ('action_and_outcome' if action_diff and outcome_diff else
                  'action_only' if action_diff else
                  'outcome_only' if outcome_diff else 'none'),
        'pipeline_errors': [r for r in (dec_t.get('errors') or []) + (dec_v.get('errors') or [])],
        'wall_s': round(time.time() - t0, 2),
        'screened_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    })
    rec['truth_boxes'] = truth_man.get('n_boxes')
    rec['obs_boxes'] = obs_man.get('n_boxes')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{sid}.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default=None)
    ap.add_argument('--states', default=None)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--workers', type=int, default=1)
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    if a.state:
        print(json.dumps(screen_state(ROOT / a.state, proto), ensure_ascii=False))
        return
    dirs = [p.parent for p in sorted((ROOT / 'runs/v3/states').glob('*/state.json'))]
    if a.states and a.states != 'all':
        keep = set(a.states.split(','))
        dirs = [d for d in dirs if d.name in keep]
    from concurrent.futures import ProcessPoolExecutor
    rows = []
    with ProcessPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = {ex.submit(screen_state, d, proto): d for d in dirs}
        for f in futs:
            try:
                r = f.result()
                rows.append({k: r[k] for k in ('state_id', 'rock_id', 'level', 'view',
                                               'complete_feasible', 'hidden_sensitive',
                                               'selected', 'layer', 'wall_s')})
                print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
            except Exception as e:  # noqa: BLE001
                rows.append({'state': futs[f].name, 'error': f'{type(e).__name__}: {e}'})
                print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    idx = {'schema': 'v3-screen-index/v1', 'n': len(rows), 'rows': rows,
           'selected': [r['state_id'] for r in rows if r.get('selected')]}
    (OUT / 'index.json').write_text(json.dumps(idx, ensure_ascii=False, indent=2))
    print(json.dumps({'n': len(rows), 'n_selected': len(idx['selected'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
