"""2.5D 两策略在同一真实状态上的规划与执行（下一批任务书 §5）。

  python scripts/v7_elev25d_eval.py --config R02_s0.9 --soil nominal --seed 7 --out <dir>
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import common_planner as CP
import runner
import skills
import v7_common_matrix as MX

BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out_root = ROOT / a.out if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    out_root.mkdir(parents=True, exist_ok=True)
    plan = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
    cfg = next(c for c in plan['configs'] if c['config_id'] == a.config)
    unit = ROOT / BATCH / 'common_states' / a.config / a.soil / f'seed{a.seed}'
    acq = json.loads((unit / 'acquisition.json').read_text())
    snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
    vis = acq.get('visible') or {}
    goal_x = json.loads((ROOT / cfg['case_config']).read_text())['goal_x']
    elev = json.loads((ROOT / BATCH / 'elev25d' / a.config / 'elev25d.json').read_text())
    rec = {'schema': 'elev25d-eval/v1', 'config': a.config, 'soil': a.soil,
           'seed': a.seed, 'state_hash': snap.get('state_hash'),
           'observation': acq.get('observation'), 'visible': vis,
           'elevation': {'unknown_frac': elev['unknown_frac'],
                         'observed_cells': elev['observed_cells']},
           'arms': {}}
    for strat in ('block', 'fill'):
        tag = strat
        d = out_root / strat
        d.mkdir(parents=True, exist_ok=True)
        asset = f"{BATCH}/elev25d/{a.config}/{strat}"
        hyps = [{'id': tag, 'kind': 'elev25d', 'collision_dir': asset}]
        p = CP.plan_action(hyps, snap, vis, [a.soil], float(cfg.get('budget_s', 30.0)),
                           (lambda h, s: MX.build_env(cfg, s, collision_dir=asset)),
                           goal_x=goal_x, seed=a.seed)
        CP.write_plan(p, d)
        act = p['decision']['chosen']
        (d / 'decision.json').write_text(json.dumps(
            {'strategy': strat, 'family': f'E25D_{strat}',
             'chosen': act, 'decision': p['decision'],
             'visible': vis}, ensure_ascii=False, indent=2))
        env = MX.build_env(cfg, a.soil, collision_dir=MX.truth_collision_for(cfg))
        env.reset(seed=a.seed)
        env.restore_state(snap, mode='same_scene')
        r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=a.seed,
                                 record_trajectory=True).run_current()
        frames = r.get('trajectory') or []
        if frames:
            (d / 'trajectory.jsonl').write_text(
                '\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
        rec['arms'][tag] = {'chosen': act, 'cells': p['counts']['rows'],
                            'safe_set': p['decision'].get('safe_set'),
                            'success': bool(r.get('success')), 'reason': r.get('reason'),
                            'final_x': r.get('final_x'),
                            'sim_time_s': round(float(env.t), 4),
                            'frames': len(frames)}
        print(json.dumps({'arm': tag, 'chosen': act,
                          'outcome': rec['arms'][tag]['success']}, ensure_ascii=False))
    (out_root / 'eval.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: {'chosen': v['chosen'], 'success': v['success']}
                      for k, v in rec['arms'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
