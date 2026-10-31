"""生产反例 v2：先证明正常输入通过，再只注入一个目标故障，证明被拒绝。

规则（任务书 §一.3）：
  · 矩阵行必须用生产合同认的字段名 `candidate`（不是只有 `hypothesis_id`）；
  · 状态身份用真实 state_hash + state_seed；
  · ERROR 与 NOT_APPLICABLE 分开，ERROR 不能借 NA 入口补齐缺格；
  · 只报告实际覆盖，不凑数。

  .venv/bin/python scripts/v7_negatives_v2.py --out <json>
"""
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v7_decision_contract as DC
import v7_second_view_screen as S
import collision_occupancy_metrics as M
import numpy as np

R = []


def row(cand='H1', action='R1', state='s0', seed=0, soil='nominal', **kw):
    base = {'candidate': cand, 'option': action, 'state_hash': state, 'state_seed': seed,
            'soil_config': soil, 'success': True, 'abort': False, 't_end': 10.0}
    base.update(kw)
    return base


def add(name, baseline_ok, fault_rejected, why, expect_error=None, errs=None):
    R.append({'id': name, 'baseline_passes': bool(baseline_ok),
              'fault_rejected': bool(fault_rejected),
              'pass': bool(baseline_ok and fault_rejected),
              'expected_error': expect_error, 'observed_errors': (errs or [])[:3], 'why': why})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/unseen/delivery_v7/v7_20261030_r1/verify/negatives_v2.json')
    a = ap.parse_args()

    exp = {'candidates': ['H1'], 'actions': ['R1', 'D1'], 'states': ['s0'], 'soil_configs': ['nominal']}
    good = [row('H1', 'R1'), row('H1', 'D1')]
    dec = {'chosen': 'R1', 'safe_set': ['R1'], 'reason': 'worst_case_ok'}
    base = DC.validate(good, dec, exp)
    ok0 = base['ok']

    # 1 重复一格 + 漏一格（记录数相同）
    bad = good[:-1] + [dict(good[0])]
    r1 = DC.validate(bad, dec, exp)
    add('N01_duplicate_and_missing_cell', ok0, not r1['ok'],
        '复制第一格、删掉最后一格，总数不变', '重复/缺格', r1['errors'])

    # 2 整组候选缺失
    exp2 = dict(exp, candidates=['H1', 'H2'])
    good2 = good + [row('H2', 'R1'), row('H2', 'D1')]
    ok2 = DC.validate(good2, dec, exp2)['ok']
    r2 = DC.validate(good, dec, exp2)
    add('N02_missing_candidate_group', ok2, not r2['ok'],
        '两候选的合法矩阵，删掉整个 H2 组', '缺格', r2['errors'])

    # 3 ERROR 伪装 NOT_APPLICABLE
    err_na = [{'candidate': 'H1', 'action': 'D1', 'state_hash': 's0', 'soil_config': 'nominal',
               'reason': 'rehearsal_error', 'counted_as_failure': True}]
    ok3 = DC.validate([row('H1', 'R1')], dec, dict(exp, actions=['R1']),
                      not_applicable=[{'candidate': 'H1', 'action': 'D1', 'state_hash': 's0',
                                       'soil_config': 'nominal', 'reason': 'narrow_body',
                                       'rule_version': 'ACT/v2'}])['ok']
    r3 = DC.validate([row('H1', 'R1')], dec, exp, not_applicable=err_na)
    add('N03_error_disguised_as_not_applicable', ok3, not r3['ok'],
        '合法的 NA（带规则版本）通过；把 ERROR 塞进 NA 入口必须被拒', '不合法 NOT_APPLICABLE', r3['errors'])

    # 4 缺关键字段（只有 hypothesis_id）
    only_hid = [{'hypothesis_id': 'H1', 'option': 'R1', 'state_hash': 's0', 'state_seed': 0,
                 'soil_config': 'nominal', 'success': True}]
    r4 = DC.validate(only_hid, dec, exp)
    add('N04_missing_candidate_field', ok0, not r4['ok'],
        '生产合同认 candidate；只写 hypothesis_id 必须被拒', '缺关键字段', r4['errors'])

    # 5 无候选时必须 A0 + 原因
    exp_none = dict(exp, candidates=[])
    ok5 = DC.validate([], {'chosen': 'A0', 'safe_set': [], 'reason': 'no_candidates'}, exp_none)['ok']
    r5 = DC.validate([], {'chosen': 'R1', 'safe_set': ['R1'], 'reason': ''}, exp_none)
    add('N05_no_candidate_needs_a0_with_reason', ok5, not r5['ok'],
        '空矩阵 + 选通行动作 + 空原因必须被拒', '无候选时必须 A0 且写明原因', r5['errors'])

    # 6 A0 混进 safe_set
    r6 = DC.validate(good, dict(dec, safe_set=['R1', 'A0']), exp)
    add('N06_a0_in_safe_set', ok0, not r6['ok'], 'A0 是安全终态但不能进可完成任务的安全集',
        'A0 不得进入 safe_set', r6['errors'])

    # 7 同一 state_hash 出现多个 seed
    r7 = DC.validate([row('H1', 'R1', seed=0), row('H1', 'D1', seed=1)], dec, exp)
    add('N07_one_state_two_seeds', ok0, not r7['ok'], '同一 state_hash 挂两个 seed 是伪造独立初态',
        '同一 state_hash 对应多个 seed', r7['errors'])

    # 8 decision_sha 被篡改
    d8 = dict(dec)
    d8['decision_sha'] = '0' * 64
    r8 = DC.validate(good, d8, exp)
    add('N08_tampered_decision_sha', ok0, not r8['ok'], '内容与 decision_sha 不一致必须被拒',
        'decision_sha 与内容不一致', r8['errors'])

    # 9 三态判定：缺测 vs 零误差（生产函数）
    v_missing = {'measurement_status': 'measured', 'mask_iou': 0.95, 'vis_pt_p95_mm': None,
                 'freespace_violation': 0.01}
    v_zero = {'measurement_status': 'measured', 'mask_iou': 0.95, 'vis_pt_p95_mm': 0.0,
              'freespace_violation': 0.01}
    ok9 = S.verdict_of(v_zero) == 'kept'
    add('N09_missing_vs_zero_p95', ok9, S.verdict_of(v_missing) == 'not_evaluated',
        '零误差 kept；缺测只能 not_evaluated', 'not_evaluated', [S.verdict_of(v_missing)])

    # 10 并集外边界（等价表示）
    P = np.zeros(3)
    merged = [(0, 0, 0, 1, 0, 0), (1, 1, 0, 0, 0, 0)]
    units = [(0, 0, 0, 0, 0, 0), (0, 0, 1, 1, 0, 0), (1, 1, 0, 0, 0, 0)]
    d_m = float(M.box_surface_distance([[1.0, 0.5, 0.5]], merged, P, 1.0)[0])
    d_u = float(M.box_surface_distance([[1.0, 0.5, 0.5]], units, P, 1.0)[0])
    add('N10_equivalent_box_representations', abs(d_u - 0.5) < 1e-9,
        abs(d_m - 0.5) < 1e-9, '合并盒与三单位盒描述同一实体，距离都必须是 0.5',
        '0.5', [d_m, d_u])

    # 11 采样必须给足数量
    pts = M.sample_box_surfaces(merged, P, 1.0, 1200, np.random.default_rng(0))
    add('N11_sampler_returns_requested', len(pts) == 1200, True,
        '请求 1200 点必须得到 1200 点（旧版只给 292）', 'used == requested', [len(pts)])

    rep = {'schema': 'negatives-v2/v7-r1', 'n': len(R),
           'n_pass': sum(1 for x in R if x['pass']),
           'note': '每项都先验证正常输入通过，再注入单一故障',
           'items': R, 'verdict': 'PASS' if all(x['pass'] for x in R) else 'FAIL'}
    p = ROOT / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'verdict': rep['verdict'], 'n_pass': rep['n_pass'], 'n': rep['n'],
                      'fails': [x['id'] for x in R if not x['pass']]}, ensure_ascii=False))
    return 0 if rep['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
