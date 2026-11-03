"""Stage006 BODY_CLEARANCE：单一逐控制步记录/安全检查入口（抬升-保持-行驶-降身-恢复）。"""
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


def tilt_deg(env):
    bid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    return float(np.degrees(np.arccos(np.clip(env.data.xmat[bid][8], -1, 1))))


def run_body_clearance(env, plan, record_dir=None, meta=None):
    """逐控制步：同一步内写 >=50Hz 帧 + 控制/阶段/接触 sidecar，步号连续。"""
    record_dir = pathlib.Path(record_dir) if record_dir else None
    rec = None; ctl = None
    if record_dir is not None:
        record_dir.mkdir(parents=True, exist_ok=True)
        m = dict(meta or {}); m.update({'skill': 'BODY_CLEARANCE',
                                        'plan_id': plan.get('plan_id')})
        rec = v3_record.Recorder(record_dir, m, hz=50.0)
        ctl = (record_dir / 'control.jsonl').open('w')
    targets = {leg: dict(bc.STANCE) for leg in bc.LEG}
    k = 0
    phase_rows = []
    chassis = 0; tilt_max = 0.0; fail_phase = None; termination = None
    phases = []

    def tick(phase, speed=None):
        nonlocal k, chassis, tilt_max, fail_phase, termination
        if speed is None:
            env.step_command(joint_targets_rad=targets, wheel_mode='coast')
        else:
            env.step_command(joint_targets_rad=targets,
                             wheel_omega_rad_s=np.full(4, float(speed) / 0.086),
                             wheel_mode='velocity')
        if rec is not None:
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t))
        c = base_obstacle_contacts(env)
        chassis += c
        tilt = tilt_deg(env)
        tilt_max = max(tilt_max, tilt)
        bad = bool(env.terminated or env.truncated or tilt > float(plan.get('stop_tilt_deg', 12.0)))
        if ctl is not None:
            ctl.write(json.dumps({'k': k, 't': round(float(env.t), 5), 'phase': phase,
                                  'x': round(float(env.data.qpos[0]), 5),
                                  'base_z': round(float(env.data.qpos[2]), 5),
                                  'tilt': round(tilt, 4), 'chassis_contacts': c,
                                  'targets': {leg: {p_: round(float(v), 5) for p_, v in targets[leg].items()}
                                              for leg in bc.LEG},
                                  'wheel_speed': speed, 'terminated': bool(env.terminated)}) + '\n')
        phase_rows.append({'k': k, 'phase': phase, 't': round(float(env.t), 4),
                           'x': round(float(env.data.qpos[0]), 4),
                           'base_z': round(float(env.data.qpos[2]), 4),
                           'tilt': round(tilt, 3), 'chassis_contacts': c})
        k += 1
        if bad and fail_phase is None:
            fail_phase = phase
            termination = dict(env.last_termination or {})
        return bad

    def mark(p):
        if not phases or phases[-1] != p:
            phases.append(p)

    # 站稳
    mark('settle')
    for _ in range(int(plan.get('settle_steps', 15))):
        if tick('settle'): break
    z0 = float(env.data.qpos[2]); c0 = SB.chassis_min_z(env)
    raise_z = float(plan.get('raise_z', 0.06)); steps = int(plan.get('ramp_steps', 100))
    # 抬升
    if fail_phase is None:
        mark('raise')
        for i in range(steps):
            targets = SB.leg_tick_targets(env, targets, raise_z / steps)
            if tick('raise'): break
    z_raise = float(env.data.qpos[2]); c_raise = SB.chassis_min_z(env)
    speed = float(plan.get('speed', 0.15)); end_x = float(plan.get('end_x', 2.6))
    lower_at = float(plan.get('lower_at_x', end_x))
    # 行驶到降身事件
    if fail_phase is None:
        mark('drive_to_lower')
        while float(env.data.qpos[0]) < lower_at:
            if tick('drive_to_lower', speed): break
    # 降身（仅未失败时）
    if fail_phase is None:
        mark('lower')
        for i in range(steps):
            targets = SB.leg_tick_targets(env, targets, -raise_z / steps)
            if tick('lower'): break
    # 继续到共同终点
    if fail_phase is None:
        mark('drive_to_end')
        while float(env.data.qpos[0]) < end_x:
            if tick('drive_to_end', speed): break
    # 稳定退出
    if fail_phase is None:
        mark('recover')
        for _ in range(int(plan.get('settle_steps', 15))):
            if tick('recover'): break
    x_end = float(env.data.qpos[0]); z_end = float(env.data.qpos[2])
    ref = rec.close() if rec is not None else None
    if ctl is not None:
        ctl.close()
    reached = bool(x_end >= end_x - 1e-3)
    tipped_or_stuck = bool(fail_phase is not None)
    stable = bool(tilt_deg(env) <= 10.0)
    safe_pass = bool(reached and chassis == 0 and not tipped_or_stuck and stable)
    phase_times = {}
    for r in phase_rows:
        phase_times.setdefault(r['phase'], [r['t'], r['t']])[1] = r['t']
    row = {'action': 'BODY_CLEARANCE', 'ok': True, 'success': safe_pass,
           'outcome': 'pass' if safe_pass else ('physical_failure' if tipped_or_stuck else
                                                'chassis_contact' if chassis else 'not_reached'),
           'reason': ('success' if safe_pass else
                      f'failed_at_{fail_phase}' if tipped_or_stuck else
                      'chassis_contact' if chassis else 'not_reached'),
           'reached': reached, 'chassis_contacts': int(chassis),
           'tipped_or_stuck': tipped_or_stuck, 'stable_exit': stable,
           'safe_pass': safe_pass, 'failed_phase': fail_phase,
           'termination': termination or {},
           'final_x': round(x_end, 4), 't_end': round(float(env.t), 3),
           'cost': round(float(env.t), 3), 'tilt_max': round(tilt_max, 3),
           'base_rise': round(z_raise - z0, 4), 'clearance_gain': round(c_raise - c0, 4),
           'end_x': end_x, 'lower_at_x': lower_at,
           'phase_times': {k2: [round(v[0], 3), round(v[1], 3)] for k2, v in phase_times.items()},
           'n_control_steps': k, 'plan_id': plan.get('plan_id'), 'applicable': True}
    if ref:
        row['trajectory_ref'] = ref
    if record_dir is not None:
        (record_dir / 'phases.json').write_text(json.dumps(
            {'phases': phases, 'phase_times': row['phase_times'],
             'failed_phase': fail_phase, 'n_steps': k}, ensure_ascii=False, indent=2))
    return row
