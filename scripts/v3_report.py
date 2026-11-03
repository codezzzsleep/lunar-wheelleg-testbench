"""v3 结果汇总：筛选漏斗、FULL/OBS_ONLY 三结局、隐藏误差、多数/最坏/首候选。

  python scripts/v3_report.py --protocol plans/v3_protocol.json
输出 runs/v3/report/{v3_results.json, v3_results.md, v3_table.csv}
"""
import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / 'runs/v3'


def jload(p, default=None):
    p = pathlib.Path(p)
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def collect(proto):
    states = []
    for p in sorted((RUNS / 'states').glob('*/state.json')):
        st = jload(p)
        d = p.parent
        scr = jload(RUNS / 'screen' / f"{st['state_id']}.json")
        row = {'state_id': st['state_id'], 'rock_id': st['rock_id'], 'level': st['level'],
               'view': st['view'], 'H': st['height_m'], 'hr': st['hr_ratio'],
               'screen': scr}
        arms = {}
        for arm in ('FULL', 'OBS_ONLY'):
            dec = jload(d / 'decision' / f'decision_{arm}.json')
            ex = jload(d / 'decision' / f'execution_{arm}.json')
            if dec:
                arms[arm] = {'chosen': dec['decision']['chosen'],
                             'votes': dec['decision']['votes'],
                             'n_valid': dec['decision']['n_valid'],
                             'n_unique': dec['decision']['n_unique_geometries'],
                             'reason': dec['decision']['reason'],
                             'mean_cost': dec['decision']['mean_cost_s'],
                             'decision_sha': dec.get('decision_sha'),
                             'execution': ({k: ex.get(k) for k in
                                            ('action', 'outcome', 'reason', 'final_x',
                                             't_end', 't_start', 'wall_s', 'run_id')}
                                           if ex else None)}
        if arms:
            row['arms'] = arms
        met = jload(d / 'metrics' / 'summary.json')
        if met:
            row['metrics'] = met['rows']
        states.append(row)
    return states


def summarize(states, proto):
    n_states = len(states)
    screened = [s for s in states if s.get('screen')]
    feas = [s for s in screened if s['screen'].get('complete_feasible')]
    sens = [s for s in screened if s['screen'].get('hidden_sensitive')]
    sel = [s for s in screened if s['screen'].get('selected')]
    layers = {}
    for s in screened:
        l = s['screen'].get('layer', 'none')
        layers[l] = layers.get(l, 0) + 1
    executed = [s for s in states if s.get('arms')]
    outcomes = {'FULL': {}, 'OBS_ONLY': {}}
    pairs = []
    for s in executed:
        a, b = s['arms'].get('FULL'), s['arms'].get('OBS_ONLY')
        if not (a and b):
            continue
        ea = (a.get('execution') or {}).get('outcome')
        eb = (b.get('execution') or {}).get('outcome')
        for arm, e in (('FULL', ea), ('OBS_ONLY', eb)):
            outcomes[arm][e] = outcomes[arm].get(e, 0) + 1
        pairs.append({'state_id': s['state_id'], 'FULL': ea, 'OBS_ONLY': eb,
                      'same': ea == eb,
                      'FULL_action': a['chosen'], 'OBS_action': b['chosen']})
    risk_under = sum(1 for p in pairs if p['FULL'] == 'physical_failure'
                     and p['OBS_ONLY'] == 'pass')
    over_cons = sum(1 for p in pairs if p['FULL'] == 'safe_stop'
                    and p['OBS_ONLY'] == 'pass')
    return {
        'n_pool_rocks': len(proto['grid']['rocks']),
        'n_states_captured': n_states,
        'n_screened': len(screened),
        'n_complete_feasible': len(feas),
        'n_hidden_sensitive': len(sens),
        'n_selected': len(sel),
        'layers': layers,
        'n_executed_states': len(pairs),
        'outcomes': outcomes,
        'FULL_better_than_OBS': sum(1 for p in pairs if p['FULL'] == 'pass'
                                    and p['OBS_ONLY'] != 'pass'),
        'OBS_better_than_FULL': sum(1 for p in pairs if p['OBS_ONLY'] == 'pass'
                                    and p['FULL'] != 'pass'),
        'same_outcome': sum(1 for p in pairs if p['same']),
        'risk_underestimate': risk_under,
        'over_conservative': over_cons,
        'pairs': pairs,
    }


def _stat(x):
    import statistics
    if not x:
        return None
    return {'n': len(x), 'mean': round(float(statistics.mean(x)), 4),
            'median': round(float(statistics.median(x)), 4),
            'min': round(float(min(x)), 4), 'max': round(float(max(x)), 4)}


def hidden_error(rows):
    out = {'n_rows': 0, 'A_iou': [], 'A_missing': [], 'A_overfill': [],
           'B_mae': [], 'B_p95': [], 'C_rear_abs': [], 'C_drop_abs': []}
    for r in rows:
        for m in (r.get('metrics') or []):
            if not m.get('A'):
                continue
            A, B, C = m['A'], m.get('B') or {}, m.get('C') or {}
            if not A.get('applicable', True):
                continue
            out['n_rows'] += 1
            for key, val in (('A_iou', A.get('iou')), ('A_missing', A.get('missing_rate')),
                             ('A_overfill', A.get('overfill_rate')),
                             ('B_mae', B.get('mae_mm')), ('B_p95', B.get('p95_mm'))):
                if val is not None:
                    out[key].append(val)
            if C.get('rear_edge_x_error_mm') is not None:
                out['C_rear_abs'].append(abs(C['rear_edge_x_error_mm']))
            if C.get('back_drop_error_mm') is not None:
                out['C_drop_abs'].append(abs(C['back_drop_error_mm']))
    return {k: (v if k == 'n_rows' else _stat(v)) for k, v in out.items()}


def markdown(states, summ, herr):
    L = []
    L.append('# v3 主结果（真实扫描岩石 · FULL vs OBS_ONLY）\n')
    L.append('## 1 筛选漏斗\n')
    L.append('| 项 | 值 |')
    L.append('| --- | --- |')
    for k in ('n_pool_rocks', 'n_states_captured', 'n_screened', 'n_complete_feasible',
              'n_hidden_sensitive', 'n_selected'):
        L.append(f'| {k} | {summ[k]} |')
    L.append(f'| 分层（动作不同/结局不同） | {summ["layers"]} |\n')
    L.append('## 2 三结局（FULL vs OBS_ONLY，同一 S0）\n')
    L.append(f'- 执行状态数：{summ["n_executed_states"]}')
    L.append(f'- FULL：{summ["outcomes"]["FULL"]}')
    L.append(f'- OBS_ONLY：{summ["outcomes"]["OBS_ONLY"]}')
    L.append(f'- 结局相同：{summ["same_outcome"]}；FULL 更好：{summ["FULL_better_than_OBS"]}；'
             f'OBS_ONLY 更好：{summ["OBS_better_than_FULL"]}')
    L.append(f'- 风险低估：{summ["risk_underestimate"]}；过度保守：{summ["over_conservative"]}\n')
    L.append('## 3 逐状态\n')
    L.append('| 状态 | H(m) | 真值选择 | OBS 选择 | FULL 执行 | OBS 执行 |')
    L.append('| --- | --- | --- | --- | --- | --- |')
    for s in states:
        if not s.get('arms'):
            continue
        sc = s.get('screen') or {}
        L.append(f"| {s['state_id']} | {s['H']:.3f} | {sc.get('truth_plan', {}).get('chosen')} | "
                 f"{sc.get('obs_plan', {}).get('chosen')} | "
                 f"{(s['arms']['FULL'].get('execution') or {}).get('outcome')} | "
                 f"{(s['arms']['OBS_ONLY'].get('execution') or {}).get('outcome')} |")
    L.append('\n## 4 隐藏区误差（候选分布，不是单个最好案例）\n')
    for k, v in herr.items():
        if k == 'n_rows':
            L.append(f'- 候选-状态行数：{v}')
        elif v:
            L.append(f'- {k}: {v}')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    states = collect(proto)
    summ = summarize(states, proto)
    herr = hidden_error(states)
    out = ROOT / 'runs/v3/report'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'v3_results.json').write_text(json.dumps(
        {'schema': 'v3-results/v1', 'protocol': a.protocol,
         'summary': summ, 'hidden_error': herr, 'states': states},
        ensure_ascii=False, indent=2))
    (out / 'v3_results.md').write_text(markdown(states, summ, herr))
    with (out / 'v3_table.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['state_id', 'rock', 'level', 'view', 'H_m', 'truth_action', 'obs_action',
                    'FULL_action', 'FULL_outcome', 'OBS_action', 'OBS_outcome',
                    'full_votes', 'obs_votes', 'hidden_sensitive', 'selected'])
        for s in states:
            ar = s.get('arms') or {}
            sc = s.get('screen') or {}
            w.writerow([s['state_id'], s['rock_id'], s['level'], s['view'], f"{s['H']:.4f}",
                        sc.get('truth_plan', {}).get('chosen'),
                        sc.get('obs_plan', {}).get('chosen'),
                        ar.get('FULL', {}).get('chosen'),
                        (ar.get('FULL', {}).get('execution') or {}).get('outcome'),
                        ar.get('OBS_ONLY', {}).get('chosen'),
                        (ar.get('OBS_ONLY', {}).get('execution') or {}).get('outcome'),
                        json.dumps(ar.get('FULL', {}).get('votes', {}), ensure_ascii=False),
                        json.dumps(ar.get('OBS_ONLY', {}).get('votes', {}), ensure_ascii=False),
                        sc.get('hidden_sensitive'), sc.get('selected')])
    print(json.dumps({'n_states': len(states), 'n_selected': summ['n_selected'],
                      'n_executed': summ['n_executed_states'],
                      'out': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
