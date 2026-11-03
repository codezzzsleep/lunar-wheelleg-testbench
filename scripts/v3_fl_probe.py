"""FL 垂直运动学单测：直接给 FL 关节下放增量，测轮心 z 的实际响应。"""
import argparse
import json
import pathlib
import sys

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402
import v3_climb as vc     # noqa: E402
import v3_basic_cycle as bc  # noqa: E402

LEG = bc.LEG


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--dthigh', type=float, default=0.15)
    ap.add_argument('--dcalf', type=float, default=-0.5)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    bundle = json.loads(pathlib.Path(a.state).read_text())
    snap, spec = bundle['snapshot'], dict(bundle['spec'])
    spec['soil'] = v7_soil.resolve('rigid')
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
    env.reset(seed=0)
    env.restore_state(snap, strict=False, mode='same_scene')
    mujoco.mj_forward(env.model, env.data)
    m, d = env.model, env.data
    arr = np.asarray((snap.get('command') or {}).get('joint_targets'), dtype=float)
    targets = {leg: {'hip': float(arr[i, 0]), 'thigh': float(arr[i, 1]),
                     'calf': float(arr[i, 2])} for i, leg in enumerate(LEG)}
    fb = bc.wheel_body(env, 'FL')

    def flz():
        return round(float(d.xpos[fb][2]), 4)

    z0 = flz()
    start = dict(targets['FL'])
    for i in range(25):
        t = (i + 1) / 25
        targets['FL']['thigh'] = start['thigh'] + a.dthigh * t
        targets['FL']['calf'] = start['calf'] + a.dcalf * t
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
    z1 = flz()
    res = {'schema': 'v3-fl-probe/v1', 'state': a.state,
           'dthigh': a.dthigh, 'dcalf': a.dcalf,
           'fl_z0': z0, 'fl_z1': z1, 'dz': round(z1 - z0, 4),
           'fl_load': round(vc.contact_load(env, 'FL'), 3),
           'thigh_actual': round(float(d.qpos[m.jnt_qposadr[mujoco.mj_name2id(
               m, mujoco.mjtObj.mjOBJ_JOINT, 'FL_thigh_joint')]]), 4),
           'calf_actual': round(float(d.qpos[m.jnt_qposadr[mujoco.mj_name2id(
               m, mujoco.mjtObj.mjOBJ_JOINT, 'FL_calf_joint')]]), 4)}
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
