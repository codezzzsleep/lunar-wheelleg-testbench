"""S1：从末段快照继续原命令，逐帧记录 RR 载荷掉零的时刻与伴随状态。"""
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
    ap.add_argument('--seconds', type=float, default=2.0)
    ap.add_argument('--wheel-mode', default='velocity', choices=['velocity', 'coast', 'brake', 'decel'])
    ap.add_argument('--decel-seconds', type=float, default=0.5)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    bundle = json.loads(pathlib.Path(a.state).read_text())
    snap, spec = bundle['snapshot'], bundle['spec']
    spec = dict(spec)
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=60.0)
    env.reset(seed=0)
    env.restore_state(snap, strict=False, mode='same_scene')
    mujoco.mj_forward(env.model, env.data)
    m, d = env.model, env.data
    cmd = snap.get('command') or {}
    jt_arr = np.asarray(cmd.get('joint_targets'), dtype=float)
    jt = {leg: {'hip': float(jt_arr[i, 0]), 'thigh': float(jt_arr[i, 1]),
                'calf': float(jt_arr[i, 2])} for i, leg in enumerate(LEG)}
    omega = float((cmd.get('wheel_omega') or [0.0])[0])
    rb = bc.wheel_body(env, 'RR')
    rows = []
    for k in range(int(a.seconds * 50)):
        if a.wheel_mode == 'velocity':
            env.step_command(joint_targets_rad=jt,
                             wheel_omega_rad_s=np.full(4, omega),
                             wheel_mode='velocity')
        elif a.wheel_mode == 'decel':
            n_dec = max(1, int(a.decel_seconds * 50))
            w = omega * max(0.0, 1.0 - k / n_dec)
            if w > 1e-6:
                env.step_command(joint_targets_rad=jt,
                                 wheel_omega_rad_s=np.full(4, w),
                                 wheel_mode='velocity')
            else:
                env.step_command(joint_targets_rad=jt, wheel_mode='coast')
        else:
            env.step_command(joint_targets_rad=jt, wheel_mode=a.wheel_mode)
        loads = {leg: vc.contact_load(env, leg) for leg in LEG}
        rows.append({'k': k, 't': round(float(env.t), 3),
                     'tilt': round(float(np.degrees(np.arccos(
                         np.clip(d.xmat[mujoco.mj_name2id(
                             m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')][8], -1, 1)))), 3),
                     'rr_load': round(loads['RR'], 3),
                     'loads': {l: round(v, 3) for l, v in loads.items()},
                     'rr_z': round(float(d.xpos[rb][2]), 4),
                     'base_z': round(float(d.qpos[2]), 4),
                     'vx': round(float(d.qvel[0]), 4),
                     'rr_thigh': round(float(d.qpos[m.jnt_qposadr[mujoco.mj_name2id(
                         m, mujoco.mjtObj.mjOBJ_JOINT, 'RR_thigh_joint')]]), 4),
                     'rr_calf': round(float(d.qpos[m.jnt_qposadr[mujoco.mj_name2id(
                         m, mujoco.mjtObj.mjOBJ_JOINT, 'RR_calf_joint')]]), 4)})
        if env.terminated or env.truncated:
            break
    first = next((r for r in rows if r['rr_load'] < 0.5), None)
    tail = rows[-50:]
    fl_vals = [r['loads']['FL'] for r in tail]
    rr_vals = [r['loads']['RR'] for r in tail]
    summary = {'fl_mean': round(float(np.mean(fl_vals)), 3) if fl_vals else None,
               'fl_frac_ge1': round(float(np.mean([v >= 1.0 for v in fl_vals])), 3) if fl_vals else None,
               'rr_mean': round(float(np.mean(rr_vals)), 3) if rr_vals else None,
               'rr_frac_ge1': round(float(np.mean([v >= 1.0 for v in rr_vals])), 3) if rr_vals else None,
               'tilt_max': max((r['tilt'] for r in tail), default=None),
               'vx_last': rows[-1]['vx'] if rows else None,
               'window_s': round(len(tail) / 50.0, 2)}
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / 'trace.json').write_text(json.dumps(
        {'schema': 'v3-endgame-trace/v1', 'soil': a.soil, 'omega': omega,
         'wheel_mode': a.wheel_mode,
         'rr_target': jt['RR'], 'first_zero': first, 'tail_summary': summary,
         'rows': rows},
        ensure_ascii=False, indent=2))
    print(json.dumps({'rows': len(rows), 'first_zero': first,
                      'tail_summary': summary}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
