"""D2 先行检查：同一个 5 cm 台，纯轮式驱动能不能过。

不做腿动作、不做决策；只回答"这个障碍是否已经需要腿"。
  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_wheel_probe.py --speed 0.30
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
    ap.add_argument('--soil', default='rigid', choices=['rigid', 'nominal'])
    ap.add_argument('--out', default='runs/v3/wheel_probe')
    a = ap.parse_args()
    out = ROOT / a.out / f'{a.soil}_v{a.speed:.2f}'
    out.mkdir(parents=True, exist_ok=True)
    sx_ledge = 0.5
    box_fr = vc.make_step(out / 'step_fr.stl', h=0.05, sx=sx_ledge, sy=0.27)
    box_fl = vc.make_step(out / 'step_fl.stl', h=0.05, sx=sx_ledge, sy=0.27)
    faces = {'FR': 0.95, 'FL': 1.13}
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=4.0, name='wheel_probe',
                             objects=[{'mesh_file': box_fr,
                                       'x': faces['FR'] + sx_ledge / 2, 'y': -0.115,
                                       'yaw_deg': 0.0},
                                      {'mesh_file': box_fl,
                                       'x': faces['FL'] + sx_ledge / 2, 'y': 0.185,
                                       'yaw_deg': 0.0}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=20.0)
    env.reset(seed=0)
    frames = []
    term = {}
    for k in range(int(12.0 * 50)):
        env.step_command(joint_targets_rad=STANCE,
                         wheel_omega_rad_s=np.full(4, a.speed / WHEEL_R),
                         wheel_mode='velocity')
        frames.append({'t': round(float(env.t), 3), 'x': round(float(env.data.qpos[0]), 4),
                       'tilt': round(float(env._tilt()), 3)})
        if env.terminated or env.truncated:
            term = {'terminated': bool(env.terminated),
                    'truncated': bool(env.truncated),
                    'reason': env.last_termination.get('reason')}
            break
        if float(env.data.qpos[0]) >= 1.55:
            break
    x = float(env.data.qpos[0])
    res = {'schema': 'v3-wheel-probe/v1', 'soil': a.soil, 'speed_mps': a.speed,
           'step_h_m': 0.05, 'wheel_radius_m': WHEEL_R,
           'final_x': round(x, 4), 'passed': bool(x >= 1.50),
           'tilt_max_deg': round(max(f['tilt'] for f in frames), 3) if frames else None,
           'termination': term, 'frames': len(frames),
           'note': '纯轮式、无腿动作；只用于判断 5 cm 台是否已经需要腿'}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
