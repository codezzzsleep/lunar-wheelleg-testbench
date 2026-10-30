"""
V7-R1 §7.1：决策矩阵合同校验（生产函数，供闭环与验收器共同调用）。

校验“候选 × 动作 × 状态身份 × 土壤身份”四元组：
  · 每个四元组必须恰好一格（重复 = 错；缺格 = 错，除非显式 not_applicable）；
  · 不允许同一 (候选,动作,状态) 用不同 seed 覆盖不同土壤记录；
  · A0 不得进入 safe_set；
  · 无候选时必须 chosen=A0 且写明原因；
  · decision_sha 必须能由内容重算出来。
"""
import hashlib
import json


def _key(r):
    return (r.get('candidate'), r.get('option'), r.get('state_hash'), r.get('soil_config'))


def validate(matrix_rows, decision, expected=None, not_applicable=None):
    """返回 {'ok': bool, 'errors': [str], 'stats': {...}}。"""
    errs = []
    seen = {}
    for r in matrix_rows:
        k = _key(r)
        if None in k:
            errs.append(f'单元格缺关键字段：{k}')
            continue
        seen.setdefault(k, 0)
        seen[k] += 1
    dups = {k: v for k, v in seen.items() if v > 1}
    if dups:
        errs.append(f'重复单元格 {len(dups)} 个：{list(dups)[:3]}')

    na = {(x.get('candidate'), x.get('action'), x.get('state_hash'), x.get('soil_config'))
          for x in (not_applicable or [])}
    if expected:
        want = {(c, a, s, so) for c in expected.get('candidates', [])
                for a in expected.get('actions', []) for s in expected.get('states', [])
                for so in expected.get('soil_configs', [])}
        missing = [k for k in want if k not in seen and k not in na]
        if missing:
            errs.append(f'缺格 {len(missing)} 个：{missing[:3]}')

    # 同一 (候选,动作,状态) 出现多个土壤身份是允许的；但同一身份用不同 seed 覆盖则不允许
    by_cas = {}
    for r in matrix_rows:
        cas = (r.get('candidate'), r.get('option'), r.get('state_hash'))
        by_cas.setdefault(cas, set()).add(r.get('soil_config'))
    # 同一四元组内 seed 必须唯一（不同 seed 只能对应不同 state_hash）
    seed_by_state = {}
    for r in matrix_rows:
        seed_by_state.setdefault(r.get('state_hash'), set()).add(r.get('state_seed'))
    bad_seed = {s: v for s, v in seed_by_state.items() if len(v) > 1}
    if bad_seed:
        errs.append(f'同一 state_hash 对应多个 seed：{bad_seed}')

    safe = set(decision.get('safe_set') or [])
    if 'A0' in safe:
        errs.append('A0 不得进入 safe_set')

    if expected and not expected.get('candidates'):
        if decision.get('chosen') != 'A0' or not decision.get('reason'):
            errs.append('无候选时必须 chosen=A0 且写明原因')

    sha = decision.get('decision_sha')
    if sha:
        payload = json.dumps({k: v for k, v in decision.items() if k != 'decision_sha'},
                             ensure_ascii=False, sort_keys=True)
        if hashlib.sha256(payload.encode()).hexdigest() != sha:
            errs.append('decision_sha 与内容不一致')

    want = set()
    if expected:
        want = {(c, a, s_, so) for c in expected.get('candidates', [])
                for a in expected.get('actions', []) for s_ in expected.get('states', [])
                for so in expected.get('soil_configs', [])}
    n_missing = len([k for k in want if k not in seen and k not in na])
    stats = {'n_cells': len(matrix_rows), 'n_unique': len(seen), 'n_dup': len(dups),
             'n_missing': n_missing, 'n_not_applicable': len(na),
             'n_states': len(seed_by_state), 'n_expected_cells': len(want)}
    return {'ok': not errs, 'errors': errs, 'stats': stats}


def load_and_validate(matrix_path, decisions_path, expected=None):
    rows = [json.loads(l) for l in open(matrix_path) if l.strip()]
    dj = json.loads(open(decisions_path).read())
    dec = dj.get('decision', dj)
    dec = dict(dec)
    dec.setdefault('decision_sha', dj.get('decision_sha'))
    return validate(rows, dec, expected, not_applicable=dj.get('not_applicable'))
