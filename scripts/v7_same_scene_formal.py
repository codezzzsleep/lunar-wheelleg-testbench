"""正式 same_scene 闭环：在**同一个真值环境实例**里完成
驾驶 → 停稳 → 采集 → 候选预演(project) → 决策落盘 → 原环境续行。

- 预演走独立环境（显式 project），真值续行用原实例 run_current()，**不自动降级**；
- 总预算从协议传入环境，驾驶/停稳/执行共用真实时钟，剩余 = 总预算 − 已消耗 env.t；
- 决策先落盘（含 decision_sha），再执行。

  MUJOCO_GL=osmesa /opt/lunar/bin/python scripts/v7_same_scene_formal.py \
      --case cases/unseen_v1/R03.json --hypotheses <json> --out <dir>
"""
import argparse, json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np
import terrain, wheelleg_env, observe, skills, runner, drive_observe as DO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--hypotheses', required=True)
    ap.add_argument('--budget', type=float, default=30.0)
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--soils', default='nominal,low_traction,high_drag')
    ap.add_argument('--actions', default=None)
    ap.add_argument('--drive-mode', choices=['nav', 'arc'], default='arc',
                    help='nav=侧向导航驾驶；arc=前进+偏航弧线（真实改变视角）')
    ap.add_argument('--arc-v', type=float, default=0.12)
    ap.add_argument('--arc-w', type=float, default=-0.20)
    ap.add_argument('--arc-seconds', type=float, default=6.0)
    ap.add_argument('--drive-target-y', type=float, default=0.42)
    ap.add_argument('--drive-stop-x', type=float, default=0.55)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    case = json.loads((ROOT / a.case).read_text())
    out = ROOT / a.out; out.mkdir(parents=True, exist_ok=True)

    spec = terrain.make_spec(kind='flat', seed=case.get('seed', 0), objects=[],
                             goal_x=a.goal_x, name=case['case_id'])
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['objects'] = [{'mesh_file': case['mesh'], 'x': case['obstacle_x'], 'y': 0.0,
                        'yaw_deg': float(case.get('yaw_deg', 0.0)),
                        'target_height_m': case['H']}]
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=a.budget)
    env.reset(seed=0)

    # 3.1：驾驶前后都记录相机世界位姿与机器人状态，观察条件全部来自实测
    import mujoco as _mj
    cam_id = observe.cam_id_of(env)
    _mj.mj_forward(env.model, env.data)
    cam0 = np.array(env.data.cam_xpos[cam_id], dtype=float).copy()
    q0 = np.array(env.data.qpos, dtype=float).copy()
    t_drive0 = float(env.t)
    if a.drive_mode == 'arc':
        _t_arc = float(env.t)
        while float(env.t) - _t_arc < a.arc_seconds:
            env.step_drive(a.arc_v, a.arc_w)
    else:
        DO.drive_to_nav(env, a.drive_target_y, stop_x=a.drive_stop_x, max_s=8.0, v=0.10)
    _st = DO.brake_and_settle(env, max_s=6.0)
    if not _st.get('stable'):
        # 弧线驾驶结束后可能仍有残余速度/转动：显式零指令再保持一段
        _t_hold = float(env.t)
        while float(env.t) - _t_hold < 0.8:
            env.step_drive(0.0, 0.0)
        _st = DO.brake_and_settle(env, max_s=3.0)
    drive_seconds = float(env.t) - t_drive0
    _mj.mj_forward(env.model, env.data)
    cam1 = np.array(env.data.cam_xpos[cam_id], dtype=float).copy()
    cam_baseline = float(np.linalg.norm(cam1 - cam0))
    obs_pos = np.array([float(case['obstacle_x']), 0.0, float(case['H']) / 2.0])
    v0, v1 = obs_pos - cam0, obs_pos - cam1
    cosang = float(np.dot(v0, v1) / max(1e-9, np.linalg.norm(v0) * np.linalg.norm(v1)))
    bearing_change_deg = float(np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0))))
    stable = bool(_st.get('stable'))
    settle_hold_s = float(_st.get('hold_s', _st.get('seconds', 0.0)) or 0.0)
    try:
        observe.capture_observation(env, out / 'obs_after_drive',
                                    obs_id=f'{case["case_id"]}_same_scene')
    except Exception as _e:
        # 目标不在视野内时裁剪会失败：这是**观察不成立**，不是程序崩溃
        rep = {'schema': 'same-scene-formal/v1', 'case': case['case_id'],
               'budget_s': a.budget, 'drive_seconds': round(drive_seconds, 4),
               'decision': {'chosen': 'A0', 'reason': 'observation_capture_failed',
                            'error': f'{type(_e).__name__}: {_e}'},
               'execution': {'success': False, 'reason': 'observation_capture_failed',
                             'executed': False, 'fallback': True},
               'candidates': 'not_evaluated'}
        (out / 'same_scene_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(json.dumps(rep, ensure_ascii=False))
        return
    # 观察质量：像素数、有效深度比例、速度、角速度、倾角
    _depth = np.load(out / 'obs_after_drive' / 'depth.npy')
    valid_frac = float(np.isfinite(_depth).mean())
    _obsj = json.loads((out / 'obs_after_drive' / 'observation.json').read_text())
    _v = (_obsj.get('visible') or {})
    mask_px = int(_obsj.get('mask_px') or _v.get('mask_px') or _v.get('n_pixels') or 0)
    speed = float(np.linalg.norm(np.asarray(env.data.qvel[:3])))
    omega = float(np.linalg.norm(np.asarray(env.data.qvel[3:6])))
    tilt = float(env._tilt())
    OBS_CRIT = {'stable': True, 'min_baseline_m': 0.20, 'min_bearing_deg': 5.0,
                'min_mask_px': 500, 'min_valid_depth_frac': 0.5,
                'max_speed': 0.05, 'max_omega': 0.5, 'max_tilt_deg': 5.0}
    reasons = []
    if not stable: reasons.append('not_stable')
    if cam_baseline < OBS_CRIT['min_baseline_m']: reasons.append('baseline_too_small')
    if bearing_change_deg < OBS_CRIT['min_bearing_deg']: reasons.append('bearing_change_too_small')
    if mask_px < OBS_CRIT['min_mask_px']: reasons.append('target_too_small')
    if valid_frac < OBS_CRIT['min_valid_depth_frac']: reasons.append('depth_invalid')
    if speed > OBS_CRIT['max_speed']: reasons.append('still_moving')
    if omega > OBS_CRIT['max_omega']: reasons.append('still_rotating')
    if tilt > OBS_CRIT['max_tilt_deg']: reasons.append('tilted')
    observation = {'stable': stable, 'settle_hold_s': settle_hold_s,
                   'cam_baseline_m': round(cam_baseline, 4),
                   'bearing_change_deg': round(bearing_change_deg, 3),
                   'mask_px': mask_px, 'valid_depth_frac': round(valid_frac, 4),
                   'speed_mps': round(speed, 4), 'omega_rps': round(omega, 4),
                   'tilt_deg': round(tilt, 3), 'criteria': OBS_CRIT,
                   'usable': not reasons, 'reasons': reasons}
    snap = env.save_state()
    (out / 'state_snapshot.json').write_text(json.dumps(snap, ensure_ascii=False, indent=2))
    remaining = max(1.0, a.budget - float(env.t))

    # 预演需要的是**公开可见量**（x_front/W_vis/H_vis），不是整份观测
    vis_out = out / 'visible_public.json'
    vr = subprocess.run([sys.executable, str(ROOT / 'scripts/v7_visible_public.py'),
                         '--observation', str(out / 'obs_after_drive'), '--out', str(vis_out)],
                        cwd=str(ROOT), capture_output=True, text=True)
    if vr.returncode != 0:
        raise SystemExit(f'可见量导出失败：{vr.stderr.strip().splitlines()[-2:]}')
    if not observation['usable']:
        # 观察不合格：不进筛选/更新，候选标 not_evaluated，走安全回退并记录原因
        rep = {'schema': 'same-scene-formal/v1', 'case': case['case_id'],
               'observation_acceptance': observation, 'budget_s': a.budget,
               'drive_seconds': round(drive_seconds, 4), 'observation_seconds': 0.0,
               'decision': {'chosen': 'A0', 'reason': 'observation_not_usable',
                            'reasons': observation['reasons']},
               'execution': {'success': False, 'reason': 'observation_not_usable',
                             'state_mode': 'same_scene', 'fallback': True,
                             'executed': False},
               'candidates': 'not_evaluated'}
        (out / 'same_scene_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(json.dumps(rep, ensure_ascii=False))
        return

    drive_json = out / 'drive_for_rehearsal.json'
    # 闭环的 --drive 需要 env_state/stable 等字段（drive_observe 的产物结构）
    drive_json.write_text(json.dumps({'runs': [{
        'seed': 0, 'stable': True, 'env_state': snap, 'state_snapshot': snap,
        'cam_baseline_m': observation['cam_baseline_m'],
        'bearing_change_deg': observation['bearing_change_deg']}]}, ensure_ascii=False))
    cli = [sys.executable, str(ROOT / 'scripts/v7_closed_loop.py'),
           '--drive', str(drive_json.relative_to(ROOT)),
           '--hypotheses', a.hypotheses,
           '--visible-json', str(vis_out.relative_to(ROOT)),
           '--soil-configs', a.soils, '--no-truth',
           '--goal-x', str(a.goal_x), '--time-limit', str(a.budget),
           '--out', str((out / 'rehearsal').relative_to(ROOT))]
    if a.actions:
        cli[cli.index('--soil-configs'):cli.index('--soil-configs')] = ['--actions', a.actions]
    r = subprocess.run(cli, cwd=str(ROOT), capture_output=True, text=True)
    (out / 'rehearsal.log').write_text((r.stdout or '') + (r.stderr or ''))
    if r.returncode != 0:
        raise SystemExit(f'预演/决策失败：{(r.stderr or "").strip().splitlines()[-3:]}')
    dec = json.loads((out / 'rehearsal' / 'decisions.json').read_text())
    chosen = dec['decision']['chosen']

    env.restore_state(snap, mode='same_scene')
    # 3.4：执行前立即记录时钟/位置/身份；3.2：执行与预演用同一份公开可见量
    vis_exec = json.loads(vis_out.read_text())
    exec_start = {'env_t': float(env.t), 'data_time': float(env.data.time),
                  'x': float(env.data.qpos[0]), 'state_hash': snap.get('state_hash')}
    res = runner.EpisodeRunner(env, skills.make_skill(chosen), visible=vis_exec, seed=0,
                               record_trajectory=True).run_current()
    exec_end = {'env_t': float(env.t), 'data_time': float(env.data.time),
                'x': float(env.data.qpos[0])}
    frames = res.get('trajectory') or []
    rep = {'schema': 'same-scene-formal/v1', 'case': case['case_id'],
           'observation_acceptance': observation,
           'budget_s': a.budget, 'drive_seconds': round(drive_seconds, 4),
           'observation_seconds': 0.0,
           'remaining_before_exec_s': round(remaining, 4),
           'env_t_before_exec': round(exec_start['env_t'], 4),
           'decision': {'chosen': chosen, 'safe_set': dec['decision'].get('safe_set'),
                        'decision_sha': dec.get('decision_sha'),
                        'cells': sum(1 for _ in (out / 'rehearsal' / 'matrix.jsonl')
                                       .read_text().splitlines())},
           'execution_start': exec_start, 'execution_end': exec_end,
           'execution': {'success': res.get('success'), 'reason': res.get('reason'),
                         'final_x': round(exec_end['x'], 6),
                         'displacement_x': round(exec_end['x'] - exec_start['x'], 6),
                         'control_steps': res.get('steps'), 'frames': len(frames),
                         'state_mode': 'same_scene', 'fallback': False}}
    (out / 'same_scene_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False))


if __name__ == '__main__':
    main()
