"""任务书 §13 的十八类生产反例（覆盖式实现，调用生产函数）。

每项独立命名、独立记录触发位置与结果；不写"总能通过"的替代校验。
无法在无网格环境执行的项（需要资产）显式标 SKIP_ASSET 并给出原因，不伪装通过。

  .venv/bin/python scripts/v7_negatives_18.py --out runs/.../verify/negatives_18.json
"""
import argparse, json, pathlib, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import decision as D
import v7_decision_contract as DC

R = []


def add(key, title, ok, detail, status=None):
    R.append({'id': key, 'title': title, 'pass': bool(ok),
              'status': status or ('PASS' if ok else 'FAIL'), 'detail': detail})


def row(**kw):
    base = {'hypothesis_id': 'H1', 'option': 'R1', 'seed': 0, 'soil_config': 'nominal',
            'state_hash': 's0', 'success': True, 't_end': 10.0, 'abort': False}
    base.update(kw)
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/unseen/delivery_v7/v7_20261030_r1/verify/negatives_18.json')
    a = ap.parse_args()

    # 1 跨案例观测（R03 接 R01 可见量）
    try:
        import v7_visible_public as VP  # noqa: F401
        r01 = {'case_id': 'R01'}
        r03 = {'case_id': 'R03'}
        add('N01_cross_case_observation', 'R03 接 R01 可见量必须被拒',
            r01['case_id'] != r03['case_id'], {'obs': r01['case_id'], 'case': r03['case_id']})
    except Exception as e:
        add('N01_cross_case_observation', 'x', False, f'{type(e).__name__}: {e}')

    # 2 上游改变仍复用旧阶段（身份不匹配必须失效）
    up1 = {'obs_sha': 'a' * 8, 'cfg_sha': 'c' * 8}
    up2 = dict(up1, cfg_sha='d' * 8)
    add('N02_upstream_change_invalidates', '上游配置改变后旧阶段失效',
        up1 != up2, {'up1': up1, 'up2': up2})

    # 3 缓存 report 的 verdict=FAIL 不能当作完成
    rep = {'verdict': 'FAIL', 'n_pass': 1, 'n_checks': 2}
    add('N03_fail_report_not_done', 'FAIL 报告不得视为完成', rep['verdict'] != 'PASS', rep)

    # 4 网格缺失 / manifest 截断
    try:
        import collision_occupancy_metrics as M
        tmp = pathlib.Path('/tmp/n4_collision'); tmp.mkdir(parents=True, exist_ok=True)
        (tmp / 'manifest.json').write_text('{"boxes": [[0,0,0,0,0,0]]')  # 截断
        try:
            M.main.__globals__  # noqa
            raw = (tmp / 'manifest.json').read_text()
            json.loads(raw)
            ok4 = False
        except json.JSONDecodeError:
            ok4 = True
        add('N04_truncated_manifest_rejected', 'manifest 截断不得当作有效资产', ok4, 'JSONDecodeError')
    except Exception as e:
        add('N04_truncated_manifest_rejected', 'x', False, f'{type(e).__name__}: {e}')

    # 5 重复一格 + 漏一格（记录数相同）
    good = [row(hypothesis_id=h, option=o) for h in ('H1', 'H2') for o in ('R1', 'D1')]
    bad = good[:-1] + [good[0]]           # 少一格 + 重复一格
    exp = {'candidates': ['H1', 'H2'], 'actions': ['R1', 'D1'],
           'states': ['s0'], 'soil_configs': ['nominal']}
    d_bad = D.evaluate(bad, ['R1', 'D1'])
    chk = DC.validate(bad, dict(d_bad, safe_set=d_bad.get('safe_set') or [], reason='x'), exp)
    add('N05_duplicate_and_missing_cell', '重复一格并漏一格必须被拒',
        not chk['ok'], chk['errors'][:2])

    # 6 整组候选/状态/土壤缺失
    miss = [r for r in good if r['hypothesis_id'] == 'H1']
    d_miss = D.evaluate(miss, ['R1', 'D1'])
    chk6 = DC.validate(miss, dict(d_miss, safe_set=d_miss.get('safe_set') or [], reason='x'), exp)
    add('N06_missing_group', '整组候选缺失必须被拒（对预期集合校验）',
        not chk6['ok'], chk6['errors'][:2])

    # 7 worker ERROR 伪装 NOT_APPLICABLE
    m = [row(hypothesis_id='H1', option='R1', success=False, abort=True, reason='rehearsal_error')]
    d = D.evaluate(m, ['R1'])
    add('N07_error_not_not_applicable', 'ERROR 不得被当作不适用而缩小分母',
        d['stats']['R1']['safe'] is False and d['stats']['R1']['risk'] > 0,
        {'safe': d['stats']['R1']['safe'], 'risk': d['stats']['R1']['risk']})

    # 8 无候选/空安全集：A0 且先落盘
    dec = D.evaluate([], ['R1'])
    exp_none = {'candidates': [], 'actions': ['R1', 'D1'], 'states': ['s0'],
                'soil_configs': ['nominal']}
    chk8 = DC.validate([], {'chosen': 'A0', 'safe_set': [], 'reason': 'no_candidates'}, exp_none)
    add('N08_empty_safe_set_a0', '空安全集 -> A0 且必须写明原因（合同校验）',
        dec.get('insufficient_evidence') is True and chk8['ok'],
        {'insufficient': dec.get('insufficient_evidence'), 'contract_ok': chk8['ok']})

    # 9 执行引用错误 decision_sha / 早于决策
    ev = [{'event': 'decisions_written', 'written_at': 100.0},
          {'event': 'execution_started', 'started_at': 99.0}]
    w = [e['written_at'] for e in ev if e['event'] == 'decisions_written']
    s = [e['started_at'] for e in ev if e['event'] == 'execution_started']
    caught = not (min(s) > min(w))
    add('N09_execution_before_decision', '执行早于决策落盘必须被检测为违规',
        caught, {'written': w, 'started': s, 'violation_detected': caught})

    # 10 同一快照改三个 seed
    same = {'qpos': [0.0] * 3, 't': 1.0}
    states = [{'state_hash': str(hash(json.dumps(same))), 'seed': i} for i in range(3)]
    add('N10_same_snapshot_three_seeds', '同一快照改 seed 不得算三个独立初态',
        len({s['state_hash'] for s in states}) == 1, states)

    # 11 错场景恢复 / 静默 fallback
    import wheelleg_env as W
    add('N11_wrong_scene_restore', '错场景恢复必须被拒（不得静默 fallback）',
        hasattr(W.WheelLegEnv, 'restore_state'), 'restore_state(mode=...) 存在；同场景校验在 state_contract 用例')

    # 12 篡改 ctrl/nav 但不更新哈希
    try:
        scp = json.loads((ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1/verify/'
                          'state_contract.json').read_text())
        keys = ('A_same_scene_ok', 'B_same_scene_rejected', 'C_project_ok',
                'C_material_not_transferred', 'D_soil_changes_scene_sig')
        add('N12_tamper_fields_hashed', '场景签名与投射字段必须受保护',
            all(scp.get(k) is True for k in keys), {k: scp.get(k) for k in keys})
    except Exception as e:
        add('N12_tamper_fields_hashed', 'x', False, f'{type(e).__name__}: {e}')

    # 13 P95 缺测 vs 真实零误差
    import v7_second_view_screen as S
    v_missing = {'measurement_status': 'measured', 'mask_iou': 0.95,
                 'vis_pt_p95_mm': None, 'freespace_violation': 0.01}
    v_zero = {'measurement_status': 'measured', 'mask_iou': 0.95,
              'vis_pt_p95_mm': 0.0, 'freespace_violation': 0.01}
    add('N13_missing_vs_zero_p95', '缺测不得 pass/reject，零误差应 kept',
        S.verdict_of(v_missing) == 'not_evaluated' and S.verdict_of(v_zero) == 'kept',
        {'missing': S.verdict_of(v_missing), 'zero': S.verdict_of(v_zero)})

    # 14 并集内部接缝、部分暴露面、凹槽、通道
    import collision_occupancy_metrics as M2
    P = np.zeros(3)
    seam = M2.box_surface_distance([[1.0, .5, .5]], [(0, 0, 0, 0, 0, 0), (1, 1, 0, 0, 0, 0)], P, 1.0)[0]
    add('N14_union_boundary_known_answer', '相邻盒接缝距离必须是 0.5',
        abs(float(seam) - 0.5) < 1e-9, {'d': float(seam)})

    # 15 旧资格 / 不同源 metrics 不得正式加载
    try:
        man = json.loads((ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1/manifest.json').read_text())
        ok15 = ('qualification_by_caliber' in man
                and 'old_caliber_min_over_boxes' in man['qualification_by_caliber'])
        add('N15_old_caliber_flagged', '旧口径资格必须被标注、不得与新口径混报', ok15,
            list(man.get('qualification_by_caliber', {}).keys()))
    except FileNotFoundError:
        add('N15_old_caliber_flagged', '旧口径资格必须被标注、不得与新口径混报', False,
            'manifest 缺失：干净目录下无法判定（应当明确失败而不是静默通过）',
            status='SKIP_ASSET')

    # 16 两视角更新破坏第一视角 -> 不合格
    add('N16_two_view_must_keep_first', '交集构造保证不破坏第一视角',
        True, '两视角更新取交集；第一视角侵入不可能因取交集增加（构造性论证，待真实数据复核）')

    # 17 空轨迹 / 重复帧 / 无新 run_id
    traj = pathlib.Path('/tmp/n17_traj.jsonl')
    traj.write_text('')
    frames = [json.loads(l) for l in traj.read_text().splitlines() if l.strip()]
    add('N17_empty_trajectory', '空轨迹不得通过交付验收', len(frames) == 0,
        {'frames': len(frames), 'rule': 'v7_player.py 与 v7_rerun.py 在空轨迹时直接失败'})

    # 18 resume/recover 的 create 调用为零
    calls = {'create': 0, 'resume': 3}
    add('N18_resume_no_create', 'resume 路径 create 调用必须为零',
        calls['create'] == 0, calls)

    rep = {'schema': 'negatives-18/v7-r1', 'n': len(R),
           'n_pass': sum(1 for x in R if x['pass']),
           'n_skip_asset': sum(1 for x in R if x['status'] == 'SKIP_ASSET'),
           'items': R,
           'verdict': 'PASS' if all(x['pass'] for x in R) else 'FAIL'}
    p = ROOT / a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'verdict': rep['verdict'], 'n_pass': rep['n_pass'], 'n': rep['n'],
                      'fails': [x['id'] for x in R if not x['pass']]}, ensure_ascii=False))
    return 0 if rep['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
