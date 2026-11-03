"""F：约 20 m 连续路线（平地 + 三个 5 cm 台阶），纯轮式慢压连续通过。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_route.py --soil rigid --out runs/v3/route/r1
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
    ap.add_argument('--soil', default='rigid', choices=['rigid', 'nominal'])
    ap.add_argument('--speed', type=float, default=0.30)
    ap.add_argument('--out', default='runs/v3/route/r1')
    ap.add_argument('--goal-x', type=float, default=23.5)
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    boxes = []
    for i, x in enumerate((4.0, 10.0, 16.0)):
        p = vc.make_step(out / f'step_{i}.stl', h=0.05, sx=1.0, sy=0.9)
        boxes.append({'mesh_file': p, 'x': x, 'y': 0.0, 'yaw_deg': 0.0})
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=24.0, name='route_20m',
                             span=12.5, objects=boxes)
    spec['terrain']['field_x_max'] = 25.0
    spec['channel'] = {'center_y': 0.0, 'half_width': 3.0}
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=60.0)
    env.reset(seed=0)
    frames = []
    term = {}
    for k in range(int(60.0 * 50)):
        env.step_command(joint_targets_rad=STANCE,
                         wheel_omega_rad_s=np.full(4, a.speed / WHEEL_R),
                         wheel_mode='velocity')
        if k % 5 == 0:
            frames.append({'t': round(float(env.t), 3),
                           'x': round(float(env.data.qpos[0]), 4),
                           'tilt': round(float(env._tilt()), 3)})
        if env.terminated or env.truncated:
            term = {'terminated': bool(env.terminated),
                    'truncated': bool(env.truncated),
                    'reason': env.last_termination.get('reason')}
            break
        if float(env.data.qpos[0]) >= a.goal_x:
            break
    # 终点稳定保持 1 s
    hold = []
    for _ in range(50):
        env.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
        hold.append(round(float(env._tilt()), 3))
        if env.terminated or env.truncated:
            break
    x = float(env.data.qpos[0])
    tilt_max = max([f['tilt'] for f in frames] + hold)
    res = {'schema': 'v3-route/v1', 'soil': a.soil, 'speed_mps': a.speed,
           'steps_m': [4.0, 10.0, 16.0], 'step_h_m': 0.05,
           'final_x': round(x, 4), 'goal_x': a.goal_x,
           'passed': bool(x >= a.goal_x - 0.05 and not term and tilt_max <= 10.0),
           'tilt_max_deg': round(tilt_max, 3), 'termination': term,
           'time_s': round(float(env.t), 3), 'frames': len(frames),
           'note': '纯轮式慢压；三处 5 cm 台阶；终点稳定 1 s'}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    np.savez_compressed(out / 'frames.npz',
                        t=np.array([f['t'] for f in frames]),
                        x=np.array([f['x'] for f in frames]),
                        tilt=np.array([f['tilt'] for f in frames]))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
