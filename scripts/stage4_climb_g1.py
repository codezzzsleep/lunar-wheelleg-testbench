"""G1：原开发场景，正式矩阵里预演/选择/执行 CLIMB（接线验证，不追价值）。"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import v3_climb as VC  # noqa: E402
import v3_record  # noqa: E402
import terrain  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import actions as ACT  # noqa: E402
import stage4_config as S4C  # noqa: E402
import stage4_geometry as S4G  # noqa: E402


def make_dev_spec(out):
    ledges = [{'face': 0.95, 'len': 1.40, 'y': -0.115}, {'face': 1.13, 'len': 1.22, 'y': 0.185}]
    objects = []
    for i, l in enumerate(ledges):
        nm = 'step_fr.stl' if i == 0 else 'step_fl.stl'
        mesh = VC.make_step(out / nm, h=0.05, sx=l['len'], sy=0.45)
        objects.append({'mesh_file': mesh, 'x': l['face'] + l['len'] / 2.0,
                        'y': l['y'], 'yaw_deg': 0.0})
    far = min(l['face'] + l['len'] for l in ledges)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=far + 0.6, name='stage4_g1', objects=objects)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    return spec, far


def run_climb(core, proto, plan, out_dir, tag):
    spec = json.loads(json.dumps(core['spec']))
    env = v3_core.make_env(spec, proto, budget=float(S4C.budget()))
    env.restore_state(core['snapshot'], mode='same_scene')
    rec = v3_record.Recorder(out_dir / tag, {'action': 'CLIMB', 'plan_id': plan['plan_id']}, hz=50.0)
    faces = {'FR': plan['params']['face_FR'], 'FL': plan['params']['face_FL']}
    phases, c = VC.run_climb_episode(env, plan['params'], faces, out_dir, rec=rec,
                                     rear=True, no_shift=False)
    ref = rec.close()
    checks = {p['phase']: bool(p.get('ok')) for p in phases}
    success = bool(all(checks.values()) and not c.terminated)
    outcome = 'pass' if success else ('physical_failure' if c.terminated else 'abort')
    t_end = float(phases[-1].get('t', 0.0)) if phases else 0.0
    row = {'action': 'CLIMB', 'ok': True, 'success': success, 'abort': not success,
           'reason': 'success' if success else ('terminated' if c.terminated else 'phase_failed'),
           'outcome': outcome, 'final_x': round(float(env.data.qpos[0]), 4),
           't_end': round(float(env.t), 3), 'cost': round(float(env.t), 3),
           'max_tilt': max((p.get('tilt_max_deg', 0.0) for p in phases), default=0.0),
           'plan_id': plan['plan_id'], 'trajectory_ref': ref,
           'phases': phases, 'checks': checks, 'terminated': bool(c.terminated)}
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--soil', default='nominal')
    a = ap.parse_args()
    out = (ROOT / a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg = S4C.load()
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    spec, far = make_dev_spec(out)
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s']))
    env.reset(seed=0)
    snap = env.save_state()
    visible = {'x_front': 0.95, 'W_vis': 0.45, 'H_vis': 0.05,
               'x_front_m': 0.95, 'W_vis_m': 0.45, 'H_vis_m': 0.05}
    core = {'spec': spec, 'snapshot': snap, 'visible': visible,
            'state': {'state_id': 'dev_g1', 'state_hash': snap.get('state_hash')}}
    geo_obs = {'face_FR': 0.95, 'face_FL': 1.13, 'top_z': 0.05, 'far_x': far,
               'landing': None, 'source': 'dev_truth_wiring'}
    gp = S4G.derive_skill_params(geo_obs)
    plan = {'action': 'CLIMB', 'params': gp['params'], 'source': 'dev_truth_wiring',
            'applicable': gp['valid'], 'plan_id': 'dev_g1'}
    rows = []
    for act in [x for x in cfg['actions'] if x != 'CLIMB']:
        ok, why = ACT.applicable(act, visible, 1.2)
        if not ok and act != 'A0':
            rows.append({'action': act, 'success': False, 'outcome': 'not_applicable',
                         'reason': why, 'cost': 60.0, 't_end': None, 'candidate': 'dev'})
            continue
        env2 = v3_core.make_env(spec, proto, budget=float(S4C.budget()))
        r = v3_core.run_action(env2, snap, act, visible, mode='same_scene',
                               record_dir=out / 'record' / act,
                               record_meta={'action': act, 'plan_id': act})
        r['candidate'] = 'dev'
        rows.append(r)
    climb_row = run_climb(core, proto, plan, out / 'record', 'CLIMB')
    climb_row['candidate'] = 'dev'
    rows.append(climb_row)
    applic = {}
    for act in ACT.OPTIONS:
        if act == 'A0':
            continue
        if act not in cfg['actions']:
            applic[act] = (False, 'not_in_stage4_protocol')
        else:
            applic[act] = ACT.applicable(act, visible, 1.2)
    applic['CLIMB'] = (bool(plan['applicable']), None)
    with (out / 'matrix.jsonl').open('w') as fh:
        for rr in rows:
            fh.write(json.dumps({k: v for k, v in rr.items() if k != 'trajectory_ref'},
                                ensure_ascii=False) + '\n')
    (out / 'applic.json').write_text(json.dumps({k: list(v) for k, v in applic.items()}, ensure_ascii=False, indent=2))
    dec = v3_core.aggregate(rows, ['dev'], {}, 'majority', proto,
                            threshold_mode='majority', applic=applic,
                            options=cfg['actions'])
    ex = None
    if dec['chosen'] == 'CLIMB':
        ex = run_climb(core, proto, plan, out / 'record_exec', 'CLIMB_exec')
    else:
        env3 = v3_core.make_env(spec, proto, budget=float(S4C.budget()))
        ex = v3_core.run_action(env3, snap, dec['chosen'], visible, mode='same_scene',
                                record_dir=out / 'record_exec' / dec['chosen'],
                                record_meta={'action': dec['chosen']})
    res = {'schema': 'stage4-g1/v1', 'protocol': cfg['revision'],
           'budget_s': cfg['budget_s'], 'plan': plan,
           'climb_matrix': {k: climb_row[k] for k in
                            ('action', 'success', 'outcome', 'cost', 't_end', 'plan_id')},
           'climb_phases_ok': climb_row['checks'],
           'votes': dec['votes'], 'costs': dec['mean_cost_s'],
           'chosen': dec['chosen'], 'reason': dec['reason'],
           'exec': {'action': dec['chosen'], 'success': ex.get('success'),
                    'outcome': ex.get('outcome'), 't_end': ex.get('t_end')},
           'note': 'wiring only; wheels are expected to be cheaper and may be chosen',
           'matrix_rows': [{k: r.get(k) for k in ('action','success','outcome','cost','t_end','reason')} for r in rows],
           'n_valid': dec['n_valid'], 'agg_errors': dec['errors'][:5]}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'climb_ok': climb_row['success'], 'climb_cost': climb_row['cost'],
                      'chosen': dec['chosen'], 'votes': dec['votes'],
                      'exec': res['exec']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
