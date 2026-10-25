"""
第 1 关 · 第 4 项：脚本控制器让 Go2W 在平地上开出 5 m 不倒。

控制器刻意做得没有学习成分：
  · 腿：固定站姿 + PD 力矩保持（纯位置伺服）
  · 轮：轮速伺服（差速直行）
它同时也是计划书里的"考生 A（低姿态）"的雏形。
"""
import mujoco, numpy as np, pathlib, json, sys

MODEL = pathlib.Path('vendor/unitree_mujoco/unitree_robots/go2w/moon_flat.xml')
LEG = ['FR', 'FL', 'RR', 'RL']
STANCE = {'hip': 0.0, 'thigh': 0.85, 'calf': -1.65}   # 低姿态
STANCE_HIGH = {'hip': 0.0, 'thigh': 0.55, 'calf': -1.05}   # ride height 0.466 m  # 高姿态（考生 B）


def ids(m):
    d = {}
    for leg in LEG:
        for part in ('hip', 'thigh', 'calf', 'wheel'):
            jn = f'{leg}_{part}_joint'
            d[jn] = dict(
                qadr=m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)],
                vadr=m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)],
                act=mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_ACTUATOR, f'{leg}_{part}'),
            )
    return d


def run(stance, v_target=1.0, seconds=16.0, ramp_s=2.0, seed=0, verbose=True):
    m = mujoco.MjModel.from_xml_path(str(MODEL))
    d = mujoco.MjData(m)
    J = ids(m)
    rng = np.random.default_rng(seed)

    # start from a slightly raised stance and let it settle
    for leg in LEG:
        d.qpos[J[f'{leg}_hip_joint']['qadr']] = stance['hip']
        d.qpos[J[f'{leg}_thigh_joint']['qadr']] = stance['thigh']
        d.qpos[J[f'{leg}_calf_joint']['qadr']] = stance['calf']
    d.qpos[2] = 0.50   # must start above the target stance height or it drops in and tips
    mujoco.mj_forward(m, d)

    KP = {'hip': 150.0, 'thigh': 150.0, 'calf': 150.0}
    KD = {'hip': 5.0, 'thigh': 5.0, 'calf': 5.0}
    WHEEL_KP = 1.2
    # A torque step makes the body pitch up into a stable 60 deg wheelie. Ramping
    # the speed command over ~2 s keeps the reaction torque inside the stance
    # controller's authority (measured: 60 deg -> 1.4 deg).

    wheel_r = 0.086

    dt = m.opt.timestep
    n_steps = int(seconds / dt)
    start_xy = d.qpos[:2].copy()
    max_tilt = 0.0
    min_z = 9.9
    fell_at = None

    for i in range(n_steps):
        # ---- leg PD hold -------------------------------------------------
        for leg in LEG:
            for part in ('hip', 'thigh', 'calf'):
                e = J[f'{leg}_{part}_joint']
                q = d.qpos[e['qadr']]
                qd = d.qvel[e['vadr']]
                trq = KP[part] * (stance[part] - q) - KD[part] * qd
                d.ctrl[e['act']] = np.clip(trq, -45.0, 45.0)

        # ---- wheel velocity servo ---------------------------------------
        t = i * dt
        vt = v_target * min(1.0, t / ramp_s) if ramp_s > 0 else v_target
        omega_t = vt / wheel_r
        for leg in LEG:
            e = J[f'{leg}_wheel_joint']
            w = d.qvel[e['vadr']]
            d.ctrl[e['act']] = np.clip(WHEEL_KP * (omega_t - w), -15, 15)

        mujoco.mj_step(m, d)

        # ---- telemetry ---------------------------------------------------
        R = d.qpos[3:7]
        w, x, y, z = R[0], R[1], R[2], R[3]
        up_z = 1 - 2 * (x * x + y * y)          # body z-axis projected on world z
        tilt = np.degrees(np.arccos(np.clip(up_z, -1, 1)))
        max_tilt = max(max_tilt, tilt)
        min_z = min(min_z, d.qpos[2])
        if tilt > 75 and fell_at is None:
            fell_at = i * dt

    dist = float(np.linalg.norm(d.qpos[:2] - start_xy))
    out = {
        'stance': stance['thigh'],
        'distance_m': round(dist, 3),
        'final_z': round(float(d.qpos[2]), 3),
        'max_tilt_deg': round(float(max_tilt), 1),
        'min_body_z': round(float(min_z), 3),
        'fell_at_s': None if fell_at is None else round(fell_at, 2),
        'v_target': v_target,
        'passed_5m': dist >= 5.0 and (fell_at is None),
    }
    if verbose:
        print(json.dumps(out, indent=2))
    return out


if __name__ == '__main__':
    import json, time
    out_dir = pathlib.Path('runs'); out_dir.mkdir(exist_ok=True)
    results = {}
    for mode, stance in (('A_low', STANCE), ('B_high', STANCE_HIGH)):
        t0 = time.time()
        r = run(stance, v_target=1.0)
        r['wall_seconds'] = round(time.time() - t0, 2)
        results[mode] = r
        print(f"{mode:8s} dist={r['distance_m']:6.2f} m  maxTilt={r['max_tilt_deg']:5.1f} deg  "
              f"final_z={r['final_z']:.3f}  {'PASS' if r['passed_5m'] else 'FAIL'}")
    (out_dir / 'gate1_drive.json').write_text(json.dumps(results, indent=2))
    ok = all(r['passed_5m'] for r in results.values())
    print('GATE-1 ITEM 4:', 'PASS' if ok else 'FAIL')
