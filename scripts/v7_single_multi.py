"""单候选 / 多候选对照（下一批任务书 §7.3）。

同一状态、同一预算、同一共同规划器，只改假设集合：
  fixed_first   只用约定首候选
  single_average 各单候选分别决策（分别执行），再看结局
  multi          所有可用候选一起预演，跨假设最坏情形聚合
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import common_planner as CP, runner, skills, v7_common_matrix as MX

BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'


def plan_and_run(tag, assets, cfg, soil, seed, snap, vis, goal_x, budget, out_root):
    d = out_root / tag; d.mkdir(parents=True, exist_ok=True)
    hyps = [{'id': k, 'kind': 'lux3d', 'collision_dir': v} for k, v in assets.items()]
    table = dict(assets)
    p = CP.plan_action(hyps, snap, vis, [soil], budget,
                       (lambda h, s: MX.build_env(cfg, s, collision_dir=table[h['id']])),
                       goal_x=goal_x, seed=seed)
    CP.write_plan(p, d)
    act = p['decision']['chosen']
    (d / 'decision.json').write_text(json.dumps(p['decision'], ensure_ascii=False, indent=2))
    env = MX.build_env(cfg, soil, collision_dir=MX.truth_collision_for(cfg))
    env.reset(seed=seed); env.restore_state(snap, mode='same_scene')
    r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=seed,
                             record_trajectory=True).run_current()
    frames = r.get('trajectory') or []
    if frames:
        (d / 'trajectory.jsonl').write_text('\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
    return {'tag': tag, 'hypotheses': list(assets), 'chosen': act,
            'cells': p['counts']['rows'], 'safe_set': p['decision'].get('safe_set'),
            'success': bool(r.get('success')), 'reason': r.get('reason'),
            'final_x': r.get('final_x'), 'frames': len(frames),
            'outcome': ('pass' if r.get('success') else ('safe_abandon' if act == 'A0' else 'fail'))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='R01_s1')
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--candidates', required=True, help='JSON: {"id": "collision_dir", ...}（按约定顺序）')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out_root = ROOT / a.out if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    out_root.mkdir(parents=True, exist_ok=True)
    cands = json.loads((ROOT / a.candidates).read_text())
    order = list(cands)
    plan = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
    cfg = next(c for c in plan['configs'] if c['config_id'] == a.config)
    unit = ROOT / BATCH / 'common_states' / a.config / a.soil / f'seed{a.seed}'
    acq = json.loads((unit / 'acquisition.json').read_text())
    snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
    vis = acq.get('visible') or {}
    goal_x = json.loads((ROOT / cfg['case_config']).read_text())['goal_x']
    budget = float(cfg.get('budget_s', 30.0))
    rows = []
    first = order[0]
    rows.append(plan_and_run('fixed_first', {first: cands[first]}, cfg, a.soil, a.seed,
                             snap, vis, goal_x, budget, out_root))
    for cid in order:
        rows.append(plan_and_run(f'single_{cid}', {cid: cands[cid]}, cfg, a.soil, a.seed,
                                 snap, vis, goal_x, budget, out_root))
    rows.append(plan_and_run('multi_all', cands, cfg, a.soil, a.seed, snap, vis,
                             goal_x, budget, out_root))
    single_rows = [r for r in rows if r['tag'].startswith('single_')]
    rep = {'schema': 'single-multi/v1', 'config': a.config, 'soil': a.soil, 'seed': a.seed,
           'create_order': order, 'state_hash': snap.get('state_hash'),
           'rows': rows,
           'summary': {
             'fixed_first': rows[0]['outcome'],
             'single_average': {
               'n': len(single_rows),
               'pass_rate': round(sum(1 for r in single_rows if r['outcome'] == 'pass') / max(1, len(single_rows)), 3),
               'outcomes': [r['outcome'] for r in single_rows]},
             'multi': rows[-1]['outcome'],
             'note': ('单候选分别决策后再平均；多候选是并发预演后最坏情形聚合，'
                      '不取几何并集。固定首候选失败不换第二个。')}}
    (out_root / 'single_multi.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    for r in rows:
        print(json.dumps({k: r[k] for k in ('tag', 'chosen', 'outcome', 'cells')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
