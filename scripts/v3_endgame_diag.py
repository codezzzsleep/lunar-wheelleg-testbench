"""S1：从 CLIMB 末段快照恢复（same_scene），测清 RR 零载荷是哪一种，再做安全退出。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_endgame_diag.py --state /tmp/endgame_rigid/state.json --soil rigid --out runs/v3/stage003/s1_rigid
"""
import argparse
import json
import pathlib
import sys

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain            # noqa: E402
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402
import v3_climb as vc     # noqa: E402
import v3_basic_cycle as bc  # noqa: E402

LEG = bc.LEG


def build_env(soil, spec=None):
    if spec is None:
        src = pathlib.Path('/tmp/e3b_rigid')
        box_fr = str(src / 'step_fr.stl')
        box_fl = str(src / 'step_fl.stl')
        spec = terrain.make_spec(kind='flat', seed=0, goal_x=2.95, name='stage003_s1',
                                 objects=[{'mesh_file': box_fr, 'x': 0.95 + 0.70,
                                           'y': -0.115, 'yaw_deg': 0.0},
                                          {'mesh_file': box_fl, 'x': 1.13 + 0.61,
                                           'y': 0.185, 'yaw_deg': 0.0}])
        spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec = dict(spec)
    spec['soil'] = v7_soil.resolve(soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=40.0)
    env.reset(seed=0)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--soil', default='rigid', choices=['rigid', 'nominal'])
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    bundle = json.loads(pathlib.Path(a.state).read_text())
    snap = bundle.get('snapshot') or bundle
    spec = bundle.get('spec')
    env = build_env(a.soil, spec)
    env.restore_state(snap, strict=False, mode='same_scene')
    mujoco.mj_forward(env.model, env.data)
    m, d = env.model, env.data
    roll, pitch = bc.attitude(env)
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    up_z = float(np.clip(d.xmat[bid][8], -1.0, 1.0))
    tilt_deg = float(np.degrees(np.arccos(up_z)))
    com = bc.com(env)
    wheels = {}
    for leg in LEG:
        b = bc.wheel_body(env, leg)
        x, y, z = (float(v) for v in d.xpos[b])
        wheels[leg] = {'x': round(x, 4), 'y': round(y, 4), 'z': round(z, 4),
                       'bottom_z': round(z - vc.WHEEL_R, 4),
                       'load_n': round(vc.contact_load(env, leg), 3)}
    # RR 与 FR 台面的几何关系
    rr = wheels['RR']
    in_fr_x = 0.95 <= rr['x'] <= 2.35
    in_fr_y = -0.34 <= rr['y'] <= 0.11
    clearance = round(rr['bottom_z'] - 0.05, 4)   # 轮底到台面
    contacts = []
    rb = bc.wheel_body(env, 'RR')
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if rb in (b1, b2):
            fr = np.asarray(c.frame, dtype=float).reshape(3, 3)
            f = np.zeros(6)
            mujoco.mj_contactForce(m, d, i, f)
            contacts.append({'other_body': int(b2 if b1 == rb else b1),
                             'pos': [round(float(x), 4) for x in c.pos],
                             'normal_z': round(float(fr[0, 2]), 3),
                             'normal_force': round(float(f[0]), 3),
                             'top': bool(abs(float(fr[0, 2])) >= 0.7)})
    # 关节实际/目标/限位
    jt = (snap.get('command') or {}).get('joint_rad') or {}
    joints = {}
    for leg in LEG:
        joints[leg] = {}
        for part in ('hip', 'thigh', 'calf'):
            j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f'{leg}_{part}_joint')
            lo, hi = (float(v) for v in m.jnt_range[j])
            act = float(d.qpos[m.jnt_qposadr[j]])
            tgt = jt.get(leg, {}).get(part)
            joints[leg][part] = {'actual': round(act, 4), 'target': tgt,
                                 'range': [round(lo, 3), round(hi, 3)],
                                 'at_limit': bool(act <= lo + 1e-3 or act >= hi - 1e-3)}
    # 安全退出：1 s 原地保持
    rows = []
    hold_t = getattr(env, '_last_joint_targets', None)
    if hold_t is None:
        hold_t = {l: dict(vc.STANCE[l]) for l in LEG}
    for _ in range(50):
        env.step_command(joint_targets_rad=hold_t, wheel_mode='coast')
        rows.append({'t': round(float(env.t), 3), 'tilt': round(float(env._tilt()), 3),
                     'vx': round(float(d.qvel[0]), 4),
                     'rr_load': round(vc.contact_load(env, 'RR'), 3)})
        if env.terminated or env.truncated:
            break
    safe = bool(rows and max(r['tilt'] for r in rows) <= 10.0
                and abs(rows[-1]['vx']) <= 0.03 and not env.terminated)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    res = {'schema': 'v3-endgame-diag/v1', 'soil': a.soil, 'state': a.state,
           'restore_mode': 'same_scene', 'wheel': wheels,
           'rr_geometry': {'in_fr_x': in_fr_x, 'in_fr_y': in_fr_y,
                           'bottom_to_platform_m': clearance},
           'rr_contacts': contacts, 'joints': joints,
           'roll_deg': round(float(np.degrees(roll)), 3),
           'pitch_deg': round(float(np.degrees(pitch)), 3),
           'tilt_deg': round(tilt_deg, 3),
           'com': [round(float(x), 4) for x in com],
           'base_z': round(float(d.qpos[2]), 4),
           'terminated': bool(env.terminated),
           'safe_exit': {'ok': safe, 'rows': len(rows),
                         'tilt_max': max((r['tilt'] for r in rows), default=None),
                         'vx_last': rows[-1]['vx'] if rows else None}}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'safe_exit': safe, 'rr': wheels['RR'],
                      'in_fr': [in_fr_x, in_fr_y], 'clearance': clearance,
                      'n_rr_contacts': len(contacts),
                      'roll': res['roll_deg'], 'pitch': res['pitch_deg']},
                     ensure_ascii=False))
    return 0 if safe else 1


if __name__ == '__main__':
    sys.exit(main())
