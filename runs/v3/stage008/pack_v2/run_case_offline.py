#!/usr/bin/env python3
"""Stage009 full cached case, offline: identity-bound caches -> aggregate -> decision -> truth run."""
import argparse, json, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'scripts'))
import v3_core, stage8_cache as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=str(HERE / 'data'))
    ap.add_argument('--out', default='out/case')
    a = ap.parse_args()
    data = pathlib.Path(a.data); out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((HERE / 'plans/v3_protocol.json').read_text())
    truth = data / 'truth'
    spec = json.loads((truth / 'scene_spec.json').read_text())
    for obj in spec.get('objects', []):
        if obj.get('posed_dir'):
            obj['posed_dir'] = str((truth / 'coll').resolve())
    snap = json.loads((truth / 'state_snapshot.json').read_text())
    tm = json.loads((truth / 'truth_manifest.json').read_text())
    fusion = json.loads((data / 'fusion' / 'fusion_summary.json').read_text())
    ident = json.loads((data / 'decisions' / 'cache_identity.json').read_text())
    geom = {t: v['scene_sha'] for t, v in ident['candidates'].items()}
    rows = {}; checks = {}
    for t, v in ident['candidates'].items():
        try:
            rr, app = C.read_cache(data / 'decisions' / v['cache'], {
                's0_state_hash': ident['s0_state_hash'], 'scene_sha256': v['scene_sha'],
                'plan_id': v['plan_id'], 'protocol_sha256': ident['protocol_sha256'],
                'actions': ident['actions'], 'applicability': ident['applicability']})
            rows[t] = rr; checks[f'full_{t}_identity'] = True
        except Exception as e:  # noqa: BLE001
            checks[f'full_{t}_identity'] = False; print('CACHE FAIL', t, e)
    try:
        obs_rows, obs_app = C.read_cache(data / 'decisions' / ident['obs']['cache'], {
            's0_state_hash': ident['s0_state_hash'], 'scene_sha256': ident['obs']['scene_sha'],
            'plan_id': ident['obs']['plan_id'], 'protocol_sha256': ident['protocol_sha256'],
            'actions': ident['actions'], 'applicability': ident['applicability']})
        checks['obs_identity'] = True
    except Exception as e:  # noqa: BLE001
        checks['obs_identity'] = False; obs_rows = []; print('CACHE FAIL OBS', e)
    if not all(checks.values()):
        print(json.dumps({'cache_checks': checks, 'exit': 'refused_before_execution'}, ensure_ascii=False))
        return 2
    applic = {k: (v, None) for k, v in ident['applicability'].items()}
    opts = ident['actions']
    dec_full = v3_core.aggregate(sum(rows.values(), []), list(rows), geom, 'majority', proto,
                                 threshold_mode='majority', applic=applic, options=opts)
    dec_obs = v3_core.aggregate(obs_rows, ['OBS'], {}, 'majority', proto,
                                threshold_mode='majority', applic=applic, options=opts)
    cached = {arm: json.loads((data / 'decisions' / f'decision_{arm}.json').read_text())
              for arm in ('FULL', 'OBS')}
    checks['FULL_chosen_matches_cache'] = dec_full['chosen'] == cached['FULL']['decision']['chosen']
    checks['OBS_chosen_matches_cache'] = dec_obs['chosen'] == cached['OBS']['decision']['chosen']
    if not all(checks.values()):
        print(json.dumps({'cache_checks': checks, 'exit': 'refused_before_execution'}, ensure_ascii=False))
        return 2
    # 执行前写本次决策与运行清单
    state = {'state': {'state_id': 'stage9_offline', 'state_hash': tm['s0_state_hash']},
             'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30}}
    drec_f = v3_core.write_decision(out, state, 'FULL', sum(rows.values(), []), dec_full,
                                    {'plan': fusion['plans']['full'], 'cache_identity': ident})
    drec_o = v3_core.write_decision(out, state, 'OBS', obs_rows, dec_obs,
                                    {'plan': fusion['plans']['obs'], 'cache_identity': ident})
    manifest = {'schema': 'stage9-offline-run/v1', 'truth_occ_sha256': tm['truth_occ_sha256'],
                's0_state_hash': tm['s0_state_hash'], 'protocol_sha256': ident['protocol_sha256'],
                'FULL': {'decision_sha': drec_f['decision_sha'], 'chosen': dec_full['chosen'],
                         'plan': fusion['plans']['full']},
                'OBS': {'decision_sha': drec_o['decision_sha'], 'chosen': dec_obs['chosen'],
                        'plan': fusion['plans']['obs']},
                'cache_checks': checks}
    (out / 'run_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    core = {'spec': spec, 'snapshot': snap,
            'visible': state['visible'],
            'state': {'state_id': 'stage8_truth_v2', 'state_hash': tm['s0_state_hash']}}
    ex_f = v3_core.truth_execute(core, dec_full['chosen'], proto, out / 'exec_full', 'TRUTH_FULL',
                                 body_plan=fusion['plans']['full'], budget=120.0)
    ex_o = v3_core.truth_execute(core, dec_obs['chosen'], proto, out / 'exec_obs', 'TRUTH_OBS',
                                 body_plan=fusion['plans']['obs'], budget=120.0)
    res = {'truth_occ_sha256': tm['truth_occ_sha256'], 's0_state_hash': tm['s0_state_hash'],
           'cache_checks': checks,
           'FULL': {'chosen': dec_full['chosen'], 'decision_sha': drec_f['decision_sha'],
                    'exec': {k: ex_f.get(k) for k in ('action','outcome','t_end','chassis_contacts','safe_pass','reached','plan_id')}},
           'OBS': {'chosen': dec_obs['chosen'], 'decision_sha': drec_o['decision_sha'],
                   'exec': {k: ex_o.get(k) for k in ('action','outcome','t_end','chassis_contacts','safe_pass','reached','plan_id')}}}
    (out / 'offline_case.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False)[:1200])
    return 0


if __name__ == '__main__':
    sys.exit(main())
