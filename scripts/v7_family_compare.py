"""六家族七行主比较（下一批任务书 §5）。

同一状态、同一公开可见量、同一预算、同一共同规划器，几何来源不同：

  1 B1_height        高度规则（规则，不预演）
  2 B2_F             方盒子 + 观测约束
  3 B3_F             镜像 + 观测约束
  4 E25D_block       2.5D 高程图，未知当障碍
  5 E25D_fill        2.5D 高程图，未知按可见地面补平
  6 H5_F             Lux3D 候选（诊断或合格，如实标注）
  7 U_truth          真值参考（只给自己读真值几何）

  python scripts/v7_family_compare.py --config R02_s0.9 --soil nominal --seed 7 --out <dir>
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import actions as ACT
import common_planner as CP
import eval_six
import runner
import skills
import v7_common_matrix as MX

BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'
HEIGHT_RULE = {'climb_direct': 1.0, 'climb_leg': 1.6, 'wheel_r': 0.08595}
FAMILIES = [
    ('B1_height', 'height_rule', None),
    ('B2_F', 'box', f'{BATCH}/priors_{{cfg}}/B2F'),
    ('B3_F', 'mirror', f'{BATCH}/priors_{{cfg}}/B3F'),
    ('E25D_block', 'elev25d_block', f'{BATCH}/elev25d/{{cfg}}/block'),
    ('E25D_fill', 'elev25d_fill', f'{BATCH}/elev25d/{{cfg}}/fill'),
    ('H5_F', 'lux3d', None),
]


def h5_asset(cfg_id):
    """Lux3D 假设：优先用该配置重配准后的候选，否则退回单视角资产。"""
    cands = [f'{BATCH}/refuse_{cfg_id}', f'{BATCH}/fusion_diagnostics/off1_{cfg_id}']
    for c in cands:
        if (ROOT / c / 'collision' / 'manifest.json').is_file():
            return c
    return None


def run_family(name, kind, asset, cfg, soil, seed, snap, vis, goal_x, out_root, budget):
    d = out_root / name
    d.mkdir(parents=True, exist_ok=True)
    rec = {'family': name, 'kind': kind, 'asset': asset}
    if kind == 'height_rule':
        act, why = eval_six.plan_height(vis, HEIGHT_RULE)
        rec['decision'] = {'chosen': act, 'evidence': why, 'planner': 'rule'}
        rec['cells'] = None
    else:
        if asset is not None and not (ROOT / asset / 'collision' / 'manifest.json').is_file():
            # 2.5D 高程图资产的 box 并集就写在资产目录自己的 manifest 里
            m = ROOT / asset / 'manifest.json'
            if m.is_file() and json.loads(m.read_text()).get('boxes'):
                pass
            else:
                asset = None
        if asset is None:
            rec.update({'decision': {'chosen': 'A0',
                                     'evidence': {'rule': 'asset_missing'}},
                        'outcome': 'asset_missing', 'cells': None})
            (d / 'row.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
            return rec
        hyps = [{'id': name, 'kind': kind, 'collision_dir': asset}]
        p = CP.plan_action(hyps, snap, vis, [soil], budget,
                           (lambda h, s: MX.build_env(cfg, s, collision_dir=asset)),
                           goal_x=goal_x, seed=seed)
        CP.write_plan(p, d)
        act = p['decision']['chosen']
        rec['decision'] = p['decision']
        rec['cells'] = p['counts']['rows']
        rec['safe_set'] = p['decision'].get('safe_set')
    (d / 'decision.json').write_text(json.dumps(rec['decision'], ensure_ascii=False, indent=2))
    env = MX.build_env(cfg, soil, collision_dir=MX.truth_collision_for(cfg))
    env.reset(seed=seed)
    env.restore_state(snap, mode='same_scene')
    r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=seed,
                             record_trajectory=True).run_current()
    frames = r.get('trajectory') or []
    if frames:
        (d / 'trajectory.jsonl').write_text(
            '\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
    rec.update({'success': bool(r.get('success')), 'reason': r.get('reason'),
                'final_x': r.get('final_x'), 'sim_time_s': round(float(env.t), 4),
                'frames': len(frames),
                'outcome': ('pass' if r.get('success') else
                            ('safe_abandon' if act == 'A0' else 'fail'))})
    (d / 'row.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--out', required=True)
    ap.add_argument('--families', default=None)
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
    budget = float(cfg.get('budget_s', 30.0))
    wanted = a.families.split(',') if a.families else None

    rows = []
    for name, kind, tmpl in FAMILIES:
        if wanted and name not in wanted:
            continue
        asset = None
        if tmpl:
            asset = tmpl.format(cfg=a.config)
        elif kind == 'lux3d':
            asset = h5_asset(a.config)
        rows.append(run_family(name, kind, asset, cfg, a.soil, a.seed, snap, vis,
                               goal_x, out_root, budget))
        print(json.dumps({'family': name, 'chosen': rows[-1]['decision'].get('chosen'),
                          'outcome': rows[-1].get('outcome')}, ensure_ascii=False), flush=True)
    # 真值参考：唯一能读真值几何的家庭
    tc = MX.truth_collision_for(cfg)
    hyps = [{'id': 'truth', 'kind': 'truth'}]
    p = CP.plan_action(hyps, snap, vis, [a.soil], budget,
                       (lambda h, s: MX.build_env(cfg, s, collision_dir=tc)),
                       goal_x=goal_x, seed=a.seed)
    d = out_root / 'U_truth'
    d.mkdir(parents=True, exist_ok=True)
    CP.write_plan(p, d)
    act = p['decision']['chosen']
    (d / 'decision.json').write_text(json.dumps(p['decision'], ensure_ascii=False, indent=2))
    env = MX.build_env(cfg, a.soil, collision_dir=tc)
    env.reset(seed=a.seed)
    env.restore_state(snap, mode='same_scene')
    r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=a.seed,
                             record_trajectory=True).run_current()
    rows.append({'family': 'U_truth', 'kind': 'truth', 'asset': tc,
                 'decision': p['decision'], 'cells': p['counts']['rows'],
                 'safe_set': p['decision'].get('safe_set'),
                 'success': bool(r.get('success')), 'reason': r.get('reason'),
                 'final_x': r.get('final_x'), 'sim_time_s': round(float(env.t), 4),
                 'outcome': ('pass' if r.get('success') else
                             ('safe_abandon' if act == 'A0' else 'fail'))})
    (d / 'row.json').write_text(json.dumps(rows[-1], ensure_ascii=False, indent=2))
    print(json.dumps({'family': 'U_truth', 'chosen': act,
                      'outcome': rows[-1]['outcome']}, ensure_ascii=False))

    table = {'schema': 'family-compare/v1', 'config': a.config, 'soil': a.soil,
             'seed': a.seed, 'state_hash': snap.get('state_hash'),
             'observation': acq.get('observation'), 'visible': vis,
             'budget_s': budget, 'planner': CP.PLANNER_VERSION,
             'rows': [{'family': r['family'], 'kind': r['kind'],
                       'chosen': r['decision'].get('chosen'),
                       'outcome': r.get('outcome'),
                       'cells': r.get('cells'), 'safe_set': r.get('safe_set'),
                       'final_x': r.get('final_x'), 'sim_time_s': r.get('sim_time_s')}
                      for r in rows]}
    (out_root / 'table.json').write_text(json.dumps(table, ensure_ascii=False, indent=2))
    print(json.dumps(table['rows'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
