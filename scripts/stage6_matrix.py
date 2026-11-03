"""Stage006：岩石场景上 BODY_CLEARANCE 与轮式动作的共用入口预演/决策/执行。"""
import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import wheelleg_env  # noqa: E402
import stage6_rock as S6R  # noqa: E402

ROBOT_KEYS = ('hip', 'thigh', 'calf', 'wheel', 'base')


def chassis_contacts_from_record(ref):
    p = pathlib.Path(ref['trajectory_path']).parent
    n = 0
    for f in sorted(p.glob('contacts_*.jsonl')):
        for line in f.open():
            d = json.loads(line)
            b1, b2 = d.get('g1_body'), d.get('g2_body')
            if not b1 or not b2:
                continue
            for a, b in ((b1, b2), (b2, b1)):
                if a == 'base_link' and b and not any(k in b for k in ROBOT_KEYS):
                    n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage006/matrix')
    ap.add_argument('--height', type=float, default=0.30)
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / 'configs/stage6_protocol.json').read_text())
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    spec, mesh, scale = S6R.build(out, a.height)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s'])); env.reset(seed=0)
    snap = env.save_state()
    core = {'spec': spec, 'snapshot': snap,
            'visible': {'x_front': 0.855, 'W_vis': 0.30, 'H_vis': a.height},
            'state': {'state_id': f'stage6_rock_{int(a.height*1000)}',
                      'state_hash': snap.get('state_hash')}}
    lower_at = 1.145 + 0.35
    plan = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
            'lower_at_x': lower_at, 'pass_x': lower_at, 'time_limit': 80.0,
            'stop_tilt_deg': 12.0, 'plan_id': hashlib.sha256(
                json.dumps({'raise_z': 0.06, 'speed': 0.15, 'lower_at_x': lower_at},
                           sort_keys=True).encode()).hexdigest()[:16]}
    rows, app = v3_core.rehearse_on_spec(core, spec, snap, proto,
                                         options=cfg['actions'], body_plan=plan,
                                         budget=float(cfg['budget_s']),
                                         record_cells=True, record_root=out / 'record')
    for r in rows:
        ref = r.get('trajectory_ref')
        if ref:
            c = chassis_contacts_from_record(ref)
            r['chassis_contacts'] = c
            if c > 0 and r.get('success'):
                r['success'] = False
                r['outcome'] = 'chassis_contact'
                r['reason'] = 'chassis_obstacle_contact'
    dec = v3_core.aggregate(rows, ['truth'], {}, 'majority', proto,
                            threshold_mode='majority', applic=app,
                            options=cfg['actions'])
    v3_core.write_decision(out, core, 'TRUTH', rows, dec,
                           {'body_plan': plan, 'scene_criterion': cfg['scene_criterion']})
    ex = v3_core.truth_execute(core, dec['chosen'], proto, out / 'truth_exec', 'TRUTH',
                               body_plan=plan, budget=float(cfg['budget_s']))
    res = {'schema': 'stage6-matrix/v1', 'rock_height': a.height,
           'plan': plan, 'votes': dec['votes'], 'costs': dec['mean_cost_s'],
           'chosen': dec['chosen'], 'reason': dec['reason'],
           'rows': [{k: r.get(k) for k in ('action', 'success', 'outcome', 'reason',
                                           'cost', 't_end', 'chassis_contacts',
                                           'base_rise', 'clearance_gain', 'plan_id')}
                    for r in rows],
           'exec': {'action': dec['chosen'], 'outcome': ex.get('outcome'),
                    't_end': ex.get('t_end'), 'chassis_contacts': ex.get('chassis_contacts')},
           'budget_s': cfg['budget_s']}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'chosen': dec['chosen'], 'votes': dec['votes'],
                      'rows': res['rows'], 'exec': res['exec']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
