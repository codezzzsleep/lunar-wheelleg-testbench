"""A6 命令合同自检：子步 PD、轮三模式、终止、平滑目标、状态合同。

只做短核查（平地、刚体），不替代 B 包的抬轮验收：
  * 站姿跟踪：0.5 s 站姿，最大关节跟踪误差；
  * 每物理子步更新：10 个控制步 => n_physics +10*substeps、n_control +10；
  * 轮三模式：VELOCITY / BRAKE / COAST 的实际 ctrl 不同，COAST 力矩为 0；
  * 终止：max_seconds 到点后 truncated，且不再继续推进；
  * 状态合同：save -> 继续 0.2 s 与 save -> restore -> 继续 0.2 s 的 qpos 一致。

  .venv/bin/python scripts/v3_selftest_command.py --out runs/v3/selftest_command
"""
import argparse
import copy
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import terrain            # noqa: E402
import wheelleg_env       # noqa: E402

LEG = wheelleg_env.LEG
STANCE = {leg: dict(wheelleg_env.STANCE) for leg in LEG}


def make_env(max_seconds=10.0):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=5.0,
                             name='cmd_selftest')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=max_seconds)
    env.reset(seed=0)
    return env


def qpos_err(a, b):
    return float(np.max(np.abs(np.asarray(a) - np.asarray(b))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/selftest_command')
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    checks = {}

    # 1) 站姿跟踪 + 子步计数
    env = make_env()
    n0, c0, t0 = env.n_physics, env.n_control, env.t
    jt_max = 0.0
    for _ in range(25):                      # 0.5 s @ 50 Hz
        env.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
        jt = env._last_joint_targets
        meas = np.array([[env.data.qpos[env.J[f'{leg}_{p}_joint']['qadr']]
                          for p in ('hip', 'thigh', 'calf')] for leg in LEG])
        jt_max = max(jt_max, float(np.max(np.abs(meas - jt))))
    checks['stand_joint_err_rad'] = round(jt_max, 4)
    checks['stand_ok'] = bool(jt_max < 0.15)
    checks['substep_update'] = {
        'd_physics': env.n_physics - n0,
        'expected': 25 * env.substeps,
        'd_control': env.n_control - c0,
        'dt': round(env.t - t0, 6),
        'expected_dt': round(25 * env.substeps * env.dt, 6),
    }
    checks['substep_ok'] = bool(env.n_physics - n0 == 25 * env.substeps
                                and env.n_control - c0 == 25)

    # 2) 轮三模式
    we = env.J['FR_wheel_joint']['act']
    env.step_command(wheel_omega_rad_s=np.full(4, 1.0), wheel_mode='velocity')
    v = float(env.data.ctrl[we])
    env.step_command(wheel_mode='brake')
    b = float(env.data.ctrl[we])
    env.step_command(wheel_mode='coast')
    c = float(env.data.ctrl[we])
    checks['wheel_ctrl'] = {'velocity': round(v, 4), 'brake': round(b, 4),
                            'coast': round(c, 6)}
    checks['wheel_modes_ok'] = bool(abs(c) < 1e-12 and abs(v - b) > 1e-3)
    checks['wheel_mode_labels'] = dict(env._last_wheel_modes)

    # 3) 终止：到时不继续
    env_t = make_env(max_seconds=0.06)
    steps = 0
    for _ in range(50):
        env_t.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
        steps += 1
        if env_t.truncated or env_t.terminated:
            break
    checks['termination'] = {
        'truncated': bool(env_t.truncated),
        'reason': env_t.last_termination.get('reason'),
        'steps': steps,
        't': round(float(env_t.t), 3),
    }
    checks['termination_ok'] = bool(env_t.truncated and steps < 50)

    # 4) 状态合同：直接继续 vs 恢复继续
    env_a = make_env()
    for _ in range(10):
        env_a.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
    snap = copy.deepcopy(env_a.save_state())
    for _ in range(10):
        env_a.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
    q_direct = np.asarray(env_a.data.qpos, dtype=np.float64).copy()

    env_b = make_env()
    for _ in range(10):
        env_b.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
    env_b.restore_state(copy.deepcopy(snap))
    for _ in range(10):
        env_b.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
    q_restore = np.asarray(env_b.data.qpos, dtype=np.float64).copy()

    err = qpos_err(q_direct, q_restore)
    checks['restore'] = {'schema': snap['schema'], 'qpos_max_abs_diff': err,
                         'tol': 1e-9}
    checks['restore_ok'] = bool(err < 1e-9)

    ok = all(checks[k] for k in checks if k.endswith('_ok'))
    res = {'schema': 'v3-selftest-command/v1',
           'env': 'flat-rigid', 'substeps': env.substeps, 'dt': env.dt,
           'checks': checks, 'pass': bool(ok)}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'pass': res['pass'],
                      'stand_err': checks['stand_joint_err_rad'],
                      'substep_ok': checks['substep_ok'],
                      'wheel_modes_ok': checks['wheel_modes_ok'],
                      'termination_ok': checks['termination_ok'],
                      'restore_diff': checks['restore']['qpos_max_abs_diff']},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
