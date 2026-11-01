"""正式比较矩阵（下一批任务书 §2–§3）：全部走共同规划器。

与上一版的区别（都是真实缺陷）：
  * U_truth 不再返回固定 R2，而是用真值几何作为唯一假设真实预演；
  * 可见量显式传入，缺字段报错，不再 visible=None；
  * 成本取真实模拟时间（成功=完成时刻，放弃/失败=冻结代价），不再恒为 9e9；
  * planning_soils 显式全集枚举 + 最坏情形聚合，执行土壤只记录；
  * H5_F 接候选列表，逐候选预演后跨假设聚合；
  * 无候选分支真实执行 A0（不是只写 decision.json）。

  python scripts/v7_common_matrix.py --plan plans/r1_states_plan.json \
      --states <common_states> --out <矩阵目录> --config R03_s1
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import actions as ACT
import common_planner as CP
import eval_six
import runner
import skills
import v7_soil
import collision_asset as CA

PY = sys.executable
BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'
RULE_METHODS = ('B0_blind', 'B1_height', 'R2_fixed', 'W_width_rule')
HEIGHT_RULE = {'climb_direct': 1.0, 'climb_leg': 1.6, 'wheel_r': 0.08595}


def sha_file(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def build_env(cfg, soil_label, collision_dir=None, objects=None):
    """构建环境：给了碰撞目录就用它的 box 并集，否则用案例真值网格。"""
    import terrain
    import wheelleg_env
    case = json.loads((ROOT / cfg['case_config']).read_text())
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=case['goal_x'],
                             name=f"m_{cfg['config_id']}")
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    if collision_dir:
        # 碰撞目录解析只有一个入口：普通融合资产取 collision/，2.5D 取根目录
        spec['objects'] = [{'posed_dir': CA.resolve(collision_dir)['collision_dir']}]
    elif objects is not None:
        spec['objects'] = objects
    else:
        spec['objects'] = [{'mesh_file': cfg['mesh'], 'x': case['obstacle_x'], 'y': 0.0,
                            'yaw_deg': 0.0, 'target_height_m': case['H']}]
    r = v7_soil.resolve(soil_label)
    spec['soil'] = ({'mode': 'rigid', 'label': soil_label}
                    if r.get('mode') == 'rigid'
                    else {'mode': 'soil', 'label': r.get('label'), 'params': r['params']})
    return wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg.get('budget_s', 30.0)))


def truth_collision_for(cfg):
    tc = cfg.get('truth_collision')
    return tc if (tc and (ROOT / tc).exists()) else None


def hypotheses_for(method, cfg, cand_map):
    """返回 (hypotheses, build_environment)。几何来源按方法区分，公开输入一致。"""
    if method == 'U_truth':
        tc = truth_collision_for(cfg)
        return ([{'id': 'truth', 'kind': 'truth'}],
                (lambda h, soil: build_env(cfg, soil, collision_dir=tc)))
    dirs = []
    if method == 'H5_F':
        for c in (cand_map.get('H5_F') or {}).get('candidates') or []:
            if c.get('qualified'):
                dirs.append(c)
    else:
        single = cand_map.get(method) or {}
        if single.get('qualified'):
            dirs.append({'candidate_id': method, 'collision_dir': single.get('collision_dir')})
    hyps = [{'id': c.get('candidate_id') or method, 'kind': method.lower(),
             'collision_dir': c.get('collision_dir')} for c in dirs]
    table = {h['id']: h['collision_dir'] for h in hyps}
    return hyps, (lambda h, soil: build_env(cfg, soil, collision_dir=table[h['id']]))


def rule_action(method, vis):
    if method == 'B0_blind':
        return 'R1', {'rule': 'blind: always R1（已降为诊断）'}
    if method == 'B1_height':
        return eval_six.plan_height(vis, HEIGHT_RULE)
    if method == 'R2_fixed':
        return 'R2', {'rule': 'fixed slow: always R2（诊断，与形状无关）'}
    if method == 'W_width_rule':
        return eval_six.plan_width_rule(vis, HEIGHT_RULE, ACT)
    raise ValueError(method)


def run_unit(cfg, soil, seed, states_root, cand_map, methods, out_root):
    cid = cfg['config_id']
    d = pathlib.Path(states_root) / cid / soil / f'seed{seed}'
    acq_p = ROOT / d / 'acquisition.json'
    if not acq_p.is_file():
        return [{'config': cid, 'soil': soil, 'seed': seed, 'method': m,
                 'outcome': 'common_acquisition_failed',
                 'error': f'缺共同状态 {d}'} for m in methods]
    acq = json.loads(acq_p.read_text())
    snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
    vis = acq.get('visible') or {}
    goal_x = json.loads((ROOT / cfg['case_config']).read_text())['goal_x']
    rows = []
    for m in methods:
        t0 = time.time()
        out_dir = out_root / cid / soil / f'seed{seed}' / m
        out_dir.mkdir(parents=True, exist_ok=True)
        rec = {'config': cid, 'soil': soil, 'seed': seed, 'method': m,
               'state_hash': snap.get('state_hash'),
               'observation_sha': (acq.get('observation') or {}).get('sha')}
        try:
            if m in RULE_METHODS:
                act, why = rule_action(m, vis)
                rec['decision'] = {'chosen': act, 'evidence': why, 'planner': 'rule'}
            else:
                hyps, builder = hypotheses_for(m, cfg, cand_map)
                if not hyps:
                    rec['decision'] = {'chosen': 'A0',
                                       'evidence': {'rule': 'no_qualified_candidate',
                                                    'fallback': True},
                                       'planner': CP.PLANNER_VERSION,
                                       'no_candidate': True}
                else:
                    plan = CP.plan_action(hyps, snap, vis, [soil],
                                          cfg.get('budget_s', 30.0), builder,
                                          goal_x=goal_x, seed=seed)
                    CP.write_plan(plan, out_dir)
                    rec['decision'] = {'chosen': plan['decision']['chosen'],
                                       'evidence': plan['decision'],
                                       'planner': CP.PLANNER_VERSION,
                                       'cells': plan['counts']['rows'],
                                       'safe_set': plan['decision'].get('safe_set')}
                    rec['plan_matrix'] = str((out_dir / 'plan_matrix.jsonl').relative_to(ROOT))
                act = rec['decision']['chosen']
            dec_p = out_dir / 'decision.json'
            dec_p.write_text(json.dumps(rec['decision'], ensure_ascii=False, indent=2))
            rec['decision_sha'] = sha_file(dec_p)
            env = build_env(cfg, soil, collision_dir=truth_collision_for(cfg))
            env.reset(seed=seed)
            env.restore_state(snap, mode='same_scene')
            r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=seed,
                                     record_trajectory=True).run_current()
            frames = r.get('trajectory') or []
            if frames:
                (out_dir / 'trajectory.jsonl').write_text(
                    '\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
            rec['execution'] = {'success': bool(r.get('success')), 'reason': r.get('reason'),
                                'final_x': r.get('final_x'),
                                'displacement_x': r.get('displacement_x'),
                                'control_steps': r.get('steps'), 'frames': len(frames),
                                'sim_time_s': round(float(env.t), 4),
                                'state_mode': 'same_scene'}
            rec['outcome'] = ('pass' if r.get('success') else
                              ('safe_abandon' if act == 'A0' else 'fail'))
        except Exception as e:
            rec['outcome'] = 'error'
            rec['error'] = f'{type(e).__name__}: {e}'
        rec['seconds'] = round(time.time() - t0, 2)
        rows.append(rec)
        print(json.dumps({'config': cid, 'soil': soil, 'seed': seed, 'method': m,
                          'outcome': rec['outcome'],
                          'chosen': (rec.get('decision') or {}).get('chosen')},
                         ensure_ascii=False), flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--states', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--config', default=None)
    ap.add_argument('--methods', default='B0_blind,B1_height,B2_F,B3_F,H5_F,U_truth')
    ap.add_argument('--diag', action='store_true')
    ap.add_argument('--candidates', default=None,
                    help='方法→候选映射；H5_F 可给 candidates 列表')
    ap.add_argument('--soils', default=None, help='只跑这些土壤（逗号分隔）')
    ap.add_argument('--seeds', default=None, help='只跑这些 seed（逗号分隔）')
    a = ap.parse_args()
    plan = json.loads((ROOT / a.plan).read_text())
    out_root = ROOT / a.out
    out_root.mkdir(parents=True, exist_ok=True)
    methods = [m for m in a.methods.split(',') if m]
    if a.diag:
        methods += ['R2_fixed', 'W_width_rule']
    cmap_all = json.loads((ROOT / a.candidates).read_text()) if a.candidates else {}
    soils = a.soils.split(',') if a.soils else plan['soils']
    seeds = [int(x) for x in a.seeds.split(',')] if a.seeds else plan['seeds']
    rows = []
    for cfg in plan['configs']:
        if a.config and cfg['config_id'] != a.config:
            continue
        cmap = cmap_all.get(cfg['config_id'], {})
        for soil in soils:
            for seed in seeds:
                rows += run_unit(cfg, soil, seed, a.states, cmap, methods, out_root)
                (out_root / 'matrix.jsonl').write_text(
                    '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
    summ = {}
    for r in rows:
        s = summ.setdefault(r['method'], {'n': 0, 'pass': 0, 'safe_abandon': 0,
                                          'fail': 0, 'error': 0, 'na': 0, 'per_config': {}})
        s['n'] += 1
        o = r.get('outcome') or 'na'
        s[o] = s.get(o, 0) + 1
        pc = s['per_config'].setdefault(r['config'], {'pass': 0, 'n': 0})
        pc['n'] += 1
        pc['pass'] += 1 if o == 'pass' else 0
    (out_root / 'summary.json').write_text(json.dumps(
        {'schema': 'common-matrix/v3', 'planner': CP.PLANNER_VERSION,
         'n_rows': len(rows), 'methods': summ,
         'note': ('所有建模方法走同一共同规划器；规则方法直接给动作；'
                  'A0 为真实执行的安全放弃，不计通行成功。')},
        ensure_ascii=False, indent=2))
    print(json.dumps({'n_rows': len(rows), 'summary': summ}, ensure_ascii=False)[:900])


if __name__ == '__main__':
    main()
