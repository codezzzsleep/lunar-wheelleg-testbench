"""支撑转移标定：抬一条腿之前，其余三条先蹲一点（降低机身、扩大稳定三角）。

扫描 (support_dthigh, support_dcalf) × (lift_dthigh, lift_dcalf)，
在 0.9 s 保持窗里评估：FR 抬高、FR 卸载、其余三轮最小载荷、机身倾角。
选“FR 抬离地且其余三轮全程承重、倾角最小”的格点。
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


def trial(sdt, sdc, ldt, ldc):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=5.0, name='sweep2')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=6.0)
    env.reset(seed=0)
    base = {leg: dict(STANCE) for leg in LEG}
    for _ in range(int(0.4 * 50)):
        env.step_command(joint_targets_rad=base, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
    z0 = wz(env, 'FR')
    support = {leg: {'hip': 0.0, 'thigh': STANCE['thigh'] + sdt,
                     'calf': STANCE['calf'] + sdc} for leg in ('FL', 'RR', 'RL')}
    support['FR'] = dict(STANCE)
    for _ in range(int(0.25 * 50)):
        env.step_command(joint_targets_rad=support, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
    lift = {k: dict(v) for k, v in support.items()}
    lift['FR'] = {'hip': 0.0, 'thigh': STANCE['thigh'] + ldt, 'calf': STANCE['calf'] + ldc}
    n = int(0.9 * 50)
    loads = {leg: [] for leg in LEG}
    tilts = []
    for _ in range(n):
        env.step_command(joint_targets_rad=lift, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
        for leg in LEG:
            loads[leg].append(wc(env, leg))
        tilts.append(float(env._tilt()))
    return {'support_dthigh': sdt, 'support_dcalf': sdc,
            'lift_dthigh': ldt, 'lift_dcalf': ldc,
            'dz_m': round(wz(env, 'FR') - z0, 4),
            'fr_load_max': round(max(loads['FR']), 2),
            'support_load_min': round(min(min(loads[k]) for k in ('FL', 'RR', 'RL')), 2),
            'tilt_max_deg': round(max(tilts), 2),
            'tilt_end_deg': round(tilts[-1], 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/control/legsweep2.json')
    a = ap.parse_args()
    rows = []
    for sdt, sdc in ((0.0, 0.0), (0.15, -0.15), (0.3, -0.3)):
        for ldt, ldc in ((0.3, -0.6), (0.45, -0.75), (0.6, -0.6)):
            rows.append(trial(sdt, sdc, ldt, ldc))
    ok = [r for r in rows if r['dz_m'] >= 0.04 and r['fr_load_max'] < 5.0
          and r['support_load_min'] > 4.0 and r['tilt_max_deg'] < 8.0]
    ok.sort(key=lambda r: (-r['dz_m'], r['tilt_max_deg']))
    out = ROOT / a.out
    out.write_text(json.dumps({'schema': 'v3-legsweep2/v1', 'rows': rows,
                               'n_ok': len(ok), 'best': ok[:3]},
                              ensure_ascii=False, indent=2))
    print(json.dumps({'n_ok': len(ok), 'best': ok[:2],
                      'all': [{k: r[k] for k in ('support_dthigh', 'lift_dthigh',
                                                 'dz_m', 'fr_load_max',
                                                 'support_load_min', 'tilt_max_deg')}
                              for r in rows]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
