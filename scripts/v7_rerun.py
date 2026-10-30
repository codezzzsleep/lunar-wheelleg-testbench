"""
V7-R1 §16.1 模式②：用缓存资产**真实重新运行**一次仿真（不调用云端、不花积分）。

与回放的区别：回放只读已有记录；本脚本启动新的 MuJoCo episode，写新的 run_id 与日志。

  .venv/bin/python scripts/v7_rerun.py --case R03 --out runs/unseen/.../rerun_<id> \
      --hypothesis runs/.../processed/V7_R03_s2/collision --action R1 --seed 0
"""
import argparse, json, pathlib, sys, time, uuid

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain, wheelleg_env, runner, skills


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--hypothesis', required=True, help='碰撞目录（box union）')
    ap.add_argument('--action', default='R1')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--time-limit', type=float, default=30.0)
    ap.add_argument('--soil', default='rigid')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    run_id = time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6]
    out = ROOT / (a.out or f'runs/unseen/delivery_v7/v7_20261030_r1/evaluation/rerun_{run_id}')
    out.mkdir(parents=True, exist_ok=True)
    spec = terrain.make_spec(kind='flat', seed=a.seed, objects=[], goal_x=a.goal_x, name=a.case)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(ROOT / a.hypothesis)}]
    if a.soil != 'rigid':
        import v7_soil
        r = v7_soil.resolve(a.soil)
        spec['soil'] = {'mode': 'soil', 'label': r.get('label'), 'params': r['params']}
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=a.time_limit,
                                   v_ref=1.0, tip_deg=60.0)
    r = runner.EpisodeRunner(env, skills.make_skill(a.action), visible={}, seed=a.seed,
                             record_trajectory=True)
    started = time.time()
    o = r.run()
    traj = (o.get('trajectory') if isinstance(o, dict) else None) or \
           (getattr(r, 'trajectory', None) or [])
    rec = {'schema': 'rerun/v7-r1', 'mode': 'rerun_not_replay', 'run_id': run_id,
           'case': a.case, 'hypothesis': a.hypothesis, 'action': a.action,
           'seed': a.seed, 'soil': a.soil, 'started_at': started,
           'finished_at': time.time(), 'success': o['success'], 'reason': o['reason'],
           'final_x': o['final_x'], 't_end': o['t_end'], 'max_tilt': o['max_tilt'],
           'n_physics': int(env.n_physics), 'n_frames': len(traj),
           'note': '真实 MuJoCo 运行，不是回放；不调用云端、不产生生成费用'}
    (out / 'rerun.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    with (out / 'rerun_trajectory.jsonl').open('w') as f:
        for fr in traj:
            f.write(json.dumps(fr) + '\n')
    if not traj:
        raise SystemExit('轨迹为空：EpisodeRunner 未记录帧，拒绝声称已有回放数据')
    print(json.dumps({'run_id': run_id, 'success': rec['success'], 'reason': rec['reason'],
                      'out': str(out.relative_to(ROOT)) if out.is_relative_to(ROOT)
                      else str(out), 'n_frames': len(traj)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
