"""V1-A 短试验：站稳 → 单腿抬轮 → 保持 → 落轮，记录目标/实测/接触。

  python scripts/v3_v1_legtest.py --out runs/v3/control/legtest

断言（写入 JSON，不通过则退出码 1）：
  * 抬轮期间 FR 轮心相对机身抬高 >= 0.03 m；
  * 抬轮期间 FR 轮接触法向载荷降到 ~0（其余三轮仍承载）；
  * 落轮后 FR 轮重新接触、载荷恢复；
  * 关节跟踪误差 < 0.15 rad（除抬腿瞬态外）。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import terrain
import v3_record
import wheelleg_env

LEG = ('FR', 'FL', 'RR', 'RL')
STANCE = {'hip': 0.0, 'thigh': 0.85, 'calf': -1.65}


def stance_targets():
    return {leg: dict(STANCE) for leg in LEG}


def wheel_contact(env, leg):
    import mujoco
    m, d = env.model, env.data
    b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
    if b < 0:
        return 0.0
    total = 0.0
    for i in range(int(d.ncon)):
        c = d.contact[i]
        if m.geom_bodyid[c.geom1] == b or m.geom_bodyid[c.geom2] == b:
            f = np.zeros(6)
            mujoco.mj_contactForce(m, d, i, f)
            total += abs(float(f[0]))
    return total


def wheel_z(env, leg):
    import mujoco
    m = env.model
    b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
    return float(env.data.xpos[b][2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/control/legtest')
    ap.add_argument('--sweep', default='runs/v3/control/legsweep.json',
                    help='抬腿幅度来自实测扫描，不写死方向')
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=5.0, name='legtest')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=10.0)
    env.reset(seed=0)
    rec = v3_record.Recorder(out / 'record', {'scenario': 'legtest_flat', 'method': 'V1-A',
                                              'action': 'LIFT_FR'}, hz=50.0)
    phases = []

    def run_phase(name, seconds, targets):
        n = int(round(seconds * 50))
        z0 = {leg: wheel_z(env, leg) for leg in LEG}
        load = {leg: 0.0 for leg in LEG}
        err = []
        for k in range(n):
            env.step_command(joint_targets_rad=targets,
                             wheel_omega_rad_s=np.zeros(4), wheel_brake=np.ones(4))
            for leg in LEG:
                load[leg] += wheel_contact(env, leg)
            jt = env._last_joint_targets
            meas = np.array([[env.data.qpos[env.J[f'{leg}_{p}_joint']['qadr']]
                              for p in ('hip', 'thigh', 'calf')] for leg in LEG])
            err.append(np.abs(meas - jt))
            rec.add(v3_record.frame_from_env(env, None, np.zeros(3), k, env.t,
                                             extra={'skill_phase': name}))
        z1 = {leg: wheel_z(env, leg) for leg in LEG}
        m = {'phase': name, 'seconds': seconds,
             'wheel_z_before': {k: round(v, 4) for k, v in z0.items()},
             'wheel_z_after': {k: round(v, 4) for k, v in z1.items()},
             'mean_contact_load': {k: round(load[k] / max(1, n), 3) for k in LEG},
             'max_joint_track_err_rad': round(float(np.max(err)), 4) if err else None}
        phases.append(m)
        return m

    sweep_p = ROOT / a.sweep
    if not sweep_p.is_file():
        raise SystemExit(f'先跑 v3_v1_legsweep.py 得到抬腿幅度：{a.sweep}')
    sweep = json.loads(sweep_p.read_text())
    ok_rows = [r for r in (sweep.get('rows') or [])
               if r.get('dz_m', 0) >= 0.03 and r.get('fr_load', 1e9) < 5.0
               and r.get('other_load_min', 0) > 5.0 and r.get('tilt_deg', 99) < 9.0]
    # 选“抬得起来且姿态扰动最小”的格点，避免为了抬得高把另外三轮也带离地
    # 取“刚好能抬离地”的最小幅度：扰动最小，避免把整机压到一条腿上
    best = (min(ok_rows, key=lambda r: r['dz_m']) if ok_rows
            else (sweep.get('best') or [None])[0])
    if not best:
        raise SystemExit('扫描里没有满足条件的抬腿格点')
    dt, dc = float(best['d_thigh']), float(best['d_calf'])
    run_phase('stand', 0.8, stance_targets())
    lift = stance_targets()
    lift['FR'] = {'hip': 0.0, 'thigh': STANCE['thigh'] + dt, 'calf': STANCE['calf'] + dc}
    ph_lift = run_phase('lift_FR', 0.5, lift)
    ph_hold = run_phase('hold_FR', 0.4, lift)
    ph_down = run_phase('lower_FR', 0.8, stance_targets())
    ref = rec.close()
    base_z = phases[0]['wheel_z_after']['FR']
    lift_z = ph_hold['wheel_z_after']['FR']
    load_lift = ph_hold['mean_contact_load']['FR']
    load_down = ph_down['mean_contact_load']['FR']
    other = {k: ph_hold['mean_contact_load'][k] for k in ('FL', 'RR', 'RL')}
    checks = {
        'lift_height_m': round(lift_z - base_z, 4),
        'lift_height_ok': bool(lift_z - base_z >= 0.03),
        'fr_load_during_hold': load_lift,
        'fr_unloaded_ok': bool(load_lift < 5.0),
        'other_legs_loaded_ok': bool(min(other.values()) > 5.0),
        'fr_load_after_lower': load_down,
        'relower_ok': bool(load_down >= 5.0),
        'tracking_ok': bool(max(p.get('max_joint_track_err_rad') or 9
                                for p in phases) < 0.15),
    }
    ok = all(v for k, v in checks.items() if k.endswith('_ok'))
    res = {'schema': 'v3-v1-legtest/v1', 'env': 'flat', 'seed': 0,
           'lift_command_source': {'file': a.sweep, 'd_thigh': dt, 'd_calf': dc,
                                   'sweep_dz_m': best.get('dz_m')},
           'phases': phases, 'checks': checks, 'all_ok': ok,
           'trajectory_ref': ref,
           'command_contract': {'joint_targets_rad': '[4,3] rad (hip,thigh,calf)',
                                'wheel_omega_rad_s': '[4] rad/s',
                                'wheel_brake': '[4] 0/1'}}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'all_ok': ok, 'checks': checks, 'traj': ref.get('frame_count')},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
