"""同一真值环境内：驾驶 → 停稳 → 采集 → 续行，并做"直接 vs 保存恢复"逐层对照。

任务书 §一要求：
  · 不再维护自写快照，统一用 env.save_state() / env.restore_state(mode='same_scene')；
  · 不再自写 run_episode，统一用 EpisodeRunner（新增 run_current()，不 reset、不重恢复）；
  · 先比**一个控制步**，逐层记录差异，前一层已不同就先修那一层。

  MUJOCO_GL=osmesa /opt/lunar/bin/python scripts/v7_same_env_loop.py \
      --case cases/unseen_v1/R03.json --action R1 --out <dir>
"""
import argparse, json, pathlib, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import wheelleg_env, terrain, observe, skills, runner


def env_state(env):
    """逐层对照用的环境状态摘要（不含 MuJoCo 内部缓存）。"""
    return {'qpos': [round(float(x), 9) for x in env.data.qpos],
            'qvel': [round(float(x), 9) for x in env.data.qvel],
            'ctrl': [round(float(x), 9) for x in env.data.ctrl],
            'data_time': round(float(env.data.time), 9),
            'env_t': round(float(getattr(env, 't', -1.0)), 9),
            'n_physics': int(getattr(env, 'n_physics', -1)),
            'nav_target_y': round(float(getattr(env, 'nav_target_y', 0.0)), 9),
            'prev_action': str(getattr(env, 'prev_action', '')),
            'soil': getattr(env, 'soil_state', None) if isinstance(
                getattr(env, 'soil_state', None), (int, float)) else None}


def diff(a, b, path=''):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += diff(a.get(k), b.get(k), f'{path}.{k}' if path else k)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f'{path}[{i}]')
        return out
    if isinstance(a, float) and isinstance(b, float):
        if abs(a - b) > 0:
            out.append({'field': path, 'a': a, 'b': b, 'abs_diff': abs(a - b)})
        return out
    if a != b:
        out.append({'field': path, 'a': a, 'b': b})
    return out


def one_control_step(env, action_name, obs=None):
    """跑一个控制步，记录 5 个阶段的量。"""
    sk = skills.make_skill(action_name)
    s0 = env_state(env)
    rs = env.robot_state()
    a = np.asarray(sk.act(obs, rs), dtype=float).reshape(-1)
    s_action = [round(float(x), 9) for x in a]
    env.step(a)
    return {'before': s0, 'action': s_action, 'after': env_state(env)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--action', default='R1')
    ap.add_argument('--drive-target-y', type=float, default=0.42,
                    help='驾驶到的横向目标（米）')
    ap.add_argument('--drive-stop-x', type=float, default=0.55)
    ap.add_argument('--drive-max-s', type=float, default=8.0)
    ap.add_argument('--drive-speed', type=float, default=0.10)
    ap.add_argument('--state-seed', type=int, default=0)
    ap.add_argument('--budget-seconds', type=float, default=30.0)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    case = json.loads((ROOT / a.case).read_text())
    out = ROOT / a.out; out.mkdir(parents=True, exist_ok=True)

    spec = terrain.make_spec(kind='flat', seed=case.get('seed', 0), objects=[],
                             goal_x=case.get('goal_x', 3.0), name=case['case_id'])
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['objects'] = [{'mesh_file': case['mesh'], 'x': case['obstacle_x'], 'y': 0.0,
                        'yaw_deg': float(case.get('yaw_deg', 0.0)),
                        'target_height_m': case['H']}]
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}

    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)

    import drive_observe as DO
    t_drive0 = float(env.t)
    # 正式流程：**真实驾驶 + 停稳**，不再导入历史 qpos/qvel 充当续行起点
    DO.drive_to_nav(env, float(a.drive_target_y), stop_x=float(a.drive_stop_x),
                    max_s=float(a.drive_max_s), v=float(a.drive_speed))
    _st = DO.brake_and_settle(env)
    settled = bool(_st.get('stable'))
    settle_s = float(_st.get('settle_s', _st.get('seconds', 0.0)))
    drive_seconds = float(env.t) - t_drive0

    t_obs0 = float(env.t)
    rec_state = env.save_state()
    observe.capture_observation(env, out / 'obs_after_drive', obs_id=f'{case["case_id"]}_same_env')
    observation_seconds = float(env.t) - t_obs0
    rec_state = env.save_state()          # 采集之后再存一次（采集可能改模型/相机）
    (out / 'state_snapshot.json').write_text(json.dumps(rec_state, ensure_ascii=False, indent=2))

    remaining = max(1.0, a.budget_seconds - observation_seconds)
    runner_kw = dict(visible={}, seed=a.state_seed, record_trajectory=True)

    # 分支 A：直接继续
    rA = runner.EpisodeRunner(env, skills.make_skill(a.action), **runner_kw)
    resA = rA.run_current()

    # 分支 B：恢复后续行
    env.restore_state(rec_state, mode='same_scene')
    rB = runner.EpisodeRunner(env, skills.make_skill(a.action), **runner_kw)
    resB = rB.run_current()

    trA = rA.trajectory or []
    trB = rB.trajectory or []
    n = min(len(trA), len(trB))
    first = None
    for i in range(n):
        d = np.abs(np.subtract(trA[i]['qpos'], trB[i]['qpos'])).max()
        if d > 0:
            first = {'frame': i, 'max_abs_diff_m': float(d),
                     't_a': trA[i].get('t'), 't_b': trB[i].get('t')}
            break

    # 单控制步逐层对照（两个分支各自从同一快照开始）
    env.restore_state(rec_state, mode='same_scene')
    stepA = one_control_step(env, a.action)
    env.restore_state(rec_state, mode='same_scene')
    stepB = one_control_step(env, a.action)
    stage_diffs = {'before': diff(stepA['before'], stepB['before']) if False else [],
                   'action': [] if stepA['action'] == stepB['action'] else
                             [{'field': 'action', 'a': stepA['action'], 'b': stepB['action']}],
                   'after': diff(stepA['after'], stepB['after'])}

    rep = {'schema': 'same-env-loop/v2', 'case': case['case_id'], 'action': a.action,
           'drive_seconds': round(drive_seconds, 4), 'settled': bool(settled),
           'settle_seconds': round(float(settle_s), 4),
           'observation_seconds': round(observation_seconds, 4),
           'execution_budget_s': round(remaining, 4),
           'state_hash': rec_state.get('state_hash'),
           'direct': {'success': resA.get('success'), 'reason': resA.get('reason'),
                      'final_x': resA.get('final_x'), 'displacement_x': resA.get('displacement_x'),
                      'frames': len(trA)},
           'save_restore': {'success': resB.get('success'), 'reason': resB.get('reason'),
                            'final_x': resB.get('final_x'), 'displacement_x': resB.get('displacement_x'),
                            'frames': len(trB)},
           'first_divergence': first, 'frames_compared': n,
           'one_control_step': {'action_identical': stepA['action'] == stepB['action'],
                                'after_diff': stage_diffs['after'][:8]}}
    (out / 'same_env_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({k: rep[k] for k in ('observation_seconds', 'direct', 'save_restore',
                                          'first_divergence', 'one_control_step')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
