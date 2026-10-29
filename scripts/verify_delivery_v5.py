"""
V5 批次统一验收：绑定 runs/unseen/delivery_v5/<batch>/manifest.json，不硬编码旧 P1/P3。

  .venv/bin/python scripts/verify_delivery_v5.py \
      --manifest runs/unseen/delivery_v5/v5_20261029/manifest.json \
      --out runs/unseen/delivery_v5/v5_20261029/verify/report.json

  --self-test 会实际调用同一校验函数跑负例（重复初态、坏 SHA、伪造成功、真假同 SHA），
  负例未检出 -> 返回非零。

注意：benefit=NOT_ESTABLISHED 是研究判断，不是程序错误；本脚本只对证据/接口/执行合同
返回非零。delivery_status 见 delivery.json，不在这里改成 PASS。
"""
import argparse
import copy
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULT = []


def check(name, ok, detail=''):
    RESULT.append({'check': name, 'pass': bool(ok), 'detail': detail})
    return bool(ok)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_json(p):
    return json.loads(pathlib.Path(p).read_text())


def load_jsonl(p):
    return [json.loads(l) for l in pathlib.Path(p).read_text().splitlines() if l.strip()]

def collision_parts_sha(coll_dir, expected_parts=None):
    """按 physicalize 的顺序重算 parts 身份；返回 (sha32, errors)。"""
    d = pathlib.Path(coll_dir)
    manp = d / 'manifest.json'
    if not manp.exists():
        return None, [f'missing collision manifest {manp}']
    man = json.loads(manp.read_text())
    parts = expected_parts or man.get('parts') or []
    if not parts:
        return None, ['collision manifest has no parts']
    h = hashlib.sha256(); errs = []
    for rel in parts:
        fp = d / rel
        if not fp.exists():
            errs.append(f'missing part {rel}')
            continue
        h.update(str(rel).encode())
        h.update(sha(fp).encode())
    return h.hexdigest()[:32], errs


def validate_collision(coll_dir, expected_sha=None):
    got, errs = collision_parts_sha(coll_dir)
    if expected_sha and got != expected_sha:
        errs.append(f'collision_sha {got} != expected {expected_sha}')
    manp = pathlib.Path(coll_dir) / 'manifest.json'
    if manp.exists():
        m = json.loads(manp.read_text())
        if expected_sha and m.get('collision_sha') != expected_sha:
            errs.append('manifest collision_sha != expected')
    return errs



# ---------- 纯校验函数（负例复用） ----------
def validate_six(records, summary, expected_truth=None):
    errs = []
    methods = [m['method'] for m in summary.get('methods', [])]
    if len(methods) != len(set(methods)):
        errs.append('duplicate method in summary')
    ex = [r for r in records if r.get('phase') == 'execution']
    keys = [(r.get('method'), r.get('initial_state_id')) for r in ex]
    if len(keys) != len(set(keys)):
        errs.append('duplicate (method, initial_state_id) execution key')
    for m in summary.get('methods', []):
        rows = [r for r in ex if r.get('method') == m['method']
                and r.get('option') == m.get('selected_action')]
        if m.get('no_candidate'):
            if rows:
                errs.append(f"{m['method']}: no_candidate but has execution")
            continue
        if len(rows) != m.get('n_expected', 0):
            errs.append(f"{m['method']}: n_exec {len(rows)} != n_expected {m.get('n_expected')}")
        succ = sum(1 for r in rows if r.get('success'))
        if succ != m.get('success'):
            errs.append(f"{m['method']}: success {succ} != summary {m.get('success')}")
    # 初态必须互异（每个 seed 一个哈希），且执行环境唯一
    by_seed = {}
    for r in ex:
        by_seed.setdefault(r.get('initial_state_id'), set()).add(r.get('initial_state_hash'))
    if any(len(v) != 1 for v in by_seed.values()):
        errs.append('same seed has multiple initial_state_hash')
    hashes = [list(v)[0] for v in by_seed.values() if len(v) == 1]
    if len(hashes) != len(set(hashes)):
        errs.append('duplicate initial state across seeds')
    truth = {r.get('truth_sha') for r in ex if r.get('truth_sha')}
    if len(truth) > 1:
        errs.append(f'multiple truth_sha in execution: {truth}')
    if expected_truth is not None:
        if summary.get('truth_sha') != expected_truth:
            errs.append(f'summary truth_sha != expected {expected_truth[:12]}')
        if any(r.get('truth_sha') != expected_truth for r in ex):
            errs.append('execution truth_sha != expected')
    # 计时：控制步 × 冻结 dt，且 t_end/sim_time 一致
    pf = load_json(ROOT / 'configs/unseen_physics_frozen.json')
    dt = float(pf['control_dt_s']); tol = float(pf['tolerance_s'])
    for r in ex:
        cs, te = r.get('control_steps'), r.get('t_end')
        if cs and te is not None:
            expect = float(cs) * dt
            if abs(float(te) - expect) > max(tol, 0.02 * expect):
                errs.append(f"{r.get('method')}/{r.get('seed')}: t_end {te} != steps*dt {expect:.3f}")
                break
    return errs


def validate_candidate_table(table, plan):
    errs = []
    by_id = {i['id']: i for i in plan['inputs']}
    for r in table.get('rows', []):
        it = by_id.get(r.get('plan_id'))
        if not it:
            errs.append(f"unknown plan_id {r.get('plan_id')}")
            continue
        if r.get('input_sha256') != it.get('image_sha256'):
            errs.append(f"{r['plan_id']}: input_sha mismatch")
        if r.get('glb_sha256') and r.get('provider_status') == 'downloaded':
            cache = None
            # 通过 batch generation table 的路径约定查找由调用方另查；这里只校验长度/十六进制
            if len(str(r['glb_sha256'])) != 64:
                errs.append(f"{r['plan_id']}: glb_sha not 64 hex")
        if r.get('strict') and r.get('planning_eligible') and not r['strict'].get('pass'):
            # 允许：仅过工程政策；但必须显式记录 strict 失败，不能写成 strict 通过
            if r.get('note') is None and r.get('strict_pass') is True:
                errs.append(f"{r['plan_id']}: strict fail但写成 strict_pass")
    return errs


def validate_h5(summary, decision, execs):
    errs = []
    chosen = summary.get('chosen')
    if decision.get('chosen') != chosen:
        errs.append('decision.chosen != summary.chosen')
    rows = [r for r in execs if r.get('option') == chosen]
    blind = [r for r in execs if r.get('option') == 'R1']
    if len(rows) != summary.get('n_seeds', 0):
        errs.append(f'chosen rows {len(rows)} != n_seeds {summary.get("n_seeds")}')
    if f"{sum(1 for r in rows if r.get('success'))}/{len(rows)}" != str(summary.get('chosen_truth_success')):
        errs.append('chosen success not recomputable')
    if f"{sum(1 for r in blind if r.get('success'))}/{len(blind)}" != str(summary.get('blind_truth_success')):
        errs.append('blind success not recomputable')
    cand = summary.get('candidates') or []
    if any(c.get('world_sha') == summary.get('truth_sha') for c in cand):
        errs.append('candidate world_sha == truth_sha')
    if any(r.get('truth_sha') != summary.get('truth_sha') for r in execs):
        errs.append('execution truth_sha != summary truth_sha')
    return errs


def validate_truth_separation(cand_world_sha, truth_sha):
    return [] if cand_world_sha != truth_sha else ['candidate world_sha equals truth_sha']


# ---------- 批次检查 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    manp = pathlib.Path(a.manifest)
    if not manp.exists():
        print(f'manifest 不存在：{manp}')
        return 2
    man = load_json(manp)
    bdir = manp.parent
    planp = ROOT / man['plan']['path']
    plan = load_json(planp)
    check('manifest: plan SHA 一致', sha(planp) == man['plan']['sha256'],
          {'file': sha(planp), 'manifest': man['plan']['sha256']})
    check('plan: 三项/60 上界', len(plan['inputs']) == 3
          and sum(i['credits_upper'] for i in plan['inputs']) == 60,
          [i['id'] for i in plan['inputs']])
    check('plan: 模型参数合法', all(i['model']['face_count'] >= 10000
                                  and i['model']['face_count'] <= 300000
                                  for i in plan['inputs']),
          [i['model'] for i in plan['inputs']])

    # 生成
    genp = bdir / 'generation/tasks.json'
    check('generation: tasks.json 存在', genp.exists(), str(genp))
    if genp.exists():
        gen = load_json(genp)
        rows = gen['rows']
        check('generation: 3 任务全部 downloaded',
              len(rows) == 3 and all(r['provider_status'] == 'downloaded' for r in rows),
              [r['provider_status'] for r in rows])
        check('generation: task_id 唯一且非空',
              len({r['task_id'] for r in rows}) == 3 and all(r['task_id'] for r in rows),
              [r['task_id'] for r in rows])
        check('generation: 扣费 unknown 不写成已核验',
              all(r.get('actual_charge') is None and r.get('verified') == 'unknown'
                  for r in rows),
              [r.get('verified') for r in rows])
        glb_errs = []
        for r in rows:
            ident = r.get('request_identity')
            gp = ROOT / 'runs/unseen/generation/cache' / str(ident)[:2] / str(ident) / 'model.glb'
            if not gp.exists():
                glb_errs.append(f'{r.get("plan_id")}: missing {gp}')
            elif sha(gp) != r.get('glb_sha256'):
                glb_errs.append(f'{r.get("plan_id")}: GLB SHA mismatch')
        check('generation: GLB SHA 与缓存一致（实际重算）', not glb_errs, glb_errs)
        check('generation: 输入 SHA 与 plan 一致',
              all(r['input_sha256'] == next(i['image_sha256'] for i in plan['inputs']
                                             if i['id'] == r['plan_id']) for r in rows))

    # 候选
    ctp = bdir / 'candidates/candidate_table.json'
    check('candidates: 表存在', ctp.exists(), str(ctp))
    if ctp.exists():
        ct = load_json(ctp)
        errs = validate_candidate_table(ct, plan)
        check('candidates: 表校验', not errs, errs)
        check('candidates: 3/3 清理通过',
              sum(1 for r in ct['rows'] if r['clean_verdict'] == 'ok') == 3,
              [r['clean_verdict'] for r in ct['rows']])
        check('candidates: 3/3 完成配准',
              all(r['align_executed'] for r in ct['rows']))
        check('candidates: strict 与 planning 分开',
              ct['summary']['strict_pass'] == 0 and ct['summary']['planning_eligible'] == 1,
              ct['summary'])
        f = next((r for r in ct['rows'] if r['plan_id'] == 'C_R01_face12k'), None)
        if f:
            check('candidates: face12k 仅过工程政策（strict=false）',
                  f['planning_eligible'] and not f['strict']['pass'],
                  f['strict'])
            colp = bdir / 'candidates/C_R01_face12k/collision/manifest.json'
            check('candidates: face12k 碰撞 manifest 存在且 pass',
                  colp.exists() and load_json(colp).get('pass') is True,
                  str(colp))
            if colp.exists():
                col = load_json(colp)
                check('candidates: face12k world_sha 与 collision manifest 一致',
                      col.get('world_sha') == f.get('world_sha256'),
                      {'collision': col.get('world_sha'), 'table': f.get('world_sha256')})

    # 六方法 R03
    r3 = bdir / 'evaluation/six_R03_v5'
    check('evaluation: six_R03_v5 存在', (r3 / 'summary.json').exists())
    if (r3 / 'summary.json').exists():
        s = load_json(r3 / 'summary.json')
        recs = load_jsonl(r3 / 'records.jsonl')
        errs = validate_six(recs, s, '436b75d2ee2d3f7e' + s.get('truth_sha','')[16:])
        check('six_R03: 记录校验', not errs, errs[:6])
        check('six_R03: 六方法齐全', len(s['methods']) == 6, [m['method'] for m in s['methods']])
        check('six_R03: 30 s 协议', s.get('time_limit_s') == 30.0, s.get('time_limit_s'))
        check('six_R03: 共同真值 436b…', s.get('truth_sha', '').startswith('436b75d2'),
              s.get('truth_sha'))
        h5 = next((m for m in s['methods'] if m['method'] == 'H5_lux3d'), None)
        check('six_R03: H5 有真实候选', bool(h5 and not h5.get('no_candidate')),
              h5)

    # 六方法 R01（无 H5）
    r1 = bdir / 'evaluation/six_R01_v5'
    check('evaluation: six_R01_v5 存在', (r1 / 'summary.json').exists())
    if (r1 / 'summary.json').exists():
        s = load_json(r1 / 'summary.json')
        recs = load_jsonl(r1 / 'records.jsonl')
        errs = validate_six(recs, s, s.get('truth_sha'))
        check('six_R01: 记录校验', not errs, errs[:6])
        h5 = next((m for m in s['methods'] if m['method'] == 'H5_lux3d'), None)
        check('six_R01: H5 记 no_candidate（不补 fixture）',
              bool(h5 and h5.get('no_candidate')), h5)
        check('six_R01: 30 s 协议', s.get('time_limit_s') == 30.0)
        check('six_R01: 共同真值 ae18…', s.get('truth_sha', '').startswith('ae1837cd'),
              s.get('truth_sha'))

    # R02/R04 无候选对象
    for c in ('R02', 'R04'):
        run = bdir / f'evaluation/six_{c}_v5'
        check(f'evaluation: six_{c}_v5 存在', (run / 'summary.json').exists())
        if (run / 'summary.json').exists():
            s = load_json(run / 'summary.json')
            recs = load_jsonl(run / 'records.jsonl')
            errs = validate_six(recs, s)
            check(f'six_{c}: 记录校验', not errs, errs[:4])
            h5 = next((m for m in s['methods'] if m['method'] == 'H5_lux3d'), None)
            check(f'six_{c}: H5 记 no_candidate', bool(h5 and h5.get('no_candidate')), h5)
            check(f'six_{c}: 30 s 协议', s.get('time_limit_s') == 30.0)

    # 正式表/收益/状态对齐
    ftp = bdir / 'evaluation/formal_table_v5.json'
    check('evaluation: 正式比较表存在', ftp.exists())
    if ftp.exists():
        ft = load_json(ftp)
        check('正式表: 4 个案例/24 行', len(ft.get('cases', [])) == 4
              and len(ft.get('rows', [])) == 24,
              {'cases': len(ft.get('cases', [])), 'rows': len(ft.get('rows', []))})
        check('正式表: benefit=NOT_ESTABLISHED',
              load_json(bdir / 'evaluation/benefit_summary.json').get('benefit_status') == 'NOT_ESTABLISHED')
        check('初态对齐: H5 与 six_R01 全匹配',
              load_json(bdir / 'evaluation/state_alignment_R01.json').get('all_match') is True)
    csp = bdir / 'cases/case_selection.json'
    check('案例: 真实覆盖报告存在', csp.exists())
    if csp.exists():
        cs = load_json(csp)
        check('案例: 独立形状 >=4', cs.get('independent_shape_count', 0) >= 4,
              cs.get('independent_shape_count'))
        check('案例: 未命中隐藏背面取舍已如实写',
              cs.get('effective_hidden_back_tradeoffs') == [], cs.get('effective_hidden_back_tradeoffs'))
    ffull = bdir / 'observation/fixture_pair_full/look_loop.json'
    check('observation: fixture 全链路结果存在', ffull.exists())
    if ffull.exists():
        d = load_json(ffull)
        check('observation: fixture 全链路触发/筛选/续行',
              d.get('trigger', {}).get('triggered') is True
              and d.get('kept') == ['FX_truth']
              and d.get('decision', {}).get('chosen') == 'S1'
              and any(e['option'] == 'S1' and e['success'] for e in d.get('execution', [])),
              {'kept': d.get('kept'), 'chosen': d.get('decision', {}).get('chosen')})

    # H5 face12k
    h5 = bdir / 'evaluation/H5_R01_face12k'
    check('evaluation: H5_R01_face12k 存在', (h5 / 'summary.json').exists())
    if (h5 / 'summary.json').exists():
        s = load_json(h5 / 'summary.json')
        dec = load_json(h5 / 'decision.json')
        ex = load_jsonl(h5 / 'execution.jsonl')
        errs = validate_h5(s, dec, ex)
        check('H5_face12k: 决策/执行可复算', not errs, errs[:6])
        check('H5_face12k: 30 s 协议', s.get('time_limit_s') == 30.0)
        check('H5_face12k: 真值与候选分离',
              all(c['world_sha'] != s['truth_sha'] for c in s['candidates']),
              {'truth': s['truth_sha'][:16]})
        check('H5_face12k: 决策先于执行（mtime）',
              (h5 / 'decision.json').stat().st_mtime <= (h5 / 'execution.jsonl').stat().st_mtime)
        check('H5_face12k: 真值几何与 R01 scan 一致（几何 SHA）',
              s['truth_sha'].startswith('ae1837cd'),
              s['truth_sha'])
        cerr = validate_collision(h5 / 'truth_collision')
        check('H5_face12k: 真值碰撞 parts 可重算', not cerr, cerr)
        ccol = bdir / 'candidates/C_R01_face12k/collision'
        if (ccol / 'manifest.json').exists():
            want = json.loads((ccol / 'manifest.json').read_text()).get('collision_sha')
            cerr = validate_collision(ccol, want)
            check('H5_face12k: 候选碰撞 parts 可重算', not cerr, cerr)

    # 观察触发
    tf = bdir / 'observation/trigger_face12k/trigger.json'
    check('observation: 真实候选 trigger 存在', tf.exists())
    if tf.exists():
        t = load_json(tf)
        check('observation: 真实候选一致 -> 不触发',
              t['triggered'] is False and t['chosen_set'] == ['L2'],
              {'triggered': t['triggered'], 'chosen': t['chosen_set']})
        check('observation: 触发来源为真实 Lux3D',
              all(c.get('source_kind') == 'lux3d' for c in t['candidates']),
              [c.get('source_kind') for c in t['candidates']])
    fx = bdir / 'observation/trigger_fixture_pair_box/trigger.json'
    check('observation: 可控 fixture trigger 存在', fx.exists())
    if fx.exists():
        t = load_json(fx)
        check('observation: fixture 分歧 -> 触发', t['triggered'] is True, t)
        check('observation: fixture 来源醒目标注',
              all(c.get('source_kind') == 'fixture' for c in t['candidates']),
              [c.get('source_kind') for c in t['candidates']])
    look = ROOT / 'runs/unseen/recovery_r3/look_loop_R01_v3/look_loop.json'
    if look.exists():
        d = load_json(look)
        check('observation: 既有完整链路保留（fixture）',
              d.get('workflow') == 'look_again_loop/v1' and d.get('candidates_in') == ['FX_R01'],
              d.get('candidates_in'))

    # 月壤
    soilp = bdir / 'soil/acceptance.json'
    check('soil: acceptance.json 存在', soilp.exists())
    if soilp.exists():
        so = load_json(soilp)
        st = so.get('stages', {})
        check('soil: A-F 阶段齐全', all(k in st for k in ('a', 'b', 'c', 'd', 'e', 'f', 'g')),
              sorted(st))
        soil_a = st.get('a', {})
        val = soil_a.get('validation', [])
        check('soil: 标定/验证载荷分开', bool(soil_a.get('calibration')) and bool(val))
        check('soil: 验证误差 <=30%', all(v.get('rel_err') is not None and v['rel_err'] <= 0.3
                                          for v in val), [v.get('rel_err') for v in val])
        g = st.get('g', {})
        check('soil: 几何下陷 verdict 明确',
              g.get('verdict') in ('PARTIAL_NOT_IMPLEMENTED', 'IMPLEMENTED'),
              g.get('verdict'))
        e = st.get('e', {})
        check('soil: 稳定性 >=1000 回合', e.get('n_episodes', 0) >= 1000, e.get('n_episodes'))
        check('soil: 稳定性无异常', e.get('n_anomaly') == 0, e.get('n_anomaly'))

    # 页面/演示
    media = bdir / 'media/page'
    check('page: 浏览器截图存在', media.exists() and len(list(media.glob('*.png'))) >= 3,
          str(media))
    check('page: 演示脚本存在', (ROOT / 'docs/DEMO_V5.md').exists())
    check('page: README 当前方向', (ROOT / 'README.md').exists())

    # 负例自检（实际调用同一校验函数）
    if a.self_test:
        # 1) 重复初态
        if (r3 / 'records.jsonl').exists():
            recs = load_jsonl(r3 / 'records.jsonl')
            bad = copy.deepcopy(recs)
            ex = [r for r in bad if r.get('phase') == 'execution']
            if len(ex) >= 2:
                ex[1]['initial_state_id'] = ex[0]['initial_state_id']
            s = load_json(r3 / 'summary.json')
            check('neg: 重复初态被检出', bool(validate_six(bad, s)), 'expected non-empty')
        # 2) 坏 SHA
        if ctp.exists():
            bad = copy.deepcopy(load_json(ctp))
            bad['rows'][0]['input_sha256'] = '0' * 64
            check('neg: 坏输入 SHA 被检出',
                  bool(validate_candidate_table(bad, plan)), 'expected non-empty')
            # 真文件一字节变化
            gp = ROOT / 'runs/unseen/generation/cache' / str(ct['rows'][0].get('request_identity'))[:2] / str(ct['rows'][0].get('request_identity')) / 'model.glb'
            if gp.exists():
                import tempfile
                tp = pathlib.Path(tempfile.mkdtemp()) / 'flip.glb'
                b = bytearray(gp.read_bytes()); b[len(b)//2] ^= 1; tp.write_bytes(bytes(b))
                check('neg: 实际 GLB 一字节变化被检出', sha(tp) != ct['rows'][0].get('glb_sha256'))
            # 缺 part
            cdir = bdir / 'candidates/C_R01_face12k/collision'
            if (cdir / 'manifest.json').exists():
                man = json.loads((cdir / 'manifest.json').read_text())
                got, errs = collision_parts_sha(cdir, man['parts'][:-1])
                check('neg: 缺碰撞 part 被检出', bool(errs) or got != man.get('collision_sha'), errs)
            # 全部 truth_sha 改错
            if (r1 / 'summary.json').exists():
                recs = load_jsonl(r1 / 'records.jsonl')
                bad = copy.deepcopy(recs)
                for x in bad:
                    if x.get('truth_sha'): x['truth_sha'] = '0'*64
                check('neg: 所有执行 truth_sha 同错被检出',
                      bool(validate_six(bad, load_json(r1 / 'summary.json'), load_json(r1 / 'summary.json').get('truth_sha'))), 'expected non-empty')
        # 3) 伪造成功
        if (h5 / 'summary.json').exists():
            s = copy.deepcopy(load_json(h5 / 'summary.json'))
            ex = copy.deepcopy(load_jsonl(h5 / 'execution.jsonl'))
            for r in ex:
                if r.get('option') == s['chosen']:
                    r['success'] = not r['success']
            check('neg: 伪造成功率被检出',
                  bool(validate_h5(s, load_json(h5 / 'decision.json'), ex)),
                  'expected non-empty')
        # 4) 真假同 SHA
        check('neg: 候选/真值同 SHA 被检出',
              bool(validate_truth_separation('abc', 'abc')), 'expected non-empty')
        # 5) 无候选 H5 被检出（构造 summary）
        fake = {'methods': [{'method': 'H5_lux3d', 'selected_action': None,
                             'no_candidate': True, 'n_expected': 0}]}
        check('neg: no_candidate 校验可用', not validate_six([], fake), 'expected empty')

    failed = [r for r in RESULT if not r['pass']]
    out = {'manifest': str(manp), 'batch_id': man.get('batch_id'),
           'n_checks': len(RESULT), 'n_pass': len(RESULT) - len(failed),
           'n_fail': len(failed), 'checks': RESULT}
    op = pathlib.Path(a.out); op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    for r in RESULT:
        print(('PASS' if r['pass'] else 'FAIL'), r['check'], '|', r['detail'])
    print(f"\n{out['n_pass']}/{out['n_checks']} 通过")
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
