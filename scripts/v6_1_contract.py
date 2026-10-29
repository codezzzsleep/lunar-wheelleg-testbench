"""
V6.1：预演/决策/执行的完整性合同（D）。

合同的目的是：**在便宜的地方失败**。正式跑几十个 30 s episode 之前，先用显式输入
检查「该有的记录是不是都在、决策是不是真的先落盘、执行是不是引用了那份决策」。

检查项：
  C1 预演矩阵完整：每个 (候选, 动作, 初态) 恰好一行；
  C2 候选不缺失：期望的候选全部出现；
  C3 初态不缺失：每个候选下期望的 seed 全部出现；
  C4 决策完整：rule / safe_set / chosen / stats / decision_sha 齐备且自洽；
  C5 执行引用决策：每条执行行带 decision_sha，且与决策文件一致；
  C6 无重复：(phase, 候选, 动作, 初态) 唯一；
  C7 决策先于执行：决策的 written_at 早于最早执行行的 started_at；
  C8 无越权动作：执行只允许 chosen / A0 / R1（参照基线）。

  .venv/bin/python scripts/v6_1_contract.py \
      --rehearsal r.jsonl --execution e.jsonl --decision d.json \
      --expect expect.json --out report.json
  .venv/bin/python scripts/v6_1_contract.py --self-test
"""
import argparse
import json
import pathlib
import sys


def load_jsonl(p):
    rows = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def check(rehearsal, execution, decision, expect):
    problems = []
    checks = {}

    def add(name, ok, detail=''):
        checks[name] = {'pass': bool(ok), 'detail': detail}
        if not ok:
            problems.append({'check': name, 'detail': detail})

    cands = list(expect.get('candidates') or [])
    options = list(expect.get('options') or [])
    seeds = [int(x) for x in (expect.get('seeds') or [])]

    # C2 候选不缺失
    seen_c = {r.get('hypothesis_id') for r in rehearsal}
    missing_c = [c for c in cands if c not in seen_c]
    add('C2_candidates_present', not missing_c, f'missing={missing_c}')

    # C3 初态不缺失（每个候选 × 每个 seed 至少一行）
    missing_seed = []
    for c in cands:
        for sd in seeds:
            if not any(r.get('hypothesis_id') == c and int(r.get('seed', -1)) == sd
                       for r in rehearsal):
                missing_seed.append(f'{c}/seed{sd}')
    add('C3_seeds_present', not missing_seed, f'missing={missing_seed[:12]}')

    # C1 矩阵完整（候选 × 非 A0 动作 × seed 恰好一行）
    expected = {(c, o, sd) for c in cands for o in options if o != 'A0' for sd in seeds}
    got = {}
    for r in rehearsal:
        k = (r.get('hypothesis_id'), r.get('option'), int(r.get('seed', -1)))
        got[k] = got.get(k, 0) + 1
    missing_cells = sorted(expected - set(got))
    add('C1_matrix_complete', not missing_cells,
        f'n_expected={len(expected)} n_got={len(got)} missing={len(missing_cells)} '
        f'first={missing_cells[:6]}')

    # C6 无重复
    dups = sorted(k for k, v in got.items() if v > 1)
    add('C6_no_duplicates', not dups, f'dups={dups[:6]}')

    # C4 决策完整
    need = ('rule', 'safe_set', 'chosen', 'stats', 'decision_sha')
    miss = [k for k in need if k not in (decision or {})]
    add('C4_decision_complete', not miss, f'missing_keys={miss}')
    if not miss:
        chosen = decision.get('chosen')
        ok_choice = (chosen == 'A0') or (chosen in (decision.get('safe_set') or []))
        add('C4b_chosen_in_safe_set', ok_choice,
            f"chosen={chosen} safe_set={decision.get('safe_set')}")

    # C5 执行引用决策
    dsha = (decision or {}).get('decision_sha')
    bad_ref = [r for r in execution if dsha and r.get('decision_sha') != dsha]
    add('C5_execution_references_decision', not bad_ref,
        f'n_bad={len(bad_ref)} decision_sha={dsha}')

    # C8 无越权动作
    allowed = {decision.get('chosen'), 'A0', 'R1'}
    bad_opt = sorted({r.get('option') for r in execution} - allowed)
    add('C8_only_allowed_actions', not bad_opt, f'unexpected={bad_opt}')

    # C7 决策先于执行
    try:
        dt = float(decision.get('written_at'))
        first = min(float(r.get('started_at')) for r in execution)
        add('C7_decision_before_execution', dt <= first,
            f'decision_at={dt} first_exec_at={first}')
    except Exception as e:
        add('C7_decision_before_execution', False, f'缺少时间戳: {e}')

    return {'schema': 'contract/v6_1', 'checks': checks,
            'n_checks': len(checks),
            'n_pass': sum(1 for v in checks.values() if v['pass']),
            'ok': all(v['pass'] for v in checks.values()),
            'problems': problems}


def self_test():
    """内置反例：每个反例都必须被检出。"""
    base_c = ['A', 'B']
    opts = ['R1', 'R2', 'S1', 'A0']
    seeds = [0, 1]
    rehears = []
    for c in base_c:
        for o in opts:
            if o == 'A0':
                continue
            for sd in seeds:
                rehears.append({'hypothesis_id': c, 'option': o, 'seed': sd,
                                'success': True, 't_end': 5.0})
    dec = {'rule': 'worst-case-risk/v2', 'safe_set': ['S1'], 'chosen': 'S1',
           'stats': {'S1': {'risk': 0.0}}, 'decision_sha': 'abc123', 'written_at': 100.0}
    exe = [{'hypothesis_id': 'truth', 'option': 'S1', 'seed': 0, 'started_at': 101.0,
            'decision_sha': 'abc123', 'success': True},
           {'hypothesis_id': 'truth', 'option': 'A0', 'seed': 0, 'started_at': 102.0,
            'decision_sha': 'abc123', 'success': False}]
    expect = {'candidates': base_c, 'options': opts, 'seeds': seeds}
    out = {}

    r = check(rehears, exe, dec, expect)
    out['baseline_ok'] = r['ok']

    # 反例1：缺整份候选
    r1 = check([x for x in rehears if x['hypothesis_id'] != 'B'], exe, dec, expect)
    out['detect_missing_candidate'] = any(p['check'] == 'C2_candidates_present'
                                          for p in r1['problems'])
    # 反例2：缺整个 seed
    r2 = check([x for x in rehears if not (x['hypothesis_id'] == 'A' and x['seed'] == 1)],
               exe, dec, expect)
    out['detect_missing_seed'] = any(p['check'] == 'C3_seeds_present'
                                     for p in r2['problems'])
    # 反例3：重复记录
    r3 = check(rehears + [dict(rehears[0])], exe, dec, expect)
    out['detect_duplicate'] = any(p['check'] == 'C6_no_duplicates' for p in r3['problems'])
    # 反例4：执行引用错误 decision_sha
    r4 = check(rehears, [dict(x, decision_sha='zzz') for x in exe], dec, expect)
    out['detect_wrong_decision_ref'] = any(p['check'] == 'C5_execution_references_decision'
                                           for p in r4['problems'])
    # 反例5：执行先于决策
    r5 = check(rehears, [dict(x, started_at=50.0) for x in exe], dec, expect)
    out['detect_exec_before_decision'] = any(p['check'] == 'C7_decision_before_execution'
                                             for p in r5['problems'])
    # 反例6：执行了 safe_set 之外的动作
    r6 = check(rehears, exe + [{'hypothesis_id': 'truth', 'option': 'L2', 'seed': 0,
                                'started_at': 103.0, 'decision_sha': 'abc123'}], dec, expect)
    out['detect_unexpected_action'] = any(p['check'] == 'C8_only_allowed_actions'
                                          for p in r6['problems'])
    # 反例7：决策缺 decision_sha
    r7 = check(rehears, exe, {k: v for k, v in dec.items() if k != 'decision_sha'}, expect)
    out['detect_incomplete_decision'] = any(p['check'] == 'C4_decision_complete'
                                            for p in r7['problems'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rehearsal')
    ap.add_argument('--execution')
    ap.add_argument('--decision')
    ap.add_argument('--expect')
    ap.add_argument('--out')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        res = self_test()
        bad = [k for k, v in res.items() if not v]
        print(json.dumps({'self_test': res, 'all_pass': not bad}, ensure_ascii=False, indent=1))
        return 0 if not bad else 1
    rep = check(load_jsonl(a.rehearsal), load_jsonl(a.execution),
                json.loads(pathlib.Path(a.decision).read_text()),
                json.loads(pathlib.Path(a.expect).read_text()))
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'ok': rep['ok'], 'n_pass': rep['n_pass'], 'n_checks': rep['n_checks'],
                      'problems': rep['problems'][:6]}, ensure_ascii=False))
    return 0 if rep['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
