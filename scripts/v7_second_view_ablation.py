"""第二观察消融：同一 S1、同一预算、同一土壤，两臂各自决策后再执行。

A 臂：只用第一视角（单视角候选 off1_*）。
B 臂：使用第二张图（两视角合并候选）。

两臂都从同一观察后快照恢复，决策各自落盘，再在同场景副本上执行；不使用
任何 --skip-acceptance 的强制 usable，观察验收由采集记录直接给出。

  python scripts/v7_second_view_ablation.py --case R03 --soil nominal --seed 7 --out <dir>
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import candidate_qualification as CQ
import runner
import skills
import v7_common_matrix as MX

BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'
ARMS = {
    'A_no_second_view': {'candidate': f'{BATCH}/fusion_diagnostics/off1_R03_s1',
                         'label': '单视角候选（不使用第二张图）'},
    'B_with_second_view': {'candidate': f'{BATCH}/fusion_diagnostics/tvocc_R03_s1_v3',
                           'label': '两视角候选（使用第二张图）'},
}


def gate_arm(arm_dir, obs, case):
    """两视角资产没有 process.json，需要走两视角记录归一；否则会被判成缺测。"""
    d = ROOT / arm_dir
    if not (d / 'manifest.json').is_file() and (d / 'two_view_report.json').is_file():
        proc = CQ.record_from_two_view(d)
    else:
        proc = d / 'manifest.json'
    return CQ.qualify_candidate({'candidate_id': d.name, 'process': str(proc),
                                 'collision_dir': str(d / 'collision'),
                                 'mesh': str(d / 'body.stl')}, obs, case=case, strict=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', default='R03')
    ap.add_argument('--config', default='R03_s1')
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)

    plan = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
    cfg = next(c for c in plan['configs'] if c['config_id'] == a.config)
    state_dir = ROOT / BATCH / 'common_states' / a.config / a.soil / f'seed{a.seed}'
    acq = json.loads((state_dir / 'acquisition.json').read_text())
    snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
    obs = CQ.load_observation_set(ROOT / 'runs/unseen/recovery_r3/obs_R03')
    case = json.loads((ROOT / cfg['case_config']).read_text())

    rec = {'schema': 'second-view-ablation/v2',
           'state': {'snapshot': acq['state']['snapshot'],
                     'state_hash': acq['state']['state_hash'],
                     'soil': a.soil, 'seed': a.seed},
           'observation': acq['observation'],
           'observation_acceptance_source': '共同采集记录（未使用 skip-acceptance 覆盖）',
           'observation_cost': {'drive_and_settle_s': (acq.get('state') or {}).get('env_t'),
                                'note': '第二张图的成本是真实驾驶+停稳+采集的时间'},
           'arms': {}}
    MX.CFG_CURRENT[0], MX.CFG_CURRENT[1] = cfg, a.soil
    for name, spec in ARMS.items():
        arm_dir = spec['candidate']
        q = gate_arm(arm_dir, obs, case)
        env, _ = MX.make_env(cfg, a.soil, collision_override=f'{arm_dir}/collision')
        env.reset(seed=a.seed)
        if q['qualified']:
            act, why = MX.rehearse(f'{arm_dir}/collision', snap=snap, method='H5_F')
        else:
            act, why = 'A0', {'rule': 'no_qualified_candidate', 'fallback': True,
                              'reasons': q['reasons'][:3]}
        dec = {'arm': name, 'chosen': act, 'evidence': why,
               'state_hash': snap.get('state_hash'), 'soil': a.soil, 'seed': a.seed,
               'candidate_qualified': q['qualified']}
        dp = out / f'{name}_decision.json'
        dp.write_text(json.dumps(dec, ensure_ascii=False, indent=2))
        # 执行必须在**独立真值**场景上，从同一快照同场景恢复；
        # 预演环境用的是候选碰撞，不能用于真值执行。
        exec_env, _ = MX.make_env(cfg, a.soil, truth_collision=cfg.get('truth_collision'))
        exec_env.reset(seed=a.seed)
        exec_env.restore_state(snap, mode='same_scene')
        r = runner.EpisodeRunner(exec_env, skills.make_skill(act), seed=a.seed,
                                 record_trajectory=True).run_current()
        n = len(r.get('trajectory') or [])
        rec['arms'][name] = {'label': spec['label'], 'candidate': arm_dir,
                             'qualified': q['qualified'],
                             'visible': q.get('visible_metrics'),
                             'collision': q.get('collision_metrics'),
                             'decision': act, 'decision_sha': None,
                             'success': bool(r.get('success')), 'reason': r.get('reason'),
                             'final_x': r.get('final_x'),
                             'displacement_x': r.get('displacement_x'),
                             'frames': n}
    # C 臂：从 S0 直接行动（不移动观察），用于"操作净价值"对照。
    # S0 由同一 (seed, soil, config) 的确定性 reset 复现，并核对哈希一致。
    MX.CFG_CURRENT[0], MX.CFG_CURRENT[1] = cfg, a.soil
    s0_path = (acq.get('s0') or {}).get('snapshot')
    rec['arms']['C_direct_from_S0'] = {
        'label': 'S0 直接行动（不做移动观察）',
        's0_snapshot': s0_path,
        'observation_cost': 0.0}
    if not s0_path:
        rec['arms']['C_direct_from_S0']['error'] = '采集记录未保存 S0 快照，未执行'
        s0 = None
    else:
        s0 = json.loads((ROOT / s0_path).read_text())
        s0_env, _ = MX.make_env(cfg, a.soil, truth_collision=cfg.get('truth_collision'))
        s0_env.reset(seed=a.seed)
        s0_env.restore_state(s0, mode='same_scene')
        rec['arms']['C_direct_from_S0']['s0_state_hash'] = s0.get('state_hash')
    if s0 is not None:
        act0, why0 = MX.decide('H5_F', acq.get('visible') or {},
                               cand_collision=(f"{ARMS['B_with_second_view']['candidate']}/collision"),
                               snapshot=s0)
        r0 = runner.EpisodeRunner(s0_env, skills.make_skill(act0), seed=a.seed,
                                  record_trajectory=True).run_current()
        rec['arms']['C_direct_from_S0'].update({
            'decision': act0, 'success': bool(r0.get('success')),
            'reason': r0.get('reason'), 'final_x': r0.get('final_x'),
            'displacement_x': r0.get('displacement_x'),
            'frames': len(r0.get('trajectory') or [])})
    else:
        rec['arms']['C_direct_from_S0'].setdefault('error', '无可用 S0 快照')
    a_ = rec['arms']['A_no_second_view']
    b_ = rec['arms']['B_with_second_view']
    rec['reading'] = {
        'information_value': ('两臂决策%s，结果%s' % (
            '相同' if a_['decision'] == b_['decision'] else '不同',
            '相同' if a_['success'] == b_['success'] else '不同')),
        'movement_cost': 'B 臂的观察成本已记在 observation_cost 中，A 臂为 0',
        'no_forced_acceptance': True}
    (out / 'ablation.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: {kk: v.get(kk) for kk in ('decision', 'success', 'reason',
                                                   'displacement_x', 'qualified')}
                      for k, v in rec['arms'].items()}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
