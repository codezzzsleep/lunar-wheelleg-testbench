"""共同规划小预检（下一批任务书 §3）：R02@0.9 + R03 各一个真实停稳状态。

预检不做全量矩阵，只验证：
  1. 固定 R1 在独立真值上真实执行（可行性对照）；
  2. 真值参考用**同一共同规划器**，枚举 7 个适用动作 × 3 土壤后执行自己的选择；
  3. 有合格候选时 H5_F 走同一规划器；无候选时真实执行 A0。

  python scripts/v7_precheck_next.py --config R02_s0.9 --soil nominal --seed 7 --out <dir>
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


def load_state(cfg_id, soil, seed):
    d = ROOT / BATCH / 'common_states' / cfg_id / soil / f'seed{seed}'
    acq = json.loads((d / 'acquisition.json').read_text())
    snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
    return acq, snap


def execute(cfg, soil, seed, snap, act, vis, out_dir):
    env = MX.build_env(cfg, soil, collision_dir=MX.truth_collision_for(cfg))
    env.reset(seed=seed)
    env.restore_state(snap, mode='same_scene')
    r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=seed,
                             record_trajectory=True).run_current()
    frames = r.get('trajectory') or []
    if frames:
        (out_dir / 'trajectory.jsonl').write_text(
            '\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
    return {'success': bool(r.get('success')), 'reason': r.get('reason'),
            'final_x': r.get('final_x'), 'displacement_x': r.get('displacement_x'),
            'control_steps': r.get('steps'), 'frames': len(frames),
            'sim_time_s': round(float(env.t), 4), 'state_mode': 'same_scene'}


def arm(name, cfg, soil, seed, snap, vis, out_root, act=None, hypotheses=None,
        builder=None, planning_soils=None):
    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = {'arm': name, 'config': cfg['config_id'], 'soil': soil, 'seed': seed,
           'state_hash': snap.get('state_hash')}
    if act is not None:
        rec['decision'] = {'chosen': act, 'evidence': {'rule': f'{name}: fixed action'}}
        rec['plan'] = None
    else:
        plan = CP.plan_action(hypotheses, snap, vis, planning_soils or [soil],
                              cfg.get('budget_s', 30.0), builder,
                              goal_x=json.loads((ROOT / cfg['case_config']).read_text())['goal_x'],
                              seed=seed)
        CP.write_plan(plan, out_dir)
        act = plan['decision']['chosen']
        rec['decision'] = plan['decision']
        rec['plan'] = {'cells': plan['counts']['rows'],
                       'expected': len(hypotheses) * 8 * len(planning_soils or [soil]),
                       'applicability': [a for a in plan['applicability']
                                         if a['hypothesis'] == hypotheses[0]['id']],
                       'safe_set': plan['decision'].get('safe_set')}
    (out_dir / 'decision.json').write_text(json.dumps(rec['decision'], ensure_ascii=False,
                                                     indent=2))
    rec['execution'] = execute(cfg, soil, seed, snap, act, vis, out_dir)
    rec['outcome'] = ('pass' if rec['execution']['success'] else
                      ('safe_abandon' if act == 'A0' else 'fail'))
    (out_dir / 'arm.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({'arm': name, 'chosen': act, 'outcome': rec['outcome'],
                      'plan_cells': (rec.get('plan') or {}).get('cells')},
                     ensure_ascii=False), flush=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='R02_s0.9')
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--out', required=True)
    ap.add_argument('--candidates', default=f'{BATCH}/verify/candidates_R03_s1.json')
    ap.add_argument('--soils', default='nominal,low_traction,high_drag')
    a = ap.parse_args()
    out_root = ROOT / a.out if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    out_root.mkdir(parents=True, exist_ok=True)
    plan = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
    cfg = next(c for c in plan['configs'] if c['config_id'] == a.config)
    acq, snap = load_state(cfg['config_id'], a.soil, a.seed)
    vis = acq.get('visible') or {}
    soils = [s for s in a.soils.split(',') if s]
    cmap = {}
    if (ROOT / a.candidates).is_file():
        cmap = json.loads((ROOT / a.candidates).read_text()).get(cfg['config_id'], {})

    out = {'schema': 'precheck-next/v1', 'config': cfg['config_id'], 'soil': a.soil,
           'seed': a.seed, 'state_hash': snap.get('state_hash'),
           'visible': vis, 'planning_soils': soils,
           'observation_sha': (acq.get('observation') or {}).get('sha'),
           'arms': {}}

    # 1 固定 R1（不再进入主比较，只作可行性对照）
    out['arms']['fixed_R1'] = arm('fixed_R1', cfg, a.soil, a.seed, snap, vis, out_root,
                                  act='R1')

    # 2 真值参考：真实预演 7 个适用动作 × 3 土壤
    hyps = [{'id': 'truth', 'kind': 'truth'}]
    builder = lambda h, soil: MX.build_env(cfg, soil, collision_dir=MX.truth_collision_for(cfg))
    out['arms']['truth_reference'] = arm('truth_reference', cfg, a.soil, a.seed, snap, vis,
                                         out_root, hypotheses=hyps, builder=builder,
                                         planning_soils=soils)

    # 3 候选方法：有合格候选走共同规划器，否则真实 A0
    for method in ('H5_F',):
        entry = cmap.get(method) or {}
        cands = [c for c in (entry.get('candidates') or []) if c.get('qualified')]
        if not cands and entry.get('qualified'):
            cands = [{'candidate_id': method, 'collision_dir': entry.get('collision_dir')}]
        if cands:
            hyps_c = [{'id': c['candidate_id'], 'kind': 'lux3d',
                       'collision_dir': c['collision_dir']} for c in cands]
            table = {h['id']: h['collision_dir'] for h in hyps_c}
            out['arms'][method] = arm(method, cfg, a.soil, a.seed, snap, vis, out_root,
                                      hypotheses=hyps_c,
                                      builder=(lambda h, soil:
                                               MX.build_env(cfg, soil,
                                                            collision_dir=table[h['id']])),
                                      planning_soils=soils)
        else:
            out['arms'][method] = arm(f'{method}_no_candidate', cfg, a.soil, a.seed,
                                      snap, vis, out_root, act='A0')
            out['arms'][method]['note'] = ('无合格候选：执行真实 A0（不是只写决策）；'
                                           '理由见候选资格记录')

    (out_root / 'precheck.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    t = out['arms']['truth_reference']
    print(json.dumps({'truth_arm_cells': (t.get('plan') or {}).get('cells'),
                      'truth_chosen': t['decision'].get('chosen'),
                      'truth_outcome': t['outcome'],
                      'fixed_R1_outcome': out['arms']['fixed_R1']['outcome']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
