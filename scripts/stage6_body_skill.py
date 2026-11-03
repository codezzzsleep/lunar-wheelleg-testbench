"""Stage006：BODY_CLEARANCE 技能（逐腿抬身 -> 轮式行驶 -> 降低 -> 稳定）。"""
import json
import pathlib
import sys

import numpy as np
import mujoco

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_basic_cycle as bc  # noqa: E402
import v3_record  # noqa: E402
import stage6_body as SB  # noqa: E402


def base_obstacle_contacts(env):
    m, d = env.model, env.data
    base = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    n = 0
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1 = int(m.geom_bodyid[c.geom1]); b2 = int(m.geom_bodyid[c.geom2])
        for a, b in ((b1, b2), (b2, b1)):
            if a != base:
                continue
            nm = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or ''
            if b != 0 and not any(k in nm for k in
                                  ('hip', 'thigh', 'calf', 'wheel', 'base')):
                n += 1
    return n


def run_body_clearance(env, plan, record_dir=None, meta=None, settle_steps=15):
    targets = {leg: dict(bc.STANCE) for leg in bc.LEG}
    rec = None
    if record_dir is not None:
        m = dict(meta or {}); m.update({'skill': 'BODY_CLEARANCE',
                                        'plan_id': plan.get('plan_id')})
        rec = v3_record.Recorder(record_dir, m, hz=50.0)
    k = 0; rows = []

    def step(phase):
        nonlocal k
        env.step_command(joint_targets_rad=targets, wheel_omega_rad_s=None,
                         wheel_mode='coast')
        if rec is not None:
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t))
        k += 1

    def step_drive(speed):
        nonlocal k
        env.step_command(joint_targets_rad=targets,
                         wheel_omega_rad_s=np.full(4, speed / 0.086),
                         wheel_mode='velocity')
        if rec is not None:
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t))
        k += 1

    for _ in range(settle_steps):
        step('settle')
    z0 = float(env.data.qpos[2]); c0 = SB.chassis_min_z(env)
    raise_z = float(plan.get('raise_z', 0.06))
    t2, r = SB.ramp(env, targets, int(plan.get('ramp_steps', 100)), raise_z)
    targets = t2
    z_raise = float(env.data.qpos[2]); c_raise = SB.chassis_min_z(env)
    speed = float(plan.get('speed', 0.15))
    lower_at = float(plan.get('lower_at_x', 2.0))
    t_limit = float(plan.get('time_limit', 60.0))
    contacts = 0; tilt_max = 0.0; x_end = float(env.data.qpos[0])
    while env.t < t_limit and not (env.terminated or env.truncated):
        step_drive(speed)
        contacts += base_obstacle_contacts(env)
        bid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
        tilt = float(np.degrees(np.arccos(np.clip(env.data.xmat[bid][8], -1, 1))))
        tilt_max = max(tilt_max, tilt)
        x_end = float(env.data.qpos[0])
        if tilt > float(plan.get('stop_tilt_deg', 12.0)):
            break
        if x_end >= lower_at:
            break
    t3, r = SB.ramp(env, targets, int(plan.get('ramp_steps', 100)), -raise_z)
    targets = t3
    for _ in range(settle_steps):
        step('recover')
    z_end = float(env.data.qpos[2])
    ref = rec.close() if rec is not None else None
    ok = bool(x_end >= float(plan.get('pass_x', lower_at)) and contacts == 0
              and tilt_max <= 10.0 and not env.terminated)
    row = {'action': 'BODY_CLEARANCE', 'ok': True, 'success': ok,
           'outcome': 'pass' if ok else ('physical_failure' if env.terminated else 'blocked'),
           'reason': 'success' if ok else ('terminated' if env.terminated else
                                           'chassis_contact' if contacts else 'not_reached'),
           'final_x': round(x_end, 4), 't_end': round(float(env.t), 3),
           'cost': round(float(env.t), 3), 'tilt_max': round(tilt_max, 3),
           'chassis_contacts': int(contacts), 'base_rise': round(z_raise - z0, 4),
           'clearance_gain': round(c_raise - c0, 4), 'plan_id': plan.get('plan_id'),
           'applicable': True}
    if ref:
        row['trajectory_ref'] = ref
    return row
