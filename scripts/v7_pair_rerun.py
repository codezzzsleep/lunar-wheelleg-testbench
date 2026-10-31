"""同一冻结起点下分别真实运行两个动作，证明它们各自执行（配对重跑）。

记录：新 run_id、**未取整** final_x / 起点 / 位移、逐帧位置与导航目标、动作、
执行器控制、终止条件与事件顺序。两次终点可以相同，不人为制造差异。

  /opt/lunar/bin/python scripts/v7_pair_rerun.py --collision <dir> --actions R1,D1 --out <dir>
"""
import argparse, hashlib, json, pathlib, sys, uuid
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np
import eval_six, runner, skills


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--collision', required=True)
    ap.add_argument('--actions', default='R1,D1')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--seconds', type=float, default=30.0)
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = ROOT / a.out; out.mkdir(parents=True, exist_ok=True)
    recs = []
    for act in a.actions.split(','):
        env = eval_six.build_env(ROOT / a.collision, a.goal_x, a.seconds, a.soil, a.seed)
        env.reset(seed=a.seed)
        q0 = np.asarray(env.data.qpos, dtype=np.float64).copy()
        r = runner.EpisodeRunner(env, skills.make_skill(act), visible={}, seed=a.seed,
                                 record_trajectory=True)
        o = r.run()
        frames = r.trajectory or []
        rid = uuid.uuid4().hex[:16]
        rec = {'run_id': rid, 'action': act, 'seed': a.seed,
               'collision': a.collision,
               'start_x_unrounded': float(q0[0]),
               'final_x_unrounded': float(env.data.qpos[0]),
               'displacement_x_unrounded': float(env.data.qpos[0] - q0[0]),
               'final_x_rounded': o.get('final_x'),
               'success': o.get('success'), 'reason': o.get('reason'),
               't_end': o.get('t_end'), 'control_steps': o.get('steps'),
               'action_fingerprint': o.get('action_fingerprint'),
               'initial_full_hash': o.get('initial_full_hash'),
               'max_tilt': o.get('max_tilt'),
               'nav_target_trace': [float(getattr(env, 'nav_target_y', 0.0))],
               'frames': len(frames),
               'trajectory_head': frames[:3], 'trajectory_tail': frames[-3:],
               'termination': {'reason': o.get('reason'), 'phases': o.get('phases')}}
        (out / f'{act}_{rid}.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        recs.append(rec)
        print(json.dumps({k: rec[k] for k in ('action','run_id','start_x_unrounded',
                                              'final_x_unrounded','displacement_x_unrounded',
                                              'success','reason','control_steps',
                                              'action_fingerprint')}, ensure_ascii=False), flush=True)
    same = (recs[0]['final_x_unrounded'] == recs[1]['final_x_unrounded']) if len(recs) > 1 else None
    (out / 'pair_summary.json').write_text(json.dumps(
        {'n': len(recs), 'final_x_equal': same,
         'distinct_run_ids': len({r['run_id'] for r in recs}) == len(recs),
         'distinct_fingerprints': len({r['action_fingerprint'] for r in recs}) == len(recs),
         'records': [{k: r[k] for k in ('action','run_id','final_x_unrounded',
                                        'displacement_x_unrounded','success','reason')} for r in recs]},
        ensure_ascii=False, indent=2))
    print(json.dumps({'final_x_equal': same, 'n': len(recs)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
