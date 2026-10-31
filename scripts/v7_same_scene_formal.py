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

    DO.drive_to_nav(env, a.drive_target_y, stop_x=a.drive_stop_x, max_s=8.0, v=0.10)
    _st = DO.brake_and_settle(env)
    drive_seconds = float(env.t)
    observe.capture_observation(env, out / 'obs_after_drive',
                                obs_id=f'{case["case_id"]}_same_scene')
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
    drive_json = out / 'drive_for_rehearsal.json'
    # 闭环的 --drive 需要 env_state/stable 等字段（drive_observe 的产物结构）
    drive_json.write_text(json.dumps({'runs': [{
        'seed': 0, 'stable': True, 'env_state': snap, 'state_snapshot': snap,
        'cam_baseline_m': 0.5, 'bearing_change_deg': 10.0}]}, ensure_ascii=False))
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
