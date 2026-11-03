"""Stage006 BODY_CLEARANCE：逐腿三关节抬升/恢复与净空测量。"""
import numpy as np
import mujoco

import v3_basic_cycle as bc
import v3_climb as VC


def chassis_min_z(env):
    """底盘（base_link 本体）最低点；腿/轮的下移不算底盘净空。"""
    m, d = env.model, env.data
    zmin = 1e9
    base_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    for g in range(m.ngeom):
        if int(m.geom_bodyid[g]) != base_id:
            continue
        R = np.asarray(d.geom_xmat[g]).reshape(3, 3)
        half = np.asarray(m.geom_aabb[g][3:], dtype=float)
        ext = float(np.abs(R[2, :]) @ half)
        z = float(d.geom_xpos[g][2]) - ext
        zmin = min(zmin, z)
    return zmin


def leg_tick_targets(env, targets, dz_step, clamp=0.02):
    """轮子相对机身下移 dz_step -> 机身抬高（轮子保持落地）。"""
    out = {k: dict(v) for k, v in targets.items()}
    for leg in bc.LEG:
        dp = np.array([0.0, 0.0, -float(dz_step)])
        dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), dp), -clamp, clamp)
        for p_, v in zip(('hip', 'thigh', 'calf'), dq):
            lo, hi = VC.jlim(env, leg, p_)
            out[leg][p_] = float(np.clip(out[leg][p_] + float(v), lo, hi))
    return out


def ramp(env, targets_start, steps, dz_total, rec=None, k0=0, phase='ramp'):
    targets = {k: dict(v) for k, v in targets_start.items()}
    dz_step = dz_total / steps
    rows = []
    for i in range(steps):
        targets = leg_tick_targets(env, targets, dz_step)
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
        rows.append(snapshot(env, targets, phase, k0 + i))
        if env.terminated or env.truncated:
            break
    return targets, rows


def hold(env, targets, steps, phase, k0):
    rows = []
    for i in range(steps):
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
        rows.append(snapshot(env, targets, phase, k0 + i))
        if env.terminated or env.truncated:
            break
    return rows


def snapshot(env, targets, phase, k):
    d = env.data
    tilt = float(np.degrees(np.arccos(np.clip(d.xmat[mujoco.mj_name2id(
        env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')][8], -1, 1))))
    loads = {leg: float(VC.contact_load(env, leg)) for leg in bc.LEG}
    joints = {}
    for leg in bc.LEG:
        for p_ in ('hip', 'thigh', 'calf'):
            j = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_JOINT, f'{leg}_{p_}_joint')
            q = float(d.qpos[env.model.jnt_qposadr[j]])
            lo, hi = (float(x) for x in env.model.jnt_range[j])
            joints[f'{leg}_{p_}'] = {'q': round(q, 4), 'target': round(targets[leg][p_], 4),
                                     'margin_lo': round(q - lo, 4), 'margin_hi': round(hi - q, 4)}
    tor = np.asarray(d.actuator_force, float)
    return {'k': k, 't': round(float(env.t), 4), 'phase': phase,
            'base_z': round(float(d.qpos[2]), 5), 'tilt': round(tilt, 3),
            'loads': loads, 'chassis_min_z': round(chassis_min_z(env), 5),
            'joints': joints, 'tau_max': round(float(np.max(np.abs(tor))), 3)}
