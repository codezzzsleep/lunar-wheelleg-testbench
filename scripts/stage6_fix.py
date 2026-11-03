"""Stage006 有限修正：统一终点/稳定退出/全阶段记录；只重跑 BODY 两臂。"""
import hashlib
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import v3_record  # noqa: E402
import wheelleg_env  # noqa: E402
import stage6_rock as S6R  # noqa: E402

END_X = 2.6
ROBOT_KEYS = ('hip', 'thigh', 'calf', 'wheel', 'base')


def chassis_from_record(p):
    n = 0
    for f in sorted(pathlib.Path(p).glob('contacts_*.jsonl')):
        for line in f.open():
            d = json.loads(line)
            b1, b2 = d.get('g1_body'), d.get('g2_body')
            if not b1 or not b2:
                continue
            for a, b in ((b1, b2), (b2, b1)):
                if a == 'base_link' and b and not any(k in b for k in ROBOT_KEYS):
                    n += 1
    return n


def record_max_x(p):
    chunks = sorted(pathlib.Path(p).glob('chunk_*.npz'))
    xs = [np.load(c)['qpos'][:, 0].max() for c in chunks]
    return float(max(xs)) if xs else None


def main():
    out = (ROOT / 'runs/v3/stage006/fix').resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / 'configs/stage6_protocol.json').read_text())
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    (out / 'scene').mkdir(parents=True, exist_ok=True)
    spec, mesh, scale = S6R.build(out / 'scene', 0.30)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s'])); env.reset(seed=0)
    snap = env.save_state()
    def mk(lower, tag):
        params = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
                  'lower_at_x': lower, 'end_x': END_X, 'stop_tilt_deg': 12.0}
        return dict(params, plan_id=hashlib.sha256(
            json.dumps(params, sort_keys=True).encode()).hexdigest()[:16], far_edge_source=tag)
    plan_full = mk(1.495, 'truth_far_edge_known')
    plan_obs = mk(2.45, 'far_edge_unknown_hold')
    r_full = v3_core.run_body_clearance_cell(spec, snap, plan_full, proto, mode='same_scene',
                                             record_dir=out / 'record_full', budget=120.0)
    r_obs = v3_core.run_body_clearance_cell(spec, snap, plan_obs, proto, mode='same_scene',
                                            record_dir=out / 'record_obs', budget=120.0)
    recheck = {}
    for act in ('R2', 'D1'):
        p = ROOT / 'runs/v3/stage006/matrix2/record' / act
        mx = record_max_x(p) if p.exists() else None
        ch = chassis_from_record(p) if p.exists() else None
        recheck[act] = {'max_x': mx, 'chassis_contacts': ch,
                        'reached_end': bool(mx is not None and mx >= END_X - 1e-3),
                        'reusable': bool(mx is not None and mx >= END_X - 1e-3)}
    res = {'schema': 'stage6-fix/v1', 'common_end_x': END_X, 'budget_s': 120.0,
           'stability': 'tilt <= 10 deg at recover, no termination',
           'plans': {'full': plan_full, 'obs': plan_obs},
           'full': {k: r_full.get(k) for k in
                    ('reached', 'chassis_contacts', 'tipped_or_stuck', 'stable_exit',
                     'safe_pass', 'failed_phase', 'final_x', 'cost', 't_end',
                     'phase_times', 'n_control_steps', 'plan_id', 'lower_at_x', 'end_x')},
           'obs': {k: r_obs.get(k) for k in
                   ('reached', 'chassis_contacts', 'tipped_or_stuck', 'stable_exit',
                    'safe_pass', 'failed_phase', 'final_x', 'cost', 't_end',
                    'phase_times', 'n_control_steps', 'plan_id', 'lower_at_x', 'end_x')},
           'recheck_wheels': recheck}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
