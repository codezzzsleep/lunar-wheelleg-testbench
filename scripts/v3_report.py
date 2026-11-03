"""v3 权威统计：只从逐状态原始记录生成唯一结果表。

有效执行配对（SPEC §4）必须同时满足：
  1. FULL/OBS_ONLY 两份 decision 都存在，且带 decision_sha 与非空 state_hash；
  2. FULL/OBS_ONLY 两份 execution 都存在、ok=True、物理结局非空；
  3. execution.action == 该臂 decision.chosen（引用正确决策与实际动作）；
  4. execution.state_mode == 'same_scene'（真值场景续行，不是投射）；
  5. 两臂 decision.state_hash 相同（同一初态 S0）；
  6. 两臂轨迹文件存在、可解析、>=2 帧，且首尾时间与 t_start/t_end 可核对。
不满足的按 one_arm_only / not_run / pipeline_failure / invalid_identity 分类，分母保留。

逐方法误判（分开统计，不混成“方法优劣”）：
  risk_underestimate = 该方法判定选中动作为安全（矩阵里该动作多数通过），
                       但真值执行物理失败；
  over_conservative  = 该方法选 A0 安全停下，而同状态**已验证**存在可行动作
                       （真值参考通行动作，或任一臂实际 pass）；
  reference_unassessed = 真值参考缺失/失败，不硬判过度保守。

  python scripts/v3_report.py --protocol plans/v3_protocol.json
输出 runs/v3/report/v3_results.json（唯一源表）+ .md/.csv（派生）。
"""
import argparse
import csv
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / 'runs/v3'
VALID_OUTCOMES = ('pass', 'safe_stop', 'physical_failure')
PHYS_FAIL_REASONS = ('tipped', 'out_of_bounds', 'out_of_field', 'failed_to_pass',
                     'time_limit', 'bypass')


def jl(p, d=None):
    p = pathlib.Path(p)
    if not p.is_file():
        return d
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


def sha256_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def traj_ok(path, t_start, t_end, tol=0.25):
    """轨迹可读、>=2 帧、首尾时间与 execution 的 t_start/t_end 可核对。"""
    p = pathlib.Path(path)
    if not p.is_file():
        return False, 'missing_trajectory', None
    frames = []
    try:
        for line in p.read_text().splitlines():
            if line.strip():
                frames.append(json.loads(line))
    except Exception as e:  # noqa: BLE001
        return False, f'trajectory_parse_error:{type(e).__name__}', None
    if len(frames) < 2:
        return False, 'trajectory_too_short', len(frames)
    t0, t1 = frames[0].get('t'), frames[-1].get('t')
    if t0 is None or t1 is None:
        return False, 'trajectory_no_time', len(frames)
    if t_start is not None and abs(float(t0) - float(t_start)) > tol:
        return False, f'trajectory_start_mismatch:{t0}!={t_start}', len(frames)
    if t_end is not None and abs(float(t1) - float(t_end)) > tol:
        return False, f'trajectory_end_mismatch:{t1}!={t_end}', len(frames)
    return True, 'ok', len(frames)


def arm_record(sd, arm):
    """返回该臂的 decision/execution/trajectory 完整性与判定。"""
    d = jl(sd / 'decision' / f'decision_{arm}.json')
    e = jl(sd / 'decision' / f'execution_{arm}.json')
    out = {'arm': arm, 'has_decision': bool(d), 'has_execution': bool(e),
           'decision_sha': (d or {}).get('decision_sha'),
           'state_hash': (d or {}).get('state_hash'),
           'chosen': ((d or {}).get('decision') or {}).get('chosen'),
           'matrix_sha': (d or {}).get('matrix_sha256')}
    if e:
        out.update({'action': e.get('action'), 'outcome': e.get('outcome'),
                    'reason': e.get('reason'), 'ok': e.get('ok', True),
                    't_start': e.get('t_start'), 't_end': e.get('t_end'),
                    'state_mode': e.get('state_mode'), 'run_id': e.get('run_id')})
    ok, why, nframes = traj_ok(sd / 'decision' / f'trajectory_{arm}.jsonl',
                               out.get('t_start'), out.get('t_end'))
    out.update({'trajectory_ok': ok, 'trajectory_reason': why,
                'trajectory_frames': nframes})
    return out


def classify_arm(rec):
    if not rec['has_decision'] and not rec['has_execution']:
        return 'not_run'
    if rec['has_execution'] and not rec.get('ok', True):
        return 'pipeline_failure'
    if rec['has_execution'] and rec.get('outcome') == 'pipeline_failure':
        return 'pipeline_failure'
    if not (rec['has_decision'] and rec['has_execution']):
        return 'one_arm_only'
    if not rec.get('outcome') in VALID_OUTCOMES:
        return 'one_arm_only'
    if rec.get('action') != rec.get('chosen'):
        return 'invalid_identity'
    if rec.get('state_mode') != 'same_scene':
        return 'invalid_identity'
    if not rec.get('decision_sha') or not rec.get('state_hash'):
        return 'invalid_identity'
    if not rec['trajectory_ok']:
        return 'invalid_identity'
    return 'valid'


def collect(proto):
    states = []
    for p in sorted((RUNS / 'states').glob('*/state.json')):
        st = jl(p)
        sd = p.parent
        scr = jl(RUNS / 'screen' / f"{st['state_id']}.json")
        row = {'state_id': st['state_id'], 'rock_id': st['rock_id'],
               'level': st['level'], 'view': st['view'], 'H': st['height_m'],
               'hr': st['hr_ratio'], 'screen': scr,
               'observation_sha': st.get('observation_sha256')}
        for arm in ('FULL', 'OBS_ONLY'):
            row[arm] = arm_record(sd, arm)
        row['pair_status'] = _pair_status(row)
        met = jl(sd / 'metrics' / 'summary.json')
        if met:
            row['metrics'] = met['rows']
        ka = jl(sd / 'registration' / 'known_answer' / 'known_answer.json')
        row['known_answer'] = _ka_summary(sd, ka)
        states.append(row)
    return states


def _pair_status(row):
    fa, oa = classify_arm(row['FULL']), classify_arm(row['OBS_ONLY'])
    if fa == 'valid' and oa == 'valid':
        if row['FULL']['state_hash'] != row['OBS_ONLY']['state_hash']:
            return 'invalid_identity'
        if row['FULL']['action'] != row['OBS_ONLY']['action'] and \
                row['FULL']['outcome'] != row['OBS_ONLY']['outcome']:
            return 'executed_pair'
        return 'executed_pair'
    if 'valid' in (fa, oa):
        return 'one_arm_only'
    if 'pipeline_failure' in (fa, oa):
        return 'pipeline_failure'
    if 'invalid_identity' in (fa, oa):
        return 'invalid_identity'
    return 'not_run'


def _ka_summary(sd, ka):
    """已知答案：区分 not_found / not_run / 实测值，不让“未运行”和“通过”并存。"""
    p = sd / 'registration' / 'known_answer' / 'known_answer.json'
    if not p.is_file():
        return {'status': 'missing_record',
                'note': '没有 known_answer.json（不等于已运行并通过）'}
    return {'status': 'measured' if 'pass' in ka else 'record_without_pass',
            'scale_error_pct': ka.get('scale_error_pct'),
            'rotation_error_deg': ka.get('rotation_error_deg'),
            'surface_p95_mm': (ka.get('surface_error_mm') or {}).get('p95'),
            'pass': ka.get('pass'), 'record_sha': sha256_file(p)}


def _truth_feasible(row):
    """同状态是否已验证存在可行动作（真值参考通行动作，或任一臂实际 pass）。"""
    scr = row.get('screen') or {}
    trav = scr.get('traverse') or {}
    truth_pass = any((v or {}).get('success') for v in trav.values())
    arm_pass = any(row[a].get('outcome') == 'pass' for a in ('FULL', 'OBS_ONLY')
                   if row[a].get('outcome'))
    return bool(truth_pass or arm_pass), bool(trav)


def per_method(states):
    out = {}
    for arm in ('FULL', 'OBS_ONLY'):
        m = {'risk_underestimate': 0, 'over_conservative': 0,
             'reference_unassessed': 0, 'safe_stop': 0, 'physical_failure': 0,
             'pass': 0, 'detected_by_screening': 0, 'n_valid_runs': 0}
        for row in states:
            rec = row[arm]
            if classify_arm(rec) != 'valid':
                continue
            m['n_valid_runs'] += 1
            oc = rec['outcome']
            if oc in m:
                m[oc] += 1
            feasible, has_ref = _truth_feasible(row)
            if oc == 'physical_failure':
                # 该方法自己的矩阵里该动作是否被判安全（多数过票）
                dec = jl(RUNS / 'states' / row['state_id'] / 'decision' /
                         f'decision_{arm}.json') or {}
                votes = ((dec.get('decision') or {}).get('votes') or {})
                need = ((dec.get('decision') or {}).get('threshold'))
                safe_pred = (votes.get(rec.get('action')) is not None and need is not None
                             and votes.get(rec.get('action')) >= need)
                if safe_pred:
                    m['risk_underestimate'] += 1
            elif oc == 'safe_stop':
                if not has_ref:
                    m['reference_unassessed'] += 1
                elif feasible:
                    m['over_conservative'] += 1
        out[arm] = m
    return out


def method_compare(states):
    pairs = [r for r in states if r['pair_status'] == 'executed_pair']
    order = {'pass': 3, 'safe_stop': 2, 'physical_failure': 1}
    better = {'FULL': 0, 'OBS_ONLY': 0, 'same': 0}
    rows = []
    for r in pairs:
        a, b = r['FULL']['outcome'], r['OBS_ONLY']['outcome']
        if a == b:
            better['same'] += 1
            who = 'same'
        elif order.get(a, 0) > order.get(b, 0):
            better['FULL'] += 1
            who = 'FULL'
        else:
            better['OBS_ONLY'] += 1
            who = 'OBS_ONLY'
        rows.append({'state_id': r['state_id'], 'FULL': a, 'OBS_ONLY': b,
                     'better': who,
                     'FULL_action': r['FULL']['action'],
                     'OBS_action': r['OBS_ONLY']['action'],
                     'FULL_t': r['FULL'].get('t_end'), 'OBS_t': r['OBS_ONLY'].get('t_end')})
    return {'n_pairs': len(pairs), 'better': better, 'rows': rows}


def hidden_error(states):
    rows = []
    for r in states:
        for m in (r.get('metrics') or []):
            A = m.get('A') or {}
            if not A.get('applicable', True):
                continue
            B = m.get('B') or {}
            C = m.get('C') or {}
            rows.append({'state_id': r['state_id'], 'candidate': m.get('candidate_id'),
                         'A_iou': A.get('iou'), 'A_missing': A.get('missing_rate'),
                         'A_overfill': A.get('overfill_rate'),
                         'B_mae': B.get('mae_mm'), 'B_p95': B.get('p95_mm'),
                         'C_rear': C.get('rear_edge_x_error_mm'),
                         'C_drop': C.get('back_drop_error_mm')})
    def st(key):
        v = [x[key] for x in rows if x.get(key) is not None]
        v = [abs(float(x)) if key in ('C_rear', 'C_drop') else float(x) for x in v]
        if not v:
            return None
        return {'n': len(v), 'mean': round(statistics.mean(v), 5),
                'median': round(statistics.median(v), 5),
                'min': round(min(v), 5), 'max': round(max(v), 5)}
    return {'n_states': len({x['state_id'] for x in rows}),
            'n_candidate_rows': len(rows),
            'coverage_note': ('只覆盖有 metrics/summary.json 的状态与候选；'
                              '未度量状态不在分母里，也不外推'),
            'A_iou': st('A_iou'), 'A_missing': st('A_missing'),
            'A_overfill': st('A_overfill'), 'B_mae': st('B_mae'),
            'B_p95': st('B_p95'), 'C_rear_abs': st('C_rear'),
            'C_drop_abs': st('C_drop')}


def known_answer_all(states):
    out = []
    for r in states:
        ka = r.get('known_answer') or {}
        if ka.get('status') == 'missing_record':
            continue
        out.append({'state_id': r['state_id'], **{k: v for k, v in ka.items()
                                                  if k != 'status'}})
    return {'n_measured': len(out), 'rows': out,
            'n_states_without_record': sum(
                1 for r in states if (r.get('known_answer') or {}).get('status')
                == 'missing_record')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    proto = jl(ROOT / a.protocol, {})
    sel = jl(ROOT / 'runs/v3/selected.json', {})
    states = collect(proto)
    planned = (sel.get('selected') or [])
    by_id = {s['state_id']: s for s in states}
    cls = {'executed_pair': 0, 'one_arm_only': 0, 'not_run': 0,
           'pipeline_failure': 0, 'invalid_identity': 0}
    for sid in planned:
        cls[by_id.get(sid, {}).get('pair_status', 'not_run')] += 1
    screened = [s for s in states if s.get('screen')]
    funnel = {'n_state_dirs': len(states), 'n_screened': len(screened),
              'n_complete_feasible': sum(1 for s in screened
                                         if s['screen'].get('complete_feasible')),
              'n_hidden_sensitive': sum(1 for s in screened
                                        if s['screen'].get('hidden_sensitive')),
              'n_selected': len(planned),
              'layers': {}}
    for s in screened:
        k = s['screen'].get('layer', 'none')
        funnel['layers'][k] = funnel['layers'].get(k, 0) + 1
    res = {
        'schema': 'v3-results/v2',
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'protocol': a.protocol,
        'protocol_sha256': sha256_file(ROOT / a.protocol) if (ROOT / a.protocol).is_file() else None,
        'definitions': {
            'executed_pair': ('两臂 decision+execution 齐全、action 与 decision 一致、'
                              'state_mode=same_scene、同一 state_hash、轨迹可读且首尾时间可核'),
            'risk_underestimate': '该方法判定选中动作安全但真值执行物理失败',
            'over_conservative': '该方法安全停下，而同状态已验证存在可行动作',
            'reference_unassessed': '真值参考缺失/失败，不硬判过度保守',
        },
        'funnel': funnel,
        'planned_states': planned,
        'classification': cls,
        'per_method': per_method(states),
        'method_compare': method_compare(states),
        'hidden_error': hidden_error(states),
        'known_answer': known_answer_all(states),
        'states': states,
    }
    out = ROOT / 'runs/v3/report'
    out.mkdir(parents=True, exist_ok=True)
    body = json.dumps(res, ensure_ascii=False, indent=2)
    (out / 'v3_results.json').write_text(body)
    # 内容 SHA 写 sidecar：JSON 里不能再嵌自己的 SHA（会自指）
    digest = sha256_file(out / 'v3_results.json')
    (out / 'v3_results.json.sha256').write_text(digest + '\n')
    res['report_sha256'] = digest
    # 派生 CSV
    with (out / 'v3_table.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['state_id', 'pair_status', 'FULL_action', 'FULL_outcome',
                    'OBS_action', 'OBS_outcome', 'FULL_t', 'OBS_t'])
        for s in states:
            if s['pair_status'] == 'not_run' and not (
                    s['FULL']['has_decision'] or s['OBS_ONLY']['has_decision']):
                continue
            w.writerow([s['state_id'], s['pair_status'],
                        s['FULL'].get('action'), s['FULL'].get('outcome'),
                        s['OBS_ONLY'].get('action'), s['OBS_ONLY'].get('outcome'),
                        s['FULL'].get('t_end'), s['OBS_ONLY'].get('t_end')])
    print(json.dumps({'report_sha256': res['report_sha256'],
                      'generated_at': res['generated_at'],
                      'classification': cls,
                      'method_compare': res['method_compare']['better'],
                      'n_pairs': res['method_compare']['n_pairs'],
                      'hidden_rows': res['hidden_error']['n_candidate_rows']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
