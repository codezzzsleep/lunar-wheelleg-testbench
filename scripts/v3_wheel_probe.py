"""完整通行判据下的纯轮式探针。

成功 = 整车四轮都越过障碍最远后缘 + 完成下降 + 稳定保持 + 无终止。
不再用"机身 x 超过某个值"代替。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_wheel_probe.py --step-h 0.05 --speed 0.30
"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain            # noqa: E402
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402
import v3_climb as vc     # noqa: E402

LEG = vc.LEG
STANCE = {leg: dict(vc.STANCE[leg]) for leg in LEG}
WHEEL_R = vc.WHEEL_R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--speed', type=float, default=0.30)
    ap.add_argument('--step-h', type=float, default=0.05)
    ap.add_argument('--soil', default='rigid', choices=['rigid', 'nominal'])
    ap.add_argument('--out', default='runs/v3/wheel_probe')
    ap.add_argument('--face-x', type=float, default=0.95)
    ap.add_argument('--length', type=float, default=1.40)
    ap.add_argument('--width', type=float, default=0.90)
    a = ap.parse_args()
    tag = f'h{a.step_h:.2f}_v{a.speed:.2f}'
    out = ROOT / a.out / tag
    out.mkdir(parents=True, exist_ok=True)
    box = vc.make_step(out / 'platform.stl', h=a.step_h, sx=a.length, sy=a.width)
    far_x = a.face_x + a.length
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=far_x + 0.6,
                             name='wheel_probe',
                             objects=[{'mesh_file': box,
                                       'x': a.face_x + a.length / 2, 'y': 0.0,
                                       'yaw_deg': 0.0}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=25.0)
    env.reset(seed=0)
    import mujoco
    m, d = env.model, env.data
    wheels = {leg: vc.bc.wheel_body(env, leg) for leg in LEG}

    def wheel_x():
        return {leg: float(d.xpos[b][0]) for leg, b in wheels.items()}

    def ground_contact(leg):
        b = wheels[leg]
        for i in range(int(d.ncon)):
            c = d.contact[i]
            b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
            if b in (b1, b2):
                other = b2 if b1 == b else b1
                if other == 0:
                    return True
        return False

    crossed_at = None
    term = {}
    for k in range(int(18.0 * 50)):
        if all(x >= far_x - 0.02 for x in wheel_x().values()):
            crossed_at = float(env.t)
            break
        env.step_command(joint_targets_rad=STANCE,
                         wheel_omega_rad_s=np.full(4, a.speed / WHEEL_R),
                         wheel_mode='velocity')
        if env.terminated or env.truncated:
            term = {'terminated': bool(env.terminated),
                    'truncated': bool(env.truncated),
                    'reason': env.last_termination.get('reason')}
            break
    # 越过后缘后继续前进，让后轮完全落地并稳定，再保持
    settle_until = float(env.t) + 3.0
    while float(env.t) < settle_until and float(d.qpos[0]) < far_x + 0.45:
        env.step_command(joint_targets_rad=STANCE,
                         wheel_omega_rad_s=np.full(4, a.speed / WHEEL_R),
                         wheel_mode='velocity')
        if env.terminated or env.truncated:
            term = {'terminated': bool(env.terminated),
                    'truncated': bool(env.truncated),
                    'reason': env.last_termination.get('reason')}
            break
    # 下降 + 稳定保持
    hold = []
    for k in range(int(1.5 * 50)):
        env.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
        hold.append({'t': round(float(env.t), 3),
                     'tilt': round(float(env._tilt()), 3),
                     'x': round(float(d.qpos[0]), 4)})
        if env.terminated or env.truncated:
            term = {'terminated': bool(env.terminated),
                    'truncated': bool(env.truncated),
                    'reason': env.last_termination.get('reason')}
            break
    wx = wheel_x()
    crossed = all(x >= far_x - 0.02 for x in wx.values())
    grounded = {leg: ground_contact(leg) for leg in LEG}
    tilt_max = max((h['tilt'] for h in hold), default=99)
    stable = bool(hold and tilt_max <= 10.0 and all(grounded.values()))
    res = {'schema': 'v3-wheel-probe/v2', 'soil': a.soil, 'speed_mps': a.speed,
           'step_h_m': a.step_h, 'wheel_radius_m': WHEEL_R,
           'face_x': a.face_x, 'far_x': round(far_x, 4),
           'crossed_at_t': crossed_at, 'crossed': bool(crossed),
           'wheel_x': {k: round(v, 4) for k, v in wx.items()},
           'grounded': grounded, 'tilt_max_deg': round(tilt_max, 3),
           'stable': stable, 'passed': bool(crossed and stable and not term),
           'termination': term, 'final_x': round(float(d.qpos[0]), 4),
           'note': '完整通行：四轮越过后缘 + 下降 + 稳定保持 + 无终止'}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
