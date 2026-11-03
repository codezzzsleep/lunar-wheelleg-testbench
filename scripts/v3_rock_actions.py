"""在真实岩石真值场景上，从同一 S0 快照逐个跑动作库。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_rock_actions.py \
      --state runs/v3/states/moon_rock_04_h1v0 --actions R1,R2,D1,D2,A0,L1,L2 \
      --out runs/v3/rock_actions/moon_rock_04_h1v0

轮式基线 = R1/R2/D1/D2/A0（不抬腿）；L1/L2 是腿式动作，用来对照。
每个动作都在 truth 网格、same_scene、同一初态上独立执行。
"""
import argparse
import json
import pathlib

import numpy as np
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import mujoco  # noqa: E402
import trimesh  # noqa: E402
import v3_core  # noqa: E402
import v3_climb as vc  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402

def ground_contact(env, leg):
    m, d = env.model, env.data
    b = vc.bc.wheel_body(env, leg)
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if b in (b1, b2) and (b2 if b1 == b else b1) == 0:
            return True
    return False


WHEEL_SET = ('R1', 'R2', 'D1', 'D2', 'A0')
LEG_SET = ('L1', 'L2')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--actions', default='R1,R2,D1,D2,A0,L1,L2')
    ap.add_argument('--out', required=True)
    ap.add_argument('--budget', type=float, default=None)
    ap.add_argument('--soil', default='nominal', choices=['rigid', 'nominal'])
    a = ap.parse_args()
    sd = (ROOT / a.state).resolve()
    st = v3_core.load_state(sd)
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    spec = v3_core.truth_spec(st)
    spec['soil'] = v7_soil.resolve(a.soil)
    rock_max_x = None
    tw = sd / 'truth' / 'body_world.stl'
    if tw.exists():
        mesh = trimesh.load(str(tw), force='mesh')
        rock_max_x = float(mesh.bounds[1][0])
    out = (ROOT / a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in [x.strip() for x in a.actions.split(',') if x.strip()]:
        env = v3_core.make_env(spec, proto, budget=a.budget)
        try:
            r = v3_core.run_action(env, st['snapshot'], name, st['visible'],
                                   mode='same_scene', seed=0, record=True)
            wheel_x = {leg: round(float(env.data.xpos[vc.bc.wheel_body(env, leg)][0]), 4)
                       for leg in vc.LEG}
            # 动作结束后先 mj_forward 刷新接触表，再查四轮落地
            mujoco.mj_forward(env.model, env.data)
            # 轮心高度 <= 0.12 m 视为已下降回平地（轮半径 0.086 m）；
            # 接触表在动作结束后不可靠，不再用它判落地。
            grounded = {leg: float(env.data.xpos[vc.bc.wheel_body(env, leg)][2]) <= 0.12
                        for leg in vc.LEG}
            base_z = round(float(env.data.qpos[2]), 4)
            final_tilt = round(float(env._tilt()), 3)
            crossed = bool(rock_max_x is not None
                           and all(x > rock_max_x + 0.03 for x in wheel_x.values()))
            # 动作结束后接触表可能未刷新；用机身高度作为“已下降回平地”的代理
            descended = bool(base_z <= 0.42)
            unified = bool(crossed and descended and final_tilt <= 10.0
                           and all(grounded.values())
                           and not env.terminated and not env.truncated)
            rows.append({'action': name, 'success': bool(r['success']),
                         'reason': r['reason'], 'final_x': r['final_x'],
                         'displacement_x': r['displacement_x'],
                         'max_tilt': r['max_tilt'], 'steps': r['steps'],
                         'cost': r['cost'], 'phases': r.get('phases'),
                         'rock_max_x': round(rock_max_x, 4) if rock_max_x else None,
                         'wheel_x': wheel_x, 'grounded': grounded,
                         'final_tilt': final_tilt, 'base_z': base_z,
                         'crossed': crossed, 'descended': descended,
                         'unified': unified})
        except Exception as e:  # noqa: BLE001
            rows.append({'action': name, 'success': False,
                         'reason': f'exception:{type(e).__name__}:{e}'})
        finally:
            del env
        print(json.dumps(rows[-1], ensure_ascii=False))
    wheel = [r for r in rows if r['action'] in WHEEL_SET]
    leg = [r for r in rows if r['action'] in LEG_SET]
    res = {'schema': 'v3-rock-actions/v2', 'state': str(sd.relative_to(ROOT)),
           'soil': a.soil, 'rock_max_x': round(rock_max_x, 4) if rock_max_x else None,
           'rows': rows,
           'wheel_ok': any(r.get('unified') for r in wheel),
           'wheel_unified_ok': any(r.get('unified') for r in wheel),
           'leg_unified_ok': any(r.get('unified') for r in leg) if leg else None,
           'leg_ok': any(r['success'] for r in leg) if leg else None,
           'note': '轮式基线 = R1/R2/D1/D2/A0；L1/L2 为腿式对照'}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
