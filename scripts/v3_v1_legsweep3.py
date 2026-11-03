"""侧向重心转移标定：用 hip（x 轴、roll）把机身压向支撑三角，再抬 FR。

对 全局 hip 偏移 h（同号加到四条腿）与差动 hip（支撑腿 vs 抬腿）做小网格实测，
保持窗 0.9 s，记录 FR 抬高、FR 载荷、支撑腿最小载荷、倾角。
"""
import argparse
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
    ground = 0.0
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if b not in (b1, b2):
            continue
        other = b2 if b1 == b else b1
        # 只统计与地面/地形（worldbody 或 terrain body）的接触；车身自碰不算承载
        if other not in (0, int(getattr(env, 'terrain_body_id', -1))):
            continue
        f = np.zeros(6)
        mujoco.mj_contactForce(m, d, i, f)
        ground += abs(float(f[0]))
    return ground


def wz(env, leg):
    import mujoco
    b = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
    return float(env.data.xpos[b][2])


def trial(h_support, h_lift, ldt=0.6, ldc=-0.6, hold=0.9):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=5.0, name='sweep3')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=6.0)
    env.reset(seed=0)
    base = {leg: dict(STANCE) for leg in LEG}
    for _ in range(int(0.4 * 50)):
        env.step_command(joint_targets_rad=base, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
    z0 = wz(env, 'FR')
    tgt = {leg: {'hip': h_support, 'thigh': STANCE['thigh'], 'calf': STANCE['calf']}
           for leg in ('FL', 'RR', 'RL')}
    tgt['FR'] = {'hip': h_lift, 'thigh': STANCE['thigh'] + ldt,
                 'calf': STANCE['calf'] + ldc}
    n = int(hold * 50)
    loads = {leg: [] for leg in LEG}
    tilts = []
    for _ in range(n):
        env.step_command(joint_targets_rad=tgt, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
        for leg in LEG:
            loads[leg].append(wc(env, leg))
        tilts.append(float(env._tilt()))
    return {'hip_support': h_support, 'hip_lift': h_lift,
            'dz_m': round(wz(env, 'FR') - z0, 4),
            'fr_load_max': round(max(loads['FR']), 2),
            'support_load_min': round(min(min(loads[k]) for k in ('FL', 'RR', 'RL')), 2),
            'tilt_max_deg': round(max(tilts), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/control/legsweep3.json')
    a = ap.parse_args()
    rows = []
    for hs in (0.0, 0.15, 0.3, -0.15, -0.3):
        for hl in (0.0, 0.2, -0.2):
            rows.append(trial(hs, hl))
    ok = [r for r in rows if r['dz_m'] >= 0.04 and r['fr_load_max'] < 5.0
          and r['support_load_min'] > 4.0 and r['tilt_max_deg'] < 8.0]
    ok.sort(key=lambda r: (-r['dz_m'], r['tilt_max_deg']))
    out = ROOT / a.out
    out.write_text(json.dumps({'schema': 'v3-legsweep3/v1', 'rows': rows,
                               'n_ok': len(ok), 'best': ok[:3]},
                              ensure_ascii=False, indent=2))
    print(json.dumps({'n_ok': len(ok), 'best': ok[:3],
                      'top_tilt': sorted(rows, key=lambda r: r['tilt_max_deg'])[:3]},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
