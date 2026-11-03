"""S2 下降：从四轮支撑状态低速越过台面最远后缘，落到平地并稳定保持。"""
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
    ap.add_argument('--soil', default='rigid', choices=['rigid', 'nominal'])
    ap.add_argument('--speed', type=float, default=0.10)
    ap.add_argument('--far-x', type=float, default=2.35)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    bundle = json.loads(pathlib.Path(a.state).read_text())
    snap, spec = bundle['snapshot'], dict(bundle['spec'])
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=60.0)
    env.reset(seed=0)
    env.restore_state(snap, strict=False, mode='same_scene')
    mujoco.mj_forward(env.model, env.data)
    m, d = env.model, env.data
    arr = np.asarray((snap.get('command') or {}).get('joint_targets'), dtype=float)
    targets = {leg: {'hip': float(arr[i, 0]), 'thigh': float(arr[i, 1]),
                     'calf': float(arr[i, 2])} for i, leg in enumerate(LEG)}
    # 预压最低载轮
    for _ in range(3):
        loads = {leg: vc.contact_load(env, leg) for leg in LEG}
        leg = min(loads, key=loads.get)
        if loads[leg] >= 3.0:
            break
        targets[leg]['thigh'] = float(np.clip(targets[leg]['thigh'] - 0.01, -1.571, 4.538))
        targets[leg]['calf'] = float(np.clip(targets[leg]['calf'] + 0.035, -2.723, -0.838))
        for _ in range(10):
            env.step_command(joint_targets_rad=targets, wheel_mode='coast')
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    drive = []
    for k in range(int(25.0 * 50)):
        env.step_command(joint_targets_rad=targets,
                         wheel_omega_rad_s=np.full(4, a.speed / vc.WHEEL_R),
                         wheel_mode='velocity')
        drive.append({'k': k, 'x': round(float(d.qpos[0]), 4),
                      'tilt': round(float(np.degrees(np.arccos(
                          np.clip(d.xmat[bid][8], -1, 1)))), 3)})
        if env.terminated or env.truncated or float(d.qpos[0]) >= a.far_x + 0.30:
            break
    hold = []
    for k in range(75):
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
        hold.append({'k': k, 't': round(float(env.t), 3),
                     'x': round(float(d.qpos[0]), 4),
                     'tilt': round(float(np.degrees(np.arccos(
                         np.clip(d.xmat[bid][8], -1, 1)))), 3),
                     'vx': round(float(d.qvel[0]), 4),
                     'loads': {leg: round(vc.contact_load(env, leg), 3) for leg in LEG}})
        if env.terminated or env.truncated:
            break
    wheel_z = {leg: round(float(d.xpos[bc.wheel_body(env, leg)][2]), 4) for leg in LEG}
    tail = hold[-50:]
    tilt = max((r['tilt'] for r in tail), default=99)
    vx = max((abs(r['vx']) for r in tail), default=99)
    grounded = all(z <= 0.12 for z in wheel_z.values())
    crossed = float(d.qpos[0]) >= a.far_x + 0.25
    ok = bool(tail and crossed and grounded and tilt <= 10.0 and vx <= 0.03
              and not env.terminated)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').write_text(json.dumps(
        {'schema': 'v3-descent/v1', 'soil': a.soil, 'ok': ok,
         'final_x': round(float(d.qpos[0]), 4), 'crossed': crossed,
         'wheel_z': wheel_z, 'grounded': grounded, 'tilt_max': tilt,
         'vx_max': vx, 'terminated': bool(env.terminated),
         'drive_frames': len(drive), 'hold_frames': len(hold),
         'hold': hold}, ensure_ascii=False, indent=2))
    if not env.terminated:
        sp = out / 'final_state.json'
        sp.write_text(json.dumps({'snapshot': env.save_state(), 'spec': spec},
                                 ensure_ascii=False))
    print(json.dumps({'ok': ok, 'final_x': round(float(d.qpos[0]), 4),
                      'tilt_max': tilt, 'vx_max': vx, 'grounded': grounded,
                      'wheel_z': wheel_z}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
