"""
V6 唯一决策函数：worst-case-risk/v2。

输入与 V5 rehearsal 行兼容：
  {option, seed, hypothesis_id, success, abort, t_end, not_applicable}
输出：
  - safe_set：所有冻结样本均完成、证据完整的非 A0 动作；
  - 每个动作的最坏代价（每个假设内取 max，再跨假设取 max）；
  - chosen = safe_set 中 worst_cost 最小，tie-break 动作名；
  - 空集合 -> A0；
  - 缺行 -> insufficient_evidence，不把缺失当失败再偷偷选动作。

与 V5 的差异：
  - V5 unseen_pipeline 用平均代价；eval_six 用 worst cost；本函数统一为 worst cost；
  - A0 不参与 safe_set；
  - 规则版本固定为 worst-case-risk/v2；V5 原结果保留为 worst-case-risk/v1。
"""
import numpy as np

RULE = 'worst-case-risk/v2'
FAR = 60.0
ABORT = 40.0


def _clean(rows):
    out = []
    for r in rows:
        if r.get('not_applicable'):
            continue
        out.append(r)
    return out


def evaluate(matrix, options, c_fail=FAR, c_abort=ABORT):
    rows = _clean(matrix)
    hyps = sorted({r.get('hypothesis_id') for r in rows})
    seeds = sorted({r.get('seed') for r in rows})
    if not hyps:
        return {'rule': RULE, 'insufficient_evidence': True,
                'missing': 'no hypotheses', 'options': list(options)}
    stats = {}
    for o in options:
        if o == 'A0':
            continue
        per_h = {}
        missing = []
        for h in hyps:
            cells = [r for r in rows if r.get('option') == o and r.get('hypothesis_id') == h]
            by_seed = {r.get('seed'): r for r in cells}
            miss = [sd for sd in seeds if sd not in by_seed]
            if miss:
                missing.append(f'{o}/{h}: missing seeds {miss}')
                continue
            costs, fails = [], 0
            for sd in seeds:
                r = by_seed[sd]
                if r.get('success'):
                    costs.append(float(r.get('t_end') or 0.0))
                else:
                    fails += 1
                    costs.append(float(c_abort if r.get('abort') else c_fail))
            per_h[h] = {'fails': fails, 'n': len(seeds),
                        'f': round(fails / len(seeds), 3),
                        'max_cost': round(max(costs), 3),
                        'costs': [round(c, 3) for c in costs]}
        if missing:
            stats[o] = {'missing': missing, 'safe': False, 'insufficient': True}
            continue
        worst_cost = max(per_h[h]['max_cost'] for h in hyps)
        risk = max(per_h[h]['f'] for h in hyps)
        stats[o] = {'per_hypothesis': per_h, 'risk': round(risk, 3),
                    'worst_cost': round(worst_cost, 3),
                    'safe': bool(risk == 0.0), 'missing': [], 'insufficient': False}
    complete = [o for o in options if o != 'A0' and o in stats
                and not stats[o].get('insufficient') and not stats[o].get('missing')
                and len(stats[o].get('per_hypothesis', {})) == len(hyps)]
    safe = [o for o in complete if stats[o]['safe']]
    tie, tied = False, []
    if safe:
        safe.sort(key=lambda o: (stats[o]['worst_cost'], o))
        chosen = safe[0]
        best = stats[safe[0]]['worst_cost']
        tied = [o for o in safe if abs(stats[o]['worst_cost'] - best) < 1e-9]
        tie = len(tied) > 1
        no_robust = False
    else:
        chosen, no_robust = 'A0', True
    return {'rule': RULE, 'tau': 0.0, 'c_fail': c_fail, 'c_abort': c_abort,
            'hypotheses': hyps, 'n_seeds': len(seeds), 'stats': stats,
            'safe_set': safe, 'chosen': chosen, 'no_robust_option': no_robust,
            'tie': tie, 'tied_options': tied,
            'insufficient_evidence': not bool(complete),
            'missing': [x for o in stats.values() for x in (o.get('missing') or [])],
            'reason_text': (f'在 {len(hyps)} 个候选 × {len(seeds)} 个冻结初态上均完成；'
                            f'按最坏代价选 {chosen}（tie={tie}）' if safe else
                            '没有在所有冻结样本上完成的动作 -> A0')}


def legacy_mean_cost(matrix, options, c_fail=FAR, c_abort=ABORT):
    """V5 unseen_pipeline 的平均代价规则，仅用于 old/new 对照。"""
    rows = _clean(matrix)
    hyps = sorted({r.get('hypothesis_id') for r in rows})
    seeds = sorted({r.get('seed') for r in rows})
    stats = {}
    for o in options:
        if o == 'A0':
            continue
        per_h = {}
        for h in hyps:
            cells = [r for r in rows if r.get('option') == o and r.get('hypothesis_id') == h]
            if len(cells) != len(seeds):
                continue
            costs = [float(r.get('t_end')) if r.get('success')
                     else float(c_abort if r.get('abort') else c_fail) for r in cells]
            per_h[h] = {'f': sum(1 for r in cells if not r.get('success')) / len(cells),
                        'mean': float(np.mean(costs))}
        if len(per_h) != len(hyps):
            continue
        risk = max(v['f'] for v in per_h.values())
        stats[o] = {'risk': risk, 'mean_cost': float(np.mean([v['mean'] for v in per_h.values()]))}
    safe = [o for o in options if o != 'A0' and o in stats and stats[o]['risk'] <= 0.0]
    safe.sort(key=lambda o: (stats[o]['mean_cost'], o))
    return {'rule': 'worst-case-risk/v1-legacy-mean', 'safe_set': safe,
            'chosen': safe[0] if safe else 'A0', 'stats': stats,
            'tie': bool(len(safe) > 1 and abs(stats[safe[0]]['mean_cost'] - stats[safe[1]]['mean_cost']) < 1e-9)}
