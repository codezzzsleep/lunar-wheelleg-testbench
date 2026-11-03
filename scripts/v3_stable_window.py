"""S2：从四轮支撑状态做 1 s 稳定窗口验收（tilt/速度/角速度/margin/支撑数）。"""
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
    ap.add_argument('--seconds', type=float, default=1.0)
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
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    # 预调：若 margin < 10 mm，用四条腿把 CoM 沿最近边内法向平移 5 mm，最多两轮
    for _ in range(2):
        loads0 = {leg: vc.contact_load(env, leg) for leg in LEG}
        pts0 = []
        for leg in LEG:
            if loads0[leg] >= 1.0:
                pts0 += [np.asarray(p[:2]) for p in vc.contact_points(env, leg)]
        if len(pts0) < 3:
            break
        mm0, inward = bc.nearest_edge(pts0, bc.com(env)[:2])
        if mm0 >= 0.010:
            break
        dp = np.zeros(3)
        dp[:2] = np.asarray(inward, dtype=float) * 0.005
        start = {leg: dict(targets[leg]) for leg in LEG}
        goal = {leg: dict(targets[leg]) for leg in LEG}
        for leg in LEG:
            dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.03, 0.03)
            for p_, v in zip(('hip', 'thigh', 'calf'), dq):
                lo, hi = vc.jlim(env, leg, p_)
                goal[leg][p_] = float(np.clip(start[leg][p_] + float(v), lo, hi))
        for i in range(15):
            a_ = (i + 1) / 15
            for leg in LEG:
                for p_ in ('hip', 'thigh', 'calf'):
                    targets[leg][p_] = float(start[leg][p_] + a_ * (goal[leg][p_] - start[leg][p_]))
            env.step_command(joint_targets_rad=targets, wheel_mode='coast')
    # 预压：把载荷最小的轮子小幅下放（2 mm 级），直到 >=3 N，最多 3 次
    for _ in range(3):
        loads1 = {leg: vc.contact_load(env, leg) for leg in LEG}
        leg = min(loads1, key=loads1.get)
        if loads1[leg] >= 3.0:
            break
        targets[leg]['thigh'] = float(np.clip(targets[leg]['thigh'] - 0.01, -1.571, 4.538))
        targets[leg]['calf'] = float(np.clip(targets[leg]['calf'] + 0.035, -2.723, -0.838))
        for _ in range(10):
            env.step_command(joint_targets_rad=targets, wheel_mode='coast')
    rows = []
    for k in range(int(a.seconds * 50)):
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
        loads = {leg: vc.contact_load(env, leg) for leg in LEG}
        pts = []
        for leg in LEG:
            if loads[leg] >= 1.0:
                pts += [np.asarray(p[:2]) for p in vc.contact_points(env, leg)]
        com = bc.com(env)
        margin = None
        if len(pts) >= 3:
            mm, _ = bc.nearest_edge(pts, com[:2])
            margin = round(float(mm), 4) if mm > -0.5 else None
        w = d.qvel[3:6]
        rows.append({'k': k, 't': round(float(env.t), 3),
                     'tilt': round(float(np.degrees(np.arccos(
                         np.clip(d.xmat[bid][8], -1, 1)))), 3),
                     'vx': round(float(d.qvel[0]), 4),
                     'omega': round(float(np.linalg.norm(w)), 4),
                     'margin': margin, 'n_support': sum(1 for v in loads.values() if v >= 1.0),
                     'loads': {l: round(v, 3) for l, v in loads.items()}})
        if env.terminated or env.truncated:
            break
    tilt = max(r['tilt'] for r in rows)
    vx = max(abs(r['vx']) for r in rows)
    om = max(r['omega'] for r in rows)
    margins = [r['margin'] for r in rows if r['margin'] is not None]
    ns = min(r['n_support'] for r in rows)
    ok = bool(rows and tilt <= 10 and vx <= 0.03 and om <= 0.1
              and margins and min(margins) >= 0.010 and ns >= 3 and not env.terminated)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    res = {'schema': 'v3-stable-window/v1', 'soil': a.soil, 'ok': ok,
           'tilt_max': tilt, 'vx_max': vx, 'omega_max': om,
           'margin_min': min(margins) if margins else None,
           'margin_frames': len(margins), 'n_support_min': ns,
           'terminated': bool(env.terminated), 'rows': rows}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({k: res[k] for k in ('ok', 'tilt_max', 'vx_max', 'omega_max',
                                          'margin_min', 'n_support_min')}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
