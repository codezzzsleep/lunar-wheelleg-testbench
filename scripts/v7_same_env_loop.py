"""同一真值环境内完成：恢复观察结束状态 → 采集第二观察 → 直接继续 / 保存恢复后再继续。

对应任务书 §四：
  · 建环境与采集分离（capture_observation 接收已有 env，不 reset、不推进物理）；
  · 真值续行在同一实例内完成，不再"重建场景 → 签名不符 → 降级 project"；
  · §四.3 的直接继续 vs 保存恢复继续对照，逐帧比较首次偏差。

  MUJOCO_GL=osmesa /opt/lunar/bin/python scripts/v7_same_env_loop.py \
      --case cases/unseen_v1/R03.json --state runs/.../drive_R03_b/drive_observe.json \
      --action R1 --out runs/.../evaluation/same_env_R03
"""
import argparse, hashlib, json, pathlib, sys
import numpy as np
import mujoco

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import wheelleg_env, terrain, observe, skills, runner


def scene_sig(env):
    m = env.model
    h = hashlib.sha256()
    h.update(np.asarray(m.body_pos, dtype=np.float64).tobytes())
    h.update(np.asarray(m.geom_pos, dtype=np.float64).tobytes())
    h.update(np.asarray(m.geom_size, dtype=np.float64).tobytes())
    h.update(np.asarray(m.geom_friction, dtype=np.float64).tobytes())
    return h.hexdigest()


def snapshot(env):
    """完整状态：mjSTATE_INTEGRATION（qpos/qvel/act/time）+ warmstart + ctrl + env 字段。

    只存 qpos/qvel/time 时，恢复后的第一次接触求解与直接继续不同 —— 实测首帧就有 2.4e-4 m 偏差。
    """
    spec = mujoco.mjtState.mjSTATE_INTEGRATION
    n = mujoco.mj_stateSize(env.model, spec)
    buf = np.zeros(n, dtype=np.float64)
    mujoco.mj_getState(env.model, env.data, buf, spec)
    return {'mjstate': [float(x) for x in buf], 'mjstate_size': int(n),
            'qacc_warmstart': [float(x) for x in env.data.qacc_warmstart],
            'ctrl': [float(x) for x in env.data.ctrl],
            'act': [float(x) for x in env.data.act] if env.data.act is not None else [],
            'time': float(env.data.time),
            'nav_target_y': float(getattr(env, 'nav_target_y', 0.0)),
            'prev_action': str(getattr(env, 'prev_action', '')),
            'step_count': int(getattr(env, 'n_physics', 0))}


def restore(env, snap):
    """支持两种快照：完整的 mjstate（本脚本产出）与历史的 qpos/qvel（drive_observe 产出）。"""
    if 'mjstate' in snap:
        spec = mujoco.mjtState.mjSTATE_INTEGRATION
        mujoco.mj_setState(env.model, env.data, np.asarray(snap['mjstate'], dtype=np.float64), spec)
    else:
        env.data.qpos[:] = np.asarray(snap['qpos'], dtype=float)
        env.data.qvel[:] = np.asarray(snap['qvel'], dtype=float)
        if snap.get('time') is not None:
            env.data.time = float(snap['time'])
    if snap.get('qacc_warmstart'):
        env.data.qacc_warmstart[:] = np.asarray(snap['qacc_warmstart'], dtype=float)
    if snap.get('ctrl'):
        env.data.ctrl[:] = np.asarray(snap['ctrl'], dtype=float)
    if snap.get('act') and env.data.act is not None:
        env.data.act[:] = np.asarray(snap['act'], dtype=float)
    if hasattr(env, 'nav_target_y'):
        env.nav_target_y = float(snap.get('nav_target_y', env.nav_target_y))
    if hasattr(env, 'n_physics'):
        env.n_physics = int(snap.get('step_count', env.n_physics))
    mujoco.mj_forward(env.model, env.data)


def run_episode(env, action, seconds, limit_x=1e9):
    sk = skills.make_skill(action)
    frames, t0 = [], float(env.data.time)
    while float(env.data.time) - t0 < seconds:
        rs = env.robot_state()
        a = sk.act(None, rs)
        env.step(a)
        frames.append({'t': round(float(env.data.time), 4),
                       'qpos': [float(x) for x in env.data.qpos[:3]]})
        if float(env.data.qpos[0]) > limit_x:
            break
    return {'frames': frames, 'sim_s': round(float(env.data.time) - t0, 4),
            'final_x': round(float(env.data.qpos[0]), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--state', required=True)
    ap.add_argument('--state-seed', type=int, default=0)
    ap.add_argument('--action', default='R1')
    ap.add_argument('--observe-seconds', type=float, default=12.0)
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
    sig_before = scene_sig(env)

    dj = json.loads((ROOT / a.state).read_text())
    rec = next((r for r in dj.get('runs', []) if int(r.get('seed', -1)) == a.state_seed), None)
    if rec is None:
        raise SystemExit(f'{a.state} 里没有 seed {a.state_seed}')
    restore(env, rec['state_snapshot'])
    sig_at_state = scene_sig(env)
    if sig_at_state != sig_before:
        raise SystemExit('恢复状态后场景签名变化：拒绝在同场景语义下继续')

    t_obs0 = float(env.data.time)
    observe.capture_observation(env, out / 'obs_after_drive', obs_id=f'{case["case_id"]}_same_env')
    observation_seconds = float(env.data.time) - t_obs0
    snap = snapshot(env)
    (out / 'state_snapshot.json').write_text(json.dumps(snap, ensure_ascii=False, indent=2))

    remaining = max(1.0, a.budget_seconds - a.observe_seconds - observation_seconds)
    direct = run_episode(env, a.action, remaining)
    sig_after_direct = scene_sig(env)

    restore(env, snap)
    again = run_episode(env, a.action, remaining)
    sig_after_restore = scene_sig(env)

    n = min(len(direct['frames']), len(again['frames']))
    first_div = None
    for i in range(n):
        d0 = np.abs(np.subtract(direct['frames'][i]['qpos'], again['frames'][i]['qpos'])).max()
        if d0 > 1e-9:
            first_div = {'frame': i, 'max_abs_diff_m': float(d0),
                         't_direct': direct['frames'][i]['t'], 't_restore': again['frames'][i]['t']}
            break

    rep = {'schema': 'same-env-loop/v1', 'case': case['case_id'], 'action': a.action,
           'scene_sig_before': sig_before, 'scene_sig_at_state': sig_at_state,
           'scene_sig_after_direct': sig_after_direct, 'scene_sig_after_restore': sig_after_restore,
           'same_scene_holds': (sig_before == sig_at_state == sig_after_direct == sig_after_restore),
           'observation_seconds': round(observation_seconds, 4),
           'execution_seconds': remaining,
           'direct': {'sim_s': direct['sim_s'], 'final_x': direct['final_x'],
                      'frames': len(direct['frames'])},
           'save_restore': {'sim_s': again['sim_s'], 'final_x': again['final_x'],
                            'frames': len(again['frames'])},
           'first_divergence': first_div,
           'frames_compared': n}
    (out / 'same_env_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False))


if __name__ == '__main__':
    main()
