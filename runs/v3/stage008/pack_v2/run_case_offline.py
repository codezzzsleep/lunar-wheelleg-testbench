#!/usr/bin/env python3
"""Stage008 full cached case, offline: cached matrices -> aggregate -> decision -> truth run -> replay."""
import argparse, json, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'scripts'))
import v3_core, terrain, v7_soil, wheelleg_env


def load_rows(p):
    return [json.loads(l) for l in open(p)] if pathlib.Path(p).exists() else []


def build_env(spec, budget=120.0):
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=budget)
    env.reset(seed=0)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=str(HERE / 'data'))
    ap.add_argument('--out', default='out/case')
    a = ap.parse_args()
    data = pathlib.Path(a.data); out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((HERE / 'plans/v3_protocol.json').read_text())
    truth = data / 'truth'
    spec = json.loads((truth / 'scene_spec.json').read_text())
    # 包内碰撞路径：把 spec 里记录的绝对路径改写到本包 data/truth/coll
    for obj in spec.get('objects', []):
        if obj.get('posed_dir'):
            obj['posed_dir'] = str((truth / 'coll').resolve())
    snap = json.loads((truth / 'state_snapshot.json').read_text())
    tm = json.loads((truth / 'truth_manifest.json').read_text())
    fusion = json.loads((data / 'fusion' / 'fusion_summary.json').read_text())
    dec_cache = {arm: json.loads((data / 'decisions' / f'decision_{arm}.json').read_text())
                 for arm in ('FULL', 'OBS')}
    rows_full = load_rows(data / 'decisions' / 'matrix_FULL.jsonl')
    rows_obs = load_rows(data / 'decisions' / 'matrix_OBS.jsonl')
    geom = {t: fusion['candidates'][t]['full_sha'] for t in fusion['candidates']}
    opts = ['R1','R2','D1','D2','L1','L2','CLIMB','BODY_CLEARANCE','A0']
    applic = {a: (True, None) for a in opts}
    applic['CLIMB'] = (False, 'climb_not_applicable')
    dec_full = v3_core.aggregate(rows_full, list(geom.keys()), geom, 'majority', proto,
                                 threshold_mode='majority', applic=applic, options=opts)
    dec_obs = v3_core.aggregate(rows_obs, ['OBS'], {}, 'majority', proto, threshold_mode='majority',
                                applic=applic, options=opts)
    checks = {'FULL_chosen_matches_cache': dec_full['chosen'] == dec_cache['FULL']['decision']['chosen'],
              'OBS_chosen_matches_cache': dec_obs['chosen'] == dec_cache['OBS']['decision']['chosen']}
    core = {'spec': spec, 'snapshot': snap,
            'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
            'state': {'state_id': 'stage8_truth_v2', 'state_hash': tm['s0_state_hash']}}
    env = build_env(spec)
    env.restore_state(snap, mode='same_scene')
    restored = env.save_state().get('state_hash')
    ex_full = v3_core.truth_execute(core, dec_full['chosen'], proto, out / 'exec_full', 'TRUTH_FULL',
                                    body_plan=fusion['plans']['full'], budget=120.0)
    ex_obs = v3_core.truth_execute(core, dec_obs['chosen'], proto, out / 'exec_obs', 'TRUTH_OBS',
                                   body_plan=fusion['plans']['obs'], budget=120.0)
    res = {'truth_occ_sha256': tm['truth_occ_sha256'], 's0_state_hash': tm['s0_state_hash'],
           'restored_state_hash': restored, 'cache_checks': checks,
           'FULL': {'chosen': dec_full['chosen'], 'votes': dec_full['votes'],
                    'exec': {k: ex_full.get(k) for k in ('action','outcome','t_end','chassis_contacts','safe_pass','reached')}},
           'OBS': {'chosen': dec_obs['chosen'], 'votes': dec_obs['votes'],
                   'exec': {k: ex_obs.get(k) for k in ('action','outcome','t_end','chassis_contacts','safe_pass','reached')}}}
    (out / 'offline_case.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False)[:1200])


if __name__ == '__main__':
    main()
