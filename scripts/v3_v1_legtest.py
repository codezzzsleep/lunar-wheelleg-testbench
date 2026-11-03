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


def body_roll(env):
    import math
    q = env.data.qpos[3:7]
    w, x, y, z = float(q[0]), float(q[1]), float(q[2]), float(q[3])
    return math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))


def stance_targets():
    return {leg: dict(STANCE) for leg in LEG}


def wheel_contact(env, leg):
    import mujoco
    m, d = env.model, env.data
    b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
    if b < 0:
        return 0.0
    ground = 0.0
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if b not in (b1, b2):
            continue
        other = b2 if b1 == b else b1
        if other not in (0, int(getattr(env, 'terrain_body_id', -1))):
            continue
        f = np.zeros(6)
        mujoco.mj_contactForce(m, d, i, f)
        ground += abs(float(f[0]))
    return ground


def wheel_z(env, leg):
    import mujoco
    m = env.model
    b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
    return float(env.data.xpos[b][2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/control/legtest')
    ap.add_argument('--roll-gain', type=float, default=0.0,
                    help='闭环支撑转移增益（按实测 roll 给支撑腿 hip 预压）')
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

    def run_phase(name, seconds, targets, ramp=0.25, brake=1.0, roll_gain=0.0):
        n = int(round(seconds * 50))
        n_ramp = max(1, int(round(ramp * 50)))
        q_now = {leg: {p: float(env.data.qpos[env.J[f'{leg}_{p}_joint']['qadr']])
                       for p in ('hip', 'thigh', 'calf')} for leg in LEG}
        z0 = {leg: wheel_z(env, leg) for leg in LEG}
        load = {leg: 0.0 for leg in LEG}
        err = []
        for k in range(n):
            a = min(1.0, (k + 1) / n_ramp)
            cmd = {leg: {p: q_now[leg][p] + a * (targets[leg][p] - q_now[leg][p])
                         for p in ('hip', 'thigh', 'calf')} for leg in LEG}
            if roll_gain:
                # 闭环支撑转移：按实测 roll 给支撑腿 hip 预压，抵消机身滚转
                r = body_roll(env)
                for leg in ('FL', 'RR', 'RL'):
                    cmd[leg]['hip'] = float(np.clip(cmd[leg]['hip'] - roll_gain * r, -1.0, 1.0))
            env.step_command(joint_targets_rad=cmd,
                             wheel_omega_rad_s=np.zeros(4),
                             wheel_brake=np.full(4, float(brake)))
            for leg in LEG:
                load[leg] += wheel_contact(env, leg)
            jt = env._last_joint_targets
            meas = np.array([[env.data.qpos[env.J[f'{leg}_{p}_joint']['qadr']]
                              for p in ('hip', 'thigh', 'calf')] for leg in LEG])
            err.append(np.abs(meas - jt))
            rec.add(v3_record.frame_from_env(env, None, np.zeros(3), k, env.t,
                                             extra={'skill_phase': name}))
            if float(env._tilt()) > 20.0:
                phases.append({'phase': name, 'aborted': 'tilt>20deg'})
                return {'phase': name, 'aborted': 'tilt_gt_20deg',
                        'tilt': round(float(env._tilt()), 2)}
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
    ok_rows = [r for r in ok_rows if r['dz_m'] <= 0.06] or ok_rows
    best = (min(ok_rows, key=lambda r: r['dz_m']) if ok_rows
            else (sweep.get('best') or [None])[0])
    if not best:
        raise SystemExit('扫描里没有满足条件的抬腿格点')
    dt, dc = float(best['d_thigh']), float(best['d_calf'])
    run_phase('stand', 0.8, stance_targets(), brake=1.0)
    lift = stance_targets()
    lift['FR'] = {'hip': 0.0, 'thigh': STANCE['thigh'] + dt, 'calf': STANCE['calf'] + dc}
    # 抬/保持/落全程不刹死轮子：让轮子能滚动来释放力矩，落轮才可能重新建立接触
    rg = float(a.roll_gain)
    ph_lift = run_phase('lift_FR', 0.8, lift, ramp=0.35, brake=0.0, roll_gain=0.0)
    ph_hold = run_phase('hold_FR', 0.4, lift, ramp=0.05, brake=0.0, roll_gain=0.0)
    # 两段式下落：先落一半并停 0.25 s 让接触建立，再落到底
    half = {leg: {pp: lift[leg][pp] + 0.5 * (stance_targets()[leg][pp] - lift[leg][pp])
                  for pp in ('hip', 'thigh', 'calf')} for leg in LEG}
    ph_down1 = run_phase('lower_half', 0.7, half, ramp=0.5, brake=0.0, roll_gain=rg)
    ph_down2 = run_phase('lower_settle', 0.25, half, ramp=0.05, brake=0.0, roll_gain=rg)
    ph_down = run_phase('lower_FR', 0.9, stance_targets(), ramp=0.7, brake=0.0, roll_gain=rg)
    ref = rec.close()
    aborted = [p for p in phases if 'aborted' in p]
    if aborted:
        res = {'schema': 'v3-v1-legtest/v1', 'env': 'flat', 'seed': 0,
               'phases': phases, 'aborted': aborted,
               'checks': {'aborted': True}, 'all_ok': False,
               'trajectory_ref': ref,
               'note': '终止检查触发：倾角过大，未完成抬轮-保持-落轮'}
        (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print(json.dumps({'all_ok': False, 'aborted': aborted[-1],
                          'traj': ref.get('frame_count')}, ensure_ascii=False))
        return 1
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
