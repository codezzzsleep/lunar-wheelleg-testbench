"""S2 结构 A 原型：从末段快照停驱动，逐步下放未承载轮，尝试恢复三点/四点支撑。"""
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
    ap.add_argument('--seconds', type=float, default=2.5)
    ap.add_argument('--dz', type=float, default=0.003)
    ap.add_argument('--out', required=True)
    ap.add_argument('--save-final', default='')
    ap.add_argument('--mode', default='unloaded', choices=['unloaded', 'body', 'fl_joint', 'level', 'touch'])
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
    rows, changes = [], []
    for k in range(int(a.seconds * 50)):
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
        if k % 5 == 0 and not env.terminated:
            loads = {leg: vc.contact_load(env, leg) for leg in LEG}
            if a.mode == 'level':
                for leg in ('FL', 'RL'):
                    targets[leg]['thigh'] = float(np.clip(targets[leg]['thigh'] + 0.004, -1.571, 3.491))
                    targets[leg]['calf'] = float(np.clip(targets[leg]['calf'] - 0.014, -2.723, -0.838))
                for leg in ('FR', 'RR'):
                    targets[leg]['thigh'] = float(np.clip(targets[leg]['thigh'] - 0.004, -1.571, 4.538))
                    targets[leg]['calf'] = float(np.clip(targets[leg]['calf'] + 0.014, -2.723, -0.838))
                changes.append({'k': k, 'leg': 'level', 'dq': [0.004, -0.014]})
            if a.mode == 'touch':
                for leg in LEG:
                    if loads[leg] < 1.0:
                        targets[leg]['thigh'] = float(np.clip(
                            targets[leg]['thigh'] - 0.02, -1.571, 4.538))
                        targets[leg]['calf'] = float(np.clip(
                            targets[leg]['calf'] + 0.07, -2.723, -0.838))
                        changes.append({'k': k, 'leg': leg, 'dq': [-0.02, 0.07]})
            if a.mode == 'fl_joint':
                if loads.get('FL', 0.0) < 1.0:
                    targets['FL']['thigh'] = float(np.clip(targets['FL']['thigh'] - 0.03, -1.571, 3.491))
                    targets['FL']['calf'] = float(np.clip(targets['FL']['calf'] + 0.10, -2.723, -0.838))
                    changes.append({'k': k, 'leg': 'FL', 'dq': [-0.03, 0.10]})
            for leg in LEG:
                if a.mode in ('body',) or (a.mode == 'unloaded' and loads[leg] < 1.0):
                    dp = np.array([0.0, 0.0, -a.dz])
                    dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.03, 0.03)
                    for p, v in zip(('hip', 'thigh', 'calf'), dq):
                        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f'{leg}_{p}_joint')
                        lo, hi = (float(x) for x in m.jnt_range[j])
                        targets[leg][p] = float(np.clip(targets[leg][p] + float(v), lo, hi))
                    changes.append({'k': k, 'leg': leg, 'dq': [round(float(x), 5) for x in dq]})
        loads = {leg: vc.contact_load(env, leg) for leg in LEG}
        rows.append({'k': k, 't': round(float(env.t), 3),
                     'tilt': round(float(np.degrees(np.arccos(
                         np.clip(d.xmat[bid][8], -1, 1)))), 3),
                     'loads': {l: round(v, 3) for l, v in loads.items()},
                     'base_z': round(float(d.qpos[2]), 4),
                     'up': [round(float(d.xmat[bid][i]), 4) for i in (6, 7, 8)]})
        if env.terminated or env.truncated:
            break
    last = rows[-1] if rows else {}
    n_support = sum(1 for v in (last.get('loads') or {}).values() if v >= 1.0)
    ok = bool(last and last['tilt'] <= 10.0 and n_support >= 3
              and (last['loads'].get('RR', 0) >= 1.0) and not env.terminated)
    if a.save_final:
        fp = ROOT / a.save_final
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps({'snapshot': env.save_state(), 'spec': spec},
                                 ensure_ascii=False))
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').write_text(json.dumps(
        {'schema': 'v3-endgame-recover/v1', 'soil': a.soil, 'dz': a.dz,
         'ok': ok, 'n_support': n_support, 'last': last,
         'terminated': bool(env.terminated), 'changes': changes[:40],
         'rows': rows}, ensure_ascii=False, indent=2))
    print(json.dumps({'ok': ok, 'n_support': n_support, 'last': last,
                      'changes': len(changes)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
