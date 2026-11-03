"""标定：单腿抬轮的方向与幅度（实测扫描，不猜符号）。

对 FR 腿在 (d_thigh, d_calf) 网格上各保持 0.45 s，记录轮心抬升与接触载荷，
选“轮离地且其余三轮仍承载”的格点写入 runs/v3/control/legsweep.json。
"""
import argparse
import itertools
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain
import wheelleg_env

LEG = ('FR', 'FL', 'RR', 'RL')
STANCE = {'hip': 0.0, 'thigh': 0.85, 'calf': -1.65}


def wc(env, leg):
    import mujoco
    m, d = env.model, env.data
    b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
    tot = 0.0
    for i in range(int(d.ncon)):
        c = d.contact[i]
        if m.geom_bodyid[c.geom1] == b or m.geom_bodyid[c.geom2] == b:
            f = np.zeros(6)
            mujoco.mj_contactForce(m, d, i, f)
            tot += abs(float(f[0]))
    return tot


def wz(env, leg):
    import mujoco
    b = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
    return float(env.data.xpos[b][2])


def trial(dt, dc, settle=0.4, hold=0.45):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=5.0, name='sweep')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=4.0)
    env.reset(seed=0)
    stance = {leg: dict(STANCE) for leg in LEG}
    for _ in range(int(settle * 50)):
        env.step_command(joint_targets_rad=stance, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
    z0 = wz(env, 'FR'); base = {leg: wc(env, leg) for leg in LEG}
    tgt = {leg: dict(STANCE) for leg in LEG}
    tgt['FR'] = {'hip': 0.0, 'thigh': STANCE['thigh'] + dt, 'calf': STANCE['calf'] + dc}
    loads = {leg: 0.0 for leg in LEG}
    n = int(hold * 50)
    for _ in range(n):
        env.step_command(joint_targets_rad=tgt, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
        for leg in LEG:
            loads[leg] += wc(env, leg)
    return {'d_thigh': dt, 'd_calf': dc, 'dz_m': round(wz(env, 'FR') - z0, 4),
            'fr_load': round(loads['FR'] / n, 2),
            'other_load_min': round(min(loads[k] for k in ('FL', 'RR', 'RL')) / n, 2),
            'tilt_deg': round(float(env._tilt()), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/control/legsweep.json')
    a = ap.parse_args()
    rows = []
    for dt, dc in itertools.product((-0.6, -0.3, 0.0, 0.3, 0.6), repeat=2):
        rows.append(trial(dt, dc))
    ok = [r for r in rows if r['dz_m'] >= 0.03 and r['fr_load'] < 5.0
          and r['other_load_min'] > 5.0 and r['tilt_deg'] < 10.0]
    ok.sort(key=lambda r: -r['dz_m'])
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'schema': 'v3-legsweep/v1', 'rows': rows,
                               'n_ok': len(ok), 'best': ok[:3]},
                              ensure_ascii=False, indent=2))
    print(json.dumps({'n_ok': len(ok), 'best': ok[:3],
                      'worst': sorted(rows, key=lambda r: r['dz_m'])[:2]},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
