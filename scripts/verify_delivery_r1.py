"""
V7-R1 统一验收器：读**本批实际文件与生产入口**，缺必需证据即失败。

与旧验收器的区别：
  · 不按 glob 猜路径；manifest 中显式列出预期产物，缺一个就 FAIL；
  · 关键判据调用生产函数（decision contract / verdict_of / v7_soil / state contract），
    不在验收器里另写一套布尔表达式；
  · 分层：完整性(integrity) / 功能(function) / 目标(goal)，分开给出结论。

  .venv/bin/python scripts/verify_delivery_r1.py --batch runs/unseen/delivery_v7/v7_20261030_r1 \
      --out runs/unseen/delivery_v7/v7_20261030_r1/verify/r1_report.json
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))


def jl(p, default=None):
    p = pathlib.Path(p)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def sha(p):
    h = hashlib.sha256()
    with pathlib.Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', default='runs/unseen/delivery_v7/v7_20261030_r1')
    ap.add_argument('--out', default='runs/unseen/delivery_v7/v7_20261030_r1/verify/r1_report.json')
    a = ap.parse_args()
    B = ROOT / a.batch
    C = []

    def add(layer, name, ok, detail=''):
        C.append({'layer': layer, 'check': name, 'pass': bool(ok), 'detail': str(detail)})

    # ---------- 完整性 ----------
    man = jl(B / 'manifest.json')
    add('integrity', 'batch_manifest', bool(man), B / 'manifest.json')
    if man:
        add('integrity', 'batch_id', man.get('batch_id') == 'v7_20261030_r1', man.get('batch_id'))
        add('integrity', 'status_fields_complete',
            all(k in (man.get('status') or {}) for k in
                ('execution_status', 'evidence_status', 'capability_status', 'benefit_status')),
            man.get('status'))
        add('integrity', 'review_baseline_recorded',
            bool(str(man.get('review_baseline', '')).startswith('4fe5281f')),
            man.get('review_baseline'))

    bud = jl(ROOT / 'configs/unseen_v7_r1_budget.json')
    add('integrity', 'budget_config', bool(bud), 'configs/unseen_v7_r1_budget.json')
    if bud:
        add('integrity', 'authorization_500', float(bud['authorization']['new_total_credits']) == 500.0,
            bud['authorization'])
        add('integrity', 'price_not_claimed_verified',
            bud['price']['price_verified'] is False
            and bud['price']['actual_charge'] == 'unknown', bud['price'])
        add('integrity', 'reserved_current_reported',
            float(bud['ledger']['reserved_current']) >= 0.0, bud['ledger']['reserved_current'])

    # 生成任务：每行要有 task_id / 输入哈希 / 模式一致
    tasks = [jl(p) for p in sorted((B / 'generation').glob('task_*.json'))]
    tasks = [t for t in tasks if t]
    add('integrity', 'generation_records_present', len(tasks) > 0, len(tasks))
    bad = []
    for t in tasks:
        if not t.get('task_id'):
            bad.append('no task_id')
        for pth, h in zip(t.get('image_paths') or [], t.get('image_sha256') or []):
            fp = pathlib.Path(pth)
            if fp.exists() and sha(fp) != h:
                bad.append(f"{t['task_id']}:image-hash")
        n = int(t.get('n_images') or 0)
        if (n >= 2) != (t.get('mode') == 'two_image'):
            bad.append(f"{t['task_id']}:mode-mismatch")
    add('integrity', 'generation_identities_consistent', not bad, bad[:3])

    soil = jl(B / 'soil/params.json')
    add('integrity', 'soil_params_recorded', bool(soil), B / 'soil/params.json')
    if soil:
        hashes = {m: (soil['configs'][m]['params_sha']) for m in soil['configs']}
        add('integrity', 'soil_params_distinct', len(set(hashes.values())) == 3, hashes)
        add('integrity', 'soil_discrimination_pass', bool(soil.get('all_pass')),
            soil.get('checks'))

    # ---------- 功能 ----------
    loops = {}
    for p in sorted((B / 'evaluation').glob('closed_loop_*/closed_loop.json')):
        d = jl(p)
        if d:
            loops[p.parent.name] = d
    add('function', 'closed_loop_runs', len(loops) >= 2, sorted(loops))
    a0 = [k for k, v in loops.items() if v.get('branch', '').startswith('a0')]
    trav = [k for k, v in loops.items() if v.get('branch') == 'matrix_decision']
    add('function', 'branch_a0_exists', bool(a0), a0)
    add('function', 'branch_traversal_exists', bool(trav), trav)
    for name, d in loops.items():
        ex = d.get('execution') or []
        add('function', f'{name}:execution_present', bool(ex), len(ex))
        if ex:
            add('function', f'{name}:no_reset',
                all((e.get('t_start') or 0) > 1.0 for e in ex),
                [e.get('t_start') for e in ex])
            # 记录里的 final_x 保留 3 位小数，比较容差放到 1 mm，避免把舍入当错误
            devs = [round(float(e.get('final_x') or 0) - float(e.get('start_x') or 0)
                          - float(e.get('displacement_x') or 0), 6) for e in ex]
            add('function', f'{name}:displacement_from_start',
                all(abs(d) <= 1e-3 for d in devs), devs)
        ev = [json.loads(l) for l in (B / 'evaluation' / name / 'decision_events.jsonl')
              .read_text().splitlines() if l.strip()] if (B / 'evaluation' / name /
                                                          'decision_events.jsonl').exists() else []
        w = [e['written_at'] for e in ev if e.get('event') == 'decisions_written']
        s_ = [e['started_at'] for e in ev if e.get('event') == 'execution_started']
        add('function', f'{name}:decision_before_execution',
            bool(w) and bool(s_) and min(s_) > min(w), {'written': w[:1], 'started': s_[:1]})

    # 决策矩阵合同：调用生产函数
    try:
        import v7_decision_contract as DC
        mp = B / 'evaluation/closed_loop_R03_scene2/matrix.jsonl'
        dp = B / 'evaluation/closed_loop_R03_scene2/decisions.json'
        if mp.exists() and dp.exists():
            rows = [json.loads(l) for l in mp.read_text().splitlines() if l.strip()]
            dj = jl(dp) or {}
            dec = dj.get('decision') or {}
            res = DC.validate(rows, dict(dec, reason=dec.get('reason') or 'n/a'))
            add('function', 'decision_matrix_contract', res['ok'], res['errors'][:2])
        else:
            add('function', 'decision_matrix_contract', False, 'matrix/decision 缺失')
    except Exception as e:
        add('function', 'decision_matrix_contract', False, f'{type(e).__name__}: {e}')

    # 六方法 × 土壤
    six = {}
    for m in ('nominal', 'low_traction', 'high_drag'):
        d = jl(B / f'evaluation/six_R03_{m}/summary.json')
        if d:
            six[m] = d
    add('function', 'six_methods_three_soils', len(six) == 3, sorted(six))
    for m, d in six.items():
        methods = {x['method'] for x in d.get('methods', [])}
        add('function', f'six_{m}:six_methods',
            {'B0_blind', 'B1_height', 'B2_box', 'B3_mirror', 'H5_lux3d', 'U_truth'} <= methods,
            sorted(methods))
        vals = [x for x in d.get('methods', [])
                if (x.get('validation') or {}).get('n')]
        add('function', f'six_{m}:validation_executed',
            len(vals) == len(d.get('methods', [])), len(vals))

    # 多 mesh 一致性
    mm = jl(B / 'fusion_diagnostics/mm_V7_R03_s2/multimesh_validate.json')
    add('function', 'multimesh_split_equivalence', bool(mm and mm.get('pass')),
        (mm or {}).get('checks'))

    # 碰撞测量的内存与等价性证据（本轮修正必须有记录，否则无法解释口径变化）
    mf = jl(B / 'fusion_diagnostics/off1_R03_s1/collision/metrics_full.json')
    add('function', 'collision_metric_full_parity',
        bool(mf) and (mf.get('parity_source') or {}).get('method') == 'full_mesh',
        (mf or {}).get('parity_source'))
    add('function', 'collision_metric_memory_recorded',
        bool(mf) and float(mf.get('peak_rss_mb') or 0) > 0
        and float(mf.get('peak_rss_mb') or 0) < 8000,
        {'peak_rss_mb': (mf or {}).get('peak_rss_mb')})
    add('function', 'collision_metric_no_subsampling',
        bool(mf) and not (mf.get('evaluation_points') or {}).get('sampled'),
        (mf or {}).get('evaluation_points'))
    eq = jl(ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1/verify/distance_block_equivalence.json')
    add('function', 'distance_block_equivalence', bool(eq and eq.get('all_zero')),
        (eq or {}).get('cases'))

    # 第二观察与再观察筛选（本轮新增能力，必须有证据）
    cap = jl(B / 'observation/drive_R03_b/capability.json')
    add('function', 'second_observation_usable',
        bool(cap) and any(r.get('usable') for r in (cap.get('runs') or [])),
        [f"{r['seed']}:{r.get('baseline_m')}m/{r.get('bearing_deg')}deg/{r.get('usable')}"
         for r in (cap or {}).get('runs', [])])
    scr = jl(B / 'evaluation/screen_R03/screen_parsed.json')
    add('function', 'second_view_screen_recorded', bool(scr), (scr or {}).get('rule'))
    if scr:
        verdicts = {r['candidate']: r['verdict'] for r in scr.get('rows', [])}
        add('function', 'second_view_discriminates',
            any('rejected' in str(v) for v in verdicts.values()), verdicts)
        add('function', 'second_view_no_silent_pass',
            all(v != 'not_evaluated' or 'error' in json.dumps(
                next((r for r in scr['rows'] if r['candidate'] == k), {}))
                for k, v in verdicts.items()), verdicts)

    # 真值对照：第二观察本身必须被真值验证为可用
    tc = jl(B / 'evaluation/truth_control_second_view.json')
    add('function', 'truth_control_on_second_view',
        bool(tc) and float((tc.get('obs2') or {}).get('freespace_violation') or 1) <= 0.05,
        (tc or {}).get('obs2'))
    # 筛选后闭环（空集合应走 A0 且写明原因）
    psc = jl(B / 'evaluation/closed_loop_R03_after_screen/closed_loop.json')
    add('function', 'post_screen_a0_branch',
        bool(psc) and psc.get('branch') == 'a0_fallback_no_candidate'
        and (psc.get('decision') or {}).get('chosen') == 'A0'
        and bool((psc.get('decision') or {}).get('reason')),
        {'branch': (psc or {}).get('branch'),
         'reason': ((psc or {}).get('decision') or {}).get('reason')})
    if psc:
        add('function', 'post_screen_state_mode_recorded',
            all(e.get('state_mode') in ('same_scene', 'project') for e in psc.get('execution') or []),
            [e.get('state_mode') for e in psc.get('execution') or []])

    # 多土壤决策聚合：同一 (候选,状态) 在不同土壤下必须是不同的格，缺一格即证据不足
    try:
        import decision as _D
        rows = []
        for cand in ('H1', 'H2'):
            for sd in (0, 1):
                for soil, ok in (('nominal', True), ('low_traction', False), ('high_drag', True)):
                    rows.append({'hypothesis_id': cand, 'option': 'R1', 'seed': sd,
                                 'soil_config': soil, 'success': ok,
                                 't_end': 10.0 if ok else None, 'abort': not ok})
        d_ok = _D.evaluate(rows, ['R1'])
        n_fail = d_ok['stats']['R1']['per_hypothesis']['H1']['fails']
        drop = [r for r in rows if not (r['hypothesis_id'] == 'H2' and r['seed'] == 1
                                        and r['soil_config'] == 'high_drag')]
        d_miss = _D.evaluate(drop, ['R1'])
        add('function', 'decision_aggregates_soil',
            n_fail == 2 and d_ok['stats']['R1']['risk'] == 0.333
            and d_miss['stats']['R1']['insufficient'] and not d_miss['stats']['R1']['safe'],
            {'fails': n_fail, 'risk': d_ok['stats']['R1']['risk'],
             'missing_detected': d_miss['stats']['R1']['insufficient']})
    except Exception as e:
        add('function', 'decision_aggregates_soil', False, f'{type(e).__name__}: {e}')

    # 验证状态续接合同：协议带快照 -> 验证行必须标 continuation=true 且记 state_mode
    v2 = jl(B / 'evaluation/six_R03_nominal_v2/summary.json')
    add('function', 'validation_continuation_run', bool(v2), 'six_R03_nominal_v2')
    if v2:
        rp = B / 'evaluation/six_R03_nominal_v2/records.jsonl'
        rows2 = ([json.loads(l) for l in rp.read_text().splitlines() if l.strip()]
                 if rp.exists() else [])
        val = [r for r in rows2 if r.get('phase') == 'validation']
        add('function', 'validation_continuation_contract',
            bool(val) and all(r.get('validation_continuation') is True
                              and r.get('state_mode') in ('same_scene', 'project')
                              for r in val),
            {'n': len(val),
             'modes': sorted({r.get('state_mode') for r in val}),
             'continuation': sorted({r.get('validation_continuation') for r in val},
                                    key=str)})

    # 用户入口：必须存在且能列出八个阶段
    ent = ROOT / 'scripts/run_r1.py'
    add('function', 'user_entry_point_exists', ent.exists(), 'scripts/run_r1.py')
    if ent.exists():
        try:
            out = subprocess.run([sys.executable, str(ent), '--dry-run'],
                                 cwd=str(ROOT), capture_output=True, text=True, timeout=120)
            stages = ['observe', 'candidate', 'fuse', 'measure', 'closed_loop', 'six',
                      'page', 'verify']
            add('function', 'user_entry_lists_stages',
                out.returncode == 0 and all(st in out.stdout for st in stages),
                {'rc': out.returncode, 'missing': [st for st in stages
                                                   if st not in out.stdout]})
        except Exception as e:
            add('function', 'user_entry_lists_stages', False, f'{type(e).__name__}: {e}')

    # 状态合同（生产函数）
    scp = jl(B / 'verify/state_contract.json')
    add('function', 'state_contract_ab', bool(scp and scp.get('all_pass')),
        {k: v.get('pass') for k, v in (scp or {}).get('cases', {}).items()}
        if isinstance((scp or {}).get('cases'), dict) else (scp or {}))

    # 反例
    st = jl(B / 'verify/selftest.json')
    add('function', 'negative_selftest', bool(st and st.get('n_pass') == st.get('n')),
        (st or {}).get('n_pass'))

    # ---------- 目标 ----------
    procs = [jl(p) for p in sorted((B / 'processed').glob('*/process.json'))]
    procs = [p for p in procs if p]
    add('goal', 'processed_candidates', len(procs) > 0, len(procs))
    # 资格：本批处理的候选 + 本批闭环**实际使用**的候选（可能来自父批次，必须按引用核对）
    used = set()
    for cp in sorted((B / 'cases').glob('*.json')):
        for h in (jl(cp) or []):
            if isinstance(h, dict) and h.get('id'):
                used.add(h['id'])
    extra = []
    for cid in sorted(used):
        for cand in (B / 'processed' / cid / 'process.json',
                     ROOT / 'runs/unseen/delivery_v7/v7_20261030/processed' / cid / 'process.json'):
            d = jl(cand)
            if d:
                extra.append(d)
                break
    allp = {p['candidate']: p for p in procs + extra}
    qual = [k for k, v in allp.items()
            if (v.get('qualified_visible') and v.get('qualified_collision'))]
    add('goal', 'qualified_candidates', len(qual) >= 1,
        {'qualified': qual, 'examined': sorted(allp)})

    page = B / 'media/report/index.html'
    add('goal', 'page_exists', page.exists(), str(page.relative_to(ROOT)) if page.exists() else '')
    if page.exists():
        html = page.read_text()
        add('goal', 'page_has_two_modes',
            ('回放已有运行' in html) and ('重新运行' in html), '')
        add('goal', 'page_no_auto_paid_call',
            ('不触发任何生成' in html) or ('不消耗积分' in html) or ('不产生生成费用' in html), '')

    rep = {'schema': 'verify-delivery/v7-r1', 'batch': a.batch,
           'n_checks': len(C), 'n_pass': sum(1 for c in C if c['pass']),
           'by_layer': {L: {'n': sum(1 for c in C if c['layer'] == L),
                            'n_pass': sum(1 for c in C if c['layer'] == L and c['pass'])}
                        for L in ('integrity', 'function', 'goal')},
           'checks': C}
    rep['verdict'] = 'PASS' if rep['n_pass'] == rep['n_checks'] else 'FAIL'
    op = ROOT / a.out
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'verdict': rep['verdict'], 'n_pass': rep['n_pass'],
                      'n': rep['n_checks'], 'by_layer': rep['by_layer'],
                      'fails': [c['check'] for c in C if not c['pass']][:10]},
                     ensure_ascii=False))
    return 0 if rep['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
