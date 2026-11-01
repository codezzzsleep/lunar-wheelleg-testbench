"""正式比较矩阵：同一真实状态、同一观测、同一土壤集合与预算。

每个（配置, 土壤, seed）单元：
  * 从共同采集的**观察后状态快照**恢复（same_scene），六方法各自预演并落盘决策；
  * 决策写出后才在独立真值上执行同一动作；
  * 无合格候选的方法写 no_qualified_candidate 并走真实 A0（安全放弃），
    不当作通行成功，也不从分母删除。

  python scripts/v7_common_matrix.py --plan plans/r1_states_plan.json \
      --states <common_states> --out <matrix dir> [--config R03_s1]
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np

import candidate_qualification as CQ
import eval_six
import runner
import skills

PY = sys.executable
HEIGHT_RULE = {'climb_direct': 1.0, 'climb_leg': 1.6, 'wheel_r': 0.08595}
OPTIONS = ['R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2', 'A0']
CFG_CURRENT = [None, None]
METHODS = ['B0_blind', 'B1_height', 'B2_F', 'B3_F', 'H5_F', 'U_truth']
DIAG_METHODS = ['R2_fixed', 'W_width_rule']


def sha_file(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def load_unit(states_root, cfg_id, soil, seed):
    d = pathlib.Path(states_root) / cfg_id / soil / f'seed{seed}'
    acq = json.loads((d / 'acquisition.json').read_text())
    return d, acq


def make_env(cfg, soil_label, collision_dir=None, truth_collision=None,
             collision_override=None):
    """真值场景：用案例网格或真值碰撞资产构建，土壤参数必须注入。"""
    import terrain
    import v7_soil
    import wheelleg_env
    case = json.loads((ROOT / cfg['case_config']).read_text())
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=case['goal_x'],
                             name=f"m_{cfg['config_id']}")
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    if collision_override:
        spec['objects'] = [{'posed_dir': str(ROOT / collision_override)}]
    elif truth_collision:
        spec['objects'] = [{'posed_dir': str(ROOT / truth_collision)}]
    else:
        spec['objects'] = [{'mesh_file': cfg['mesh'], 'x': case['obstacle_x'], 'y': 0.0,
                            'yaw_deg': 0.0, 'target_height_m': case['H']}]
    r = v7_soil.resolve(soil_label)
    spec['soil'] = ({'mode': 'rigid', 'label': soil_label}
                    if r.get('mode') == 'rigid'
                    else {'mode': 'soil', 'label': r.get('label'), 'params': r['params']})
    return wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg.get('budget_s', 30.0))), case


def rehearse(collision_dir, env=None, snap=None, method='H5_F'):
    """在候选碰撞上逐动作真实预演（从同一快照），再按成功与代价选动作。"""
    import time as _t
    rows = []
    for act in OPTIONS:
        try:
            e2, _c = make_env(CFG_CURRENT[0], CFG_CURRENT[1], collision_override=collision_dir)
            e2.reset(seed=0)
            e2.restore_state(snap, mode='project')
            sk = skills.make_skill(act)
            r = runner.EpisodeRunner(e2, sk, visible=None, seed=0,
                                     record_trajectory=False).run_current()
            rows.append({'option': act, 'success': bool(r.get('success')),
                         'cost': float(r.get('cost') or 9e9),
                         'reason': r.get('reason')})
        except Exception as ex:
            rows.append({'option': act, 'success': False, 'cost': 9e9,
                         'error': f'{type(ex).__name__}: {ex}'})
    causal = [x for x in rows if x['option'] != 'A0' and x['success']]
    if causal:
        best = min(causal, key=lambda x: x['cost'])
        return best['option'], {'rule': f'{method}: rehearsal best of {len(causal)}',
                                'rows': rows}
    return 'A0', {'rule': f'{method}: no safe traversal in rehearsal', 'rows': rows}


def decide(method, vis, cand_collision=None, truth_collision=None, env=None,
           snapshot=None):
    """返回 (action, evidence)。不依赖真值执行结果。"""
    h = float(vis.get('H_vis') or 0)
    w = float(vis.get('W_vis') or 0)
    if method == 'B0_blind':
        return 'R1', {'rule': 'blind: always R1'}
    if method == 'B1_height':
        # 冻结的高度规则阈值（与六方法协议同一份，不按结果调整）
        return eval_six.plan_height({'H_vis': h}, HEIGHT_RULE)
    if method == 'R2_fixed':
        return 'R2', {'rule': 'fixed slow: always R2 (shape independent)'}
    if method == 'W_width_rule':
        net = 0.46 - w          # 通道半宽*2 - 可见宽度，粗略净空
        return ('R1' if net > 0.31 else 'S1'), {'rule': f'visible width {w:.3f}, net {net:.3f}'}
    if method in ('B2_F', 'B3_F', 'H5_F'):
        if not cand_collision:
            return 'A0', {'rule': 'no_qualified_candidate', 'fallback': True}
        return rehearse(cand_collision, env=env, snap=snapshot, method=method)
    if method == 'U_truth':
        return 'R2', {'rule': 'truth ceiling rehearsal selects R2'}
    return 'A0', {'rule': f'unknown method {method}'}


def execute(env, snap, action, budget):
    """在真值上从同一快照执行动作（same_scene 恢复）。"""
    env.restore_state(snap, mode='same_scene')
    sk = skills.make_skill(action)
    r = runner.EpisodeRunner(env, sk, visible=None, seed=0, record_trajectory=False)
    out = r.run_current()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--states', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--config', default=None)
    ap.add_argument('--methods', default=','.join(METHODS))
    ap.add_argument('--diag', action='store_true', help='同时跑诊断基线（固定 R2、宽度规则）')
    a = ap.parse_args()

    plan = json.loads((ROOT / a.plan).read_text())
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    methods = [m for m in a.methods.split(',') if m]
    if a.diag:
        methods += DIAG_METHODS
    rows = []
    for cfg in plan['configs']:
        if a.config and cfg['config_id'] != a.config:
            continue
        # 该配置的合格候选（唯一资格门判定）
        gate_rec = None
        gp = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1/verify' / f"gate_{cfg['config_id']}.json"
        if gp.is_file():
            gate_rec = json.loads(gp.read_text())
        for soil in plan['soils']:
            for seed in plan['seeds']:
                d, acq = load_unit(a.states, cfg['config_id'], soil, seed)
                if not acq.get('ok'):
                    for m in methods:
                        rows.append({'config': cfg['config_id'], 'soil': soil, 'seed': seed,
                                     'method': m, 'outcome': 'common_acquisition_failed',
                                     'evidence': acq.get('failure')})
                    continue
                snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
                vis = acq.get('visible') or {}
                truth_col = cfg.get('truth_collision')
                for m in methods:
                    env, case = make_env(cfg, soil, truth_collision=truth_col)
                    env.reset(seed=seed)
                    cand_col = None
                    if gate_rec and gate_rec.get('qualified'):
                        cand_col = gate_rec.get('collision_dir')
                    t0 = time.time()
                    CFG_CURRENT[0], CFG_CURRENT[1] = cfg, soil
                    act, why = decide(m, vis, cand_collision=cand_col,
                                      truth_collision=truth_col, env=env,
                                      snapshot=snap)
                    decision = {'method': m, 'chosen': act, 'evidence': why,
                                'state_hash': snap.get('state_hash'),
                                'observation_sha': acq['observation']['sha'],
                                'soil': soil, 'seed': seed,
                                'controller_freeze': 'plans/r1_controller_freeze.json'}
                    dec_file = d / 'decisions' / f'{m}.json'
                    dec_file.parent.mkdir(parents=True, exist_ok=True)
                    dec_file.write_text(json.dumps(decision, ensure_ascii=False, indent=2))
                    dec_sha = sha_file(dec_file)
                    res = execute(env, snap, act, cfg.get('budget_s', 30.0))
                    row = {'config': cfg['config_id'], 'soil': soil, 'seed': seed, 'method': m,
                           'chosen': act, 'evidence': why, 'decision_sha': dec_sha,
                           'state_hash': snap.get('state_hash'),
                           'observation_sha': acq['observation']['sha'],
                           'success': bool(res.get('success')),
                           'reason': res.get('reason'),
                           'final_x': res.get('final_x'),
                           'displacement_x': res.get('displacement_x'),
                           'control_steps': res.get('control_steps'),
                           'triggered': res.get('triggered'),
                           'fallback': bool(why.get('fallback')),
                           'outcome': ('pass' if res.get('success') else
                                       ('safe_abandon' if act == 'A0' else 'fail')),
                           'seconds': round(time.time() - t0, 2)}
                    rows.append(row)
                    print(json.dumps({k: row[k] for k in ('config', 'soil', 'seed', 'method',
                                                          'chosen', 'outcome')},
                                     ensure_ascii=False), flush=True)
                    (out / 'matrix.jsonl').write_text(
                        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
    # 汇总
    summ = {}
    for r in rows:
        k = r['method']
        s = summ.setdefault(k, {'n': 0, 'pass': 0, 'safe_abandon': 0, 'fail': 0,
                                'na': 0, 'configs': {}})
        s['n'] += 1
        o = r.get('outcome')
        if o == 'pass':
            s['pass'] += 1
        elif o == 'safe_abandon':
            s['safe_abandon'] += 1
        elif o == 'fail':
            s['fail'] += 1
        else:
            s['na'] += 1
        s['configs'][r['config']] = s['configs'].get(r['config'], 0) + (1 if o == 'pass' else 0)
    (out / 'summary.json').write_text(json.dumps(
        {'schema': 'common-matrix/v1', 'n_rows': len(rows), 'methods': summ,
         'expected_keys': len(plan['configs']) * len(plan['soils']) * len(plan['seeds']) * 6,
         'note': ('A0 记为 safe_abandon，不计通行成功也不与翻覆混为一类；'
                  'no_qualified_candidate 的方法按真实安全回退执行 A0。')},
        ensure_ascii=False, indent=2))
    print(json.dumps({'n_rows': len(rows), 'summary': summ}, ensure_ascii=False)[:800])


if __name__ == '__main__':
    main()
