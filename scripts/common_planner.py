"""共同规划：所有比较入口复用的唯一实现（下一批任务书 §2）。

一个接口，一条语义：

    plan_action(hypotheses, snapshot, visible, planning_soils, budget,
                build_environment, goal_x) -> 原始矩阵 + 适用性 + 决策与理由

必须满足：
  * 假设 × 状态 × 土壤 × 动作**完整枚举**，逐个预演，不做几何并集；
  * 公开可见量必须真实传入（缺关键字段直接报错，不允许 visible=None 回退）；
  * 成本来自真实模拟时间（成功用完成时刻，安全放弃用冻结代价，失败用冻结代价），
    成功却缺时间属于计算错误，不填 9e9 后继续宣布最优；
  * planning_soils 显式给出，逐土壤枚举后按最坏情形聚合；执行土壤只记录，不告知规划器；
  * 不适用格与实际物理失败分开记录；A0 不进入通行安全集。
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import eval_six
import collision_asset as CA

REQUIRED_VISIBLE = ('x_front', 'W_vis', 'H_vis')
PLANNER_VERSION = 'common-planner/v1'


class PlannerInputError(ValueError):
    """输入不完整：必须是显式错误，不能退化成直行或空可见量。"""


def check_visible(visible):
    missing = [k for k in REQUIRED_VISIBLE
               if not isinstance(visible, dict) or visible.get(k) is None]
    if missing:
        raise PlannerInputError(
            f'公开可见量缺关键字段 {missing}：不允许用空可见量退化规划')
    return {k: float(visible[k]) for k in REQUIRED_VISIBLE} | {
        k: v for k, v in (visible or {}).items() if k not in REQUIRED_VISIBLE}


def plan_action(hypotheses, snapshot, visible, planning_soils, budget,
                build_environment, goal_x=2.6, seed=0, actions_mod=None,
                state_mode='project', channel_half=1.2):
    """完整枚举并预演，返回矩阵与决策。

    hypotheses: [{'id': str, 'kind': str}]，kind 仅用于记录（如 truth/box/mirror/lux3d）
    build_environment(hypothesis, soil) -> env（调用方负责场景与土壤注入）
    """
    import actions as ACT
    actions_mod = actions_mod or ACT
    vis = check_visible(visible)
    if not hypotheses:
        raise PlannerInputError('假设列表为空：无候选时必须走显式 A0 分支')
    if not planning_soils:
        raise PlannerInputError('planning_soils 为空：跨土壤聚合必须有集合')

    matrix, applicability = [], []
    # 只枚举可通行（非 A0）动作：A0 是安全回退，不是被规划的动作。
    traversal_actions = [o for o in actions_mod.OPTIONS if o != 'A0']
    for h in hypotheses:
        for act in traversal_actions:
            ok, why = actions_mod.applicable(act, vis, channel_half)
            applicability.append({'hypothesis': h['id'], 'action': act,
                                  'applicable': bool(ok), 'reason': why})
            if not ok:
                for soil in planning_soils:
                    matrix.append({'hypothesis': h['id'], 'kind': h.get('kind'),
                                   'action': act, 'soil': soil,
                                   'outcome': 'not_applicable', 'reason': why,
                                   'success': False, 'cost': None})
                continue
            for soil in planning_soils:
                # 先单独建环境：加载失败属于 rehearsal_error，绝不混进物理结论
                try:
                    env = build_environment(h, soil)
                except CA.CollisionAssetError as e:
                    matrix.append({'hypothesis': h['id'], 'kind': h.get('kind'),
                                   'action': act, 'soil': soil,
                                   'outcome': 'rehearsal_error',
                                   'error_class': 'collision_asset',
                                   'error': str(e)[:600],
                                   'success': False, 'cost': None})
                    continue
                except Exception as e:
                    matrix.append({'hypothesis': h['id'], 'kind': h.get('kind'),
                                   'action': act, 'soil': soil,
                                   'outcome': 'rehearsal_error',
                                   'error_class': 'environment',
                                   'error': f'{type(e).__name__}: {e}'[:600],
                                   'success': False, 'cost': None})
                    continue
                try:
                    rows = eval_six.run_episode_from_env(
                        env, act, seed, vis, goal_x, time_limit=budget,
                        hid=h['id'], soil_mode=soil, snapshot=snapshot,
                        state_mode=state_mode)
                    r = rows[0]
                    if r['success'] and (r.get('cost') is None
                                         or r['cost'] >= eval_six.FAR):
                        # 成功但缺真实时间：这是计算错误，不能静默给最坏代价
                        raise PlannerInputError(
                            f"{h['id']}/{act}/{soil} 成功却没有有效完成时刻")
                    matrix.append({'hypothesis': h['id'], 'kind': h.get('kind'),
                                   'action': act, 'soil': soil,
                                   'outcome': ('success' if r['success'] else
                                               ('abort' if r.get('abort') else 'failure')),
                                   'success': bool(r['success']),
                                   'cost': r.get('cost'), 'reason': r.get('reason'),
                                   'sim_time_s': r.get('sim_time_s_'),
                                   't_end': r.get('t_end'), 'final_x': r.get('final_x'),
                                   'max_tilt': r.get('max_tilt'),
                                   'triggered': r.get('triggered')})
                except PlannerInputError:
                    raise
                except Exception as e:
                    matrix.append({'hypothesis': h['id'], 'kind': h.get('kind'),
                                   'action': act, 'soil': soil,
                                   'outcome': 'rehearsal_error',
                                   'error_class': 'episode',
                                   'error': f'{type(e).__name__}: {e}'[:600],
                                   'success': False, 'cost': None})

    # 聚合 1：同一（假设, 动作）跨土壤最坏情形
    per_hyp = {}
    for row in matrix:
        key = (row['hypothesis'], row['action'])
        cur = per_hyp.setdefault(key, {'soil_outcomes': {}, 'costs': [],
                                       'success': True, 'errors': 0,
                                       'not_applicable': False})
        cur['soil_outcomes'][row['soil']] = row['outcome']
        if row['outcome'] == 'not_applicable':
            cur['not_applicable'] = True
            cur['success'] = False
        elif row['outcome'] == 'rehearsal_error':
            cur['errors'] += 1
            cur['success'] = False
        else:
            cur['success'] = cur['success'] and row['success']
            if row.get('cost') is not None:
                cur['costs'].append(row['cost'])

    # 聚合 2：跨假设最坏情形（多假设语义，不做几何并集）
    per_action = {}
    for (hid, act), cur in per_hyp.items():
        agg = per_action.setdefault(act, {'success': True, 'costs': [],
                                          'per_hypothesis': {}, 'errors': 0,
                                          'not_applicable': False})
        agg['per_hypothesis'][hid] = {'success': cur['success'],
                                      'soil_outcomes': cur['soil_outcomes'],
                                      'cost': (max(cur['costs']) if cur['costs'] else None)}
        agg['success'] = agg['success'] and cur['success'] and not cur['not_applicable']
        agg['errors'] += cur['errors']
        agg['not_applicable'] = agg['not_applicable'] or cur['not_applicable']
        agg['costs'] += cur['costs']

    candidates = []
    for act, agg in per_action.items():
        if act == 'A0':
            continue                       # A0 不进入通行安全集
        if agg['success'] and agg['costs']:
            candidates.append({'action': act, 'cost': max(agg['costs'])})
    candidates.sort(key=lambda x: (x['cost'], x['action']))

    load_errors = sum(v['errors'] for v in per_action.values())
    if candidates:
        best = candidates[0]
        decision = {'chosen': best['action'], 'safe_set': [c['action'] for c in candidates],
                    'cost': best['cost'], 'reason': 'worst_case_traversal',
                    'tie': [c['action'] for c in candidates if c['cost'] == best['cost']],
                    'rehearsal_errors': load_errors}
    else:
        decision = {'chosen': 'A0', 'safe_set': [],
                    'cost': None,
                    'reason': ('no_safe_traversal' if load_errors == 0
                               else 'inconclusive_rehearsal_errors'),
                    'rehearsal_errors': load_errors,
                    'detail': {a: {'not_applicable': v['not_applicable'],
                                   'errors': v['errors'],
                                   'per_hypothesis': {k: vv['success']
                                                      for k, vv in v['per_hypothesis'].items()}}
                               for a, v in per_action.items() if a != 'A0'}}

    return {'schema': 'common-plan/v1', 'version': PLANNER_VERSION,
            'visible': vis, 'planning_soils': list(planning_soils),
            'hypotheses': [h['id'] for h in hypotheses],
            'state_mode': state_mode,
            'matrix': matrix, 'applicability': applicability,
            'per_hypothesis_action': {f'{k[0]}|{k[1]}': v for k, v in per_hyp.items()},
            'decision': decision,
            'counts': {'rows': len(matrix),
                       'expected_rows': (len(hypotheses) * len(traversal_actions)
                                         * len(planning_soils)),
                       'traversal_actions': traversal_actions,
                       'a0_is_fallback': True}}


def write_plan(plan, out_dir, name='plan'):
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{name}_matrix.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in plan['matrix']) + '\n')
    (out / f'{name}_decision.json').write_text(
        json.dumps(plan['decision'], ensure_ascii=False, indent=2))
    slim = {k: v for k, v in plan.items() if k != 'matrix'}
    (out / f'{name}.json').write_text(json.dumps(slim, ensure_ascii=False, indent=2))
    return {'matrix': str(out / f'{name}_matrix.jsonl'),
            'decision': str(out / f'{name}_decision.json'),
            'summary': str(out / f'{name}.json')}
