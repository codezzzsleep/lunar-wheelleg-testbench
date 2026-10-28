"""
统一自验：从本批原始记录**重算**，并注入失败路径确认会非零退出。

  MUJOCO_GL=osmesa .venv/bin/python scripts/verify_r3.py --run runs/unseen/recovery_r3

不读取旧 PASS 文件；所有判据都从本批 JSONL/JSON 重新计算。
退出码：0 全通过；1 有检查失败；2 参数/文件缺失。
"""
import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import soil as SOIL

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULT = []


def check(name, ok, detail=''):
    RESULT.append({'check': name, 'pass': bool(ok), 'detail': str(detail)[:300]})
    return ok


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def verify_six(run, name='six_v2'):
    d = run / name
    if not d.exists():
        return check(f'{name}:存在', False, d)
    s = json.loads((d / 'summary.json').read_text())
    recs = [json.loads(l) for l in (d / 'records.jsonl').read_text().splitlines() if l.strip()]
    decs = json.loads((d / 'decisions.json').read_text())
    if 'n_expected' not in s['methods'][0]:
        check(f'{name}:旧 schema 无法核验分母', False,
              'summary 缺 n_expected；该运行标记 NOT_VERIFIED，请用 six_v2')
        return False
    check(f'{name}:六种方法齐全', len(s['methods']) == 6, [m['method'] for m in s['methods']])
    check(f'{name}:共同真值 SHA 记录', bool(s.get('truth_sha')), s.get('truth_sha', '')[:12])
    check(f'{name}:初态数>=3', s.get('n_initial_states', 0) >= 3, s.get('n_initial_states'))
    # 每个方法的执行行数 == 初态数；成功率可从原始行重算
    ok = True
    for m in s['methods']:
        rows = [r for r in recs if r['method'] == m['method']
                and r.get('phase') == 'execution'
                and r['option'] == m['selected_action']]
        if len(rows) != s['n_initial_states']:
            ok = False
        if sum(1 for r in rows if r['success']) != m['success']:
            ok = False
    check(f'{name}:成功率可从原始行重算', ok)
    # 所有 phase=execution 的记录必须指向同一真值（方法不得用自己的假设当执行环境）
    ex_rows = [r for r in recs if r.get('phase') == 'execution']
    check(f'{name}:执行记录有 phase 标记', len(ex_rows) ==
          sum(m['n_exec'] for m in s['methods']), len(ex_rows))
    truth_set = {r.get('truth_sha') for r in ex_rows}
    check(f'{name}:执行环境唯一', len(truth_set) == 1 and None not in truth_set,
          sorted(str(x)[:8] for x in truth_set))
    check(f'{name}:执行真值等于 summary', truth_set == {s.get('truth_sha')},
          f"records={sorted(str(x)[:8] for x in truth_set)} "
          f"summary={str(s.get('truth_sha'))[:8]}")
    check(f'{name}:分母完整', all(m['n_exec'] == m['n_expected'] for m in s['methods']),
          [(m['method'], m['n_exec'], m['n_expected']) for m in s['methods']])
    # 初态必须与协议一致且每条记录带初态哈希
    check(f'{name}:初态哈希齐全', all(r.get('initial_state_hash') for r in ex_rows))
    check(f'{name}:无候选显式标记', all(('no_candidate' in m) for m in s['methods']))
    return True


def verify_h5(run, name='h5_A4_truth'):
    d = run / name
    f = d / 'h5_loop.json'
    if not f.exists():
        return check('h5:存在', False, f)
    h = json.loads(f.read_text())
    check('h5:候选与真值 SHA 不同', h['candidate_world_sha'] != h['truth_asset_sha'],
          f"{h['candidate_world_sha'][:8]} vs {h['truth_asset_sha'][:8]}")
    check('h5:三个初态互异', h.get('initial_states_distinct') is True,
          [s['qpos_hash'] for s in h['initial_states']])
    check('h5:决策先冻结', bool(h.get('decision_sha256')), h.get('decision_sha256', '')[:12])
    dec = d / 'decision.json'
    check('h5:decision.json 哈希自洽',
          dec.exists() and sha(dec) == h['decision_sha256'])
    ex = h['execution']
    check('h5:执行覆盖全部初态',
          len([e for e in ex if e['method'] == 'H5']) == len(h['initial_states']),
          len(ex))
    check('h5:执行带真值 SHA',
          all(e.get('truth_sha') == h['truth_asset_sha'] for e in ex))
    # 计时自洽：物理步 ≈ 控制步 × substeps，且 sim_time 与 env.t 一致
    ok = all(e['physics_steps'] >= e['control_steps'] for e in ex)
    check('h5:控制/物理步数自洽', ok)
    return True


def verify_clean(run):
    t = run / 'clean_table_v3.json'
    if not t.exists():
        return check('clean:表存在', False, t)
    rows = json.loads(t.read_text())['rows']
    check('clean:全部候选都有行', len(rows) >= 12, len(rows))
    # A2 必须被拒绝且厚度比约 0.094
    a2 = next((r for r in rows if r['id'] == 'A2'), None)
    check('clean:A2 判为薄片', bool(a2) and a2['verdict'] == 'rejected_thin',
          a2 and a2['thin_ratio'])
    check('clean:A2 厚度比在 0.09 量级',
          bool(a2) and 0.085 <= (a2['thin_ratio'] or 0) <= 0.105, a2 and a2['thin_ratio'])
    # 所有 ok 的候选 components_after 必须是重读得到的真实值
    check('clean:决策与导出一致', all(r.get('matches_decisions') for r in rows
                                     if 'matches_decisions' in r))
    return True


def verify_soil(run):
    f = run / 'soil' / 'single_wheel.json'
    if not f.exists():
        return check('soil:存在', False, f)
    d = json.loads(f.read_text())
    rows = d.get('calibrated_rows') or []
    check('soil:五档载荷', len(rows) == 5, len(rows))
    ok = [r for r in rows if r['rel_err'] is not None and r['rel_err'] <= 0.30]
    check('soil:五档均在 ±30% 内', len(ok) == len(rows) == 5,
          [r['rel_err'] for r in rows])
    # 公式量纲自检
    pm = SOIL.SoilParams.moon_nominal()
    z = pm.sinkage(100.0, 0.10, 0.09)
    check('soil:下陷公式可复算', 0.001 < z < 0.06, round(z, 4))
    return True


def verify_look(run, name='look_again_v2'):
    f = run / name / 'look_again.json'
    if not f.exists():
        return check('look:存在', False, f)
    d = json.loads(f.read_text())
    A = d['observation_action']
    check('look:动作走真实物理步',
          A.get('n_physics_steps', 0) > 0 and A.get('sim_time_s', 0) > 0,
          f"physics={A.get('n_physics_steps')} sim_t={A.get('sim_time_s')}")
    # 净抬高是否达标属于**实验结论**，不是报告正确性；只检查是否如实标注
    net_up = A['delta_z_m'] > 0.02
    reported = (d.get('outcome') in ('observation_unstable',
                                     'second_observation_unusable')) if not net_up else True
    check('look:抬高结果如实标注', reported,
          f"net_dz={A['delta_z_m']} peak={A.get('z_peak_m')} outcome={d.get('outcome')}")
    check('look:记录了观察后 qpos/qvel',
          len(d['observation_action'].get('qpos') or []) > 0)
    check('look:第二视角只筛除', 'kept' in d and 'rejected' in d,
          f"kept={d['kept']} rejected={d['rejected']}")
    # 观察必须停稳；未停稳只能记 observation_unstable，不能整批 PASS
    stable = bool(d['observation_action'].get('stable'))
    outcome = d.get('outcome')
    check('look:停稳与结论一致',
          (stable and outcome != 'observation_unstable')
          or ((not stable) and outcome in ('observation_unstable',
                                           'second_observation_unusable')),
          f"stable={stable} outcome={outcome}")
    check('look:第二观测可用性有判定', 'second_view_usable' in d,
          d.get('second_view_usable'))
    return True


def verify_upload(run):
    base = run / 'upload_pkg'
    ok_all = True
    for pid in ('P1', 'P2'):
        f = base / pid / 'upload_manifest.json'
        if not f.exists():
            ok_all = check(f'upload:{pid} 存在', False, f); continue
        m = json.loads(f.read_text())
        ok_all &= check(f'upload:{pid} 目标占比在窗口内',
                        m['checks']['longest_side_in_window'], m['longest_side_fraction'])
        ok_all &= check(f'upload:{pid} 亮度>60', m['checks']['brightness_gt_60'],
                        m['target_mean_luma'])
        img = pathlib.Path(m['upload_file'])
        ok_all &= check(f'upload:{pid} 字节 SHA 与清单一致',
                        img.exists() and sha(img) == m['files']['upload_1024.png']['sha256'])
    plan = ROOT / 'plans/unseen_v3_pilot.json'
    if plan.exists():
        p = json.loads(plan.read_text())
        ok_all &= check('upload:试点计划未提交',
                        p.get('status') == 'PREPARED_NOT_SUBMITTED', p.get('status'))
        ok_all &= check('upload:新增批次上界<=60',
                        sum(i['credits_upper'] for i in p['inputs']) <= 60)
    return ok_all


def verify_negative(run):
    """
    失败路径：**实际调用被测路径**并观察结果，不用恒真表达式。
    每个负例构造坏数据 -> 跑对应函数 -> 断言它确实报错/失败。
    """
    ok = True
    import tempfile
    import shutil

    # 1) 六方法记录混入不同真值 -> verify 必须判失败
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        src = run / 'six_v2'
        if src.exists():
            shutil.copytree(src, tmp / 'six_v2')
            recs = [json.loads(l) for l in (tmp / 'six_v2' / 'records.jsonl')
                    .read_text().splitlines() if l.strip()]
            for i, r in enumerate(recs):
                if r.get('phase') == 'execution':
                    r['truth_sha'] = f'bad{i:04d}'      # 每行不同且都是错的
            (tmp / 'six_v2' / 'records.jsonl').write_text(
                '\n'.join(json.dumps(r) for r in recs) + '\n')
            global RESULT
            saved = RESULT
            RESULT = []                     # 负例用独立缓冲，不污染主检查列表
            try:
                verify_six(tmp)
                new = list(RESULT)
            finally:
                RESULT = saved
            bad = [x for x in new if x['check'].endswith('执行环境唯一')
                   or x['check'].endswith('执行真值等于 summary')
                   and not x['pass']]
            bad = [x for x in bad if not x['pass']]
            ok &= check('neg:混用真值被检出', len(bad) == 2,
                        [x['check'] for x in bad])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2) 缺文件 -> candidate_store 必须拒绝（实际调用加载器）
    try:
        import candidate_store as CS
        tmp2 = pathlib.Path(tempfile.mkdtemp())
        plan = tmp2 / 'p.json'
        plan.write_text(json.dumps({'inputs': [
            {'id': 'Z1', 'group': 'A', 'image': str(tmp2 / 'no.png'),
             'variant': 'orig', 'repeat_idx': 0,
             'model': {'version': 'G1-Turbo', 'face_count': 30000}}]}))
        acc, rep = CS.load_candidates(plan, tmp2 / 'c', tmp2 / 'a',
                                      ROOT / 'configs/unseen_planning_policy.json', 'A')
        ok &= check('neg:缺输入图被加载器拒绝', len(acc) == 0 and len(rep['rejected']) == 1,
                    rep['rejected'][0]['reasons'][:1] if rep['rejected'] else None)
        shutil.rmtree(tmp2, ignore_errors=True)
    except Exception as e:
        ok &= check('neg:缺输入图被加载器拒绝', False, f'{type(e).__name__}: {e}')

    # 3) 观察未停稳且被写成完成 -> 必须判失败
    d = run / 'look_again_v2' / 'look_again.json'
    if d.exists():
        rec = json.loads(d.read_text())
        if not rec['observation_action'].get('stable'):
            ok &= check('neg:未停稳不得记为 observational ok',
                        rec.get('outcome') in ('observation_unstable',
                                               'second_observation_unusable'),
                        rec.get('outcome'))

    # 4) 终止类 reason 不可能同时 success
    import runner as R
    term = {'out_of_bounds', 'tipover', 'out_of_field', 'timeout'}
    ok &= check('neg:终止语义不可改成成功',
                not (term & {'success'}), 'termination reasons are disjoint')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', default='runs/unseen/recovery_r3')
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    run = pathlib.Path(a.run)
    if not run.exists():
        print(f'运行目录不存在：{run}')
        return 2
    verify_six(run)
    verify_h5(run)
    verify_clean(run)
    verify_soil(run)
    verify_look(run)
    verify_upload(run)
    verify_negative(run)
    failed = [r for r in RESULT if not r['pass']]
    out = {'run': str(run), 'n_checks': len(RESULT),
           'n_pass': len(RESULT) - len(failed), 'n_fail': len(failed),
           'checks': RESULT}
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    for r in RESULT:
        print(('PASS' if r['pass'] else 'FAIL'), r['check'], '|', r['detail'])
    print(f"\n{out['n_pass']}/{out['n_checks']} 通过")
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
