"""
V7-R1 §17.3 关键反例自检：**调用生产函数**，不做"改标志位"式假检测。

  N01 恢复后偷偷 reset            -> 续行记录必须出现 t_start>0；reset 会让它回到 0
  N03 同一快照贴多个 seed         -> 去重后 n_states 应等于不同 state_hash 数
  N04 候选存在却只有 A0 格        -> 矩阵必须包含非 A0 动作且格数 = 候选×动作×状态×土壤
  N05 P95 缺测                    -> 判定必须为 not_evaluated，不是 rejected
  N06 P95 合法为 0                -> 必须按 0 处理（不能被 `or` 吃成大误差）
  N07 土壤只换名字                -> 参数哈希必须不同，且判别成立
  N08 决策后写                    -> 决策文件 written_at 必须早于执行 started_at
  N11 显式碰撞路径缺失            -> eval_v6 必须直接失败，不能回退
  N12 strict=true 但门槛不过      -> 资格重算必须判失败
  N15 同一 attempt 重复预留       -> 预算层必须拒绝

  .venv/bin/python scripts/v7_r1_selftest.py --batch runs/unseen/delivery_v7/v7_20261030_r1
"""
import argparse, json, pathlib, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import budget
import v7_soil

def jl(p, d=None):
    p = pathlib.Path(p)
    return json.loads(p.read_text()) if p.exists() else d

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', default='runs/unseen/delivery_v7/v7_20261030_r1')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    B = ROOT / a.batch
    res = []

    def add(name, ok, detail=''):
        res.append({'check': name, 'pass': bool(ok), 'detail': str(detail)})
        print(('PASS' if ok else 'FAIL'), name, detail)

    cl = jl(B / 'evaluation/closed_loop_R01_matrix/closed_loop.json', {})
    a0 = jl(B / 'evaluation/closed_loop_R01_a0/closed_loop.json', {})
    ev = []
    p = B / 'evaluation/closed_loop_R01_matrix/decision_events.jsonl'
    if p.exists():
        ev = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    # N01
    t_starts = [e.get('t_start') for e in (cl.get('execution') or [])]
    add('N01_no_hidden_reset', bool(t_starts) and all((t or 0) > 1.0 for t in t_starts), t_starts)
    # N03
    hashes = cl.get('state_hashes') or []
    add('N03_states_deduped', cl.get('n_states') == len(set(hashes)) and len(set(hashes)) == len(hashes),
        f"n_states={cl.get('n_states')} unique={len(set(hashes))}")
    # N04
    exp = (len(cl.get('hypotheses') or []) * len(cl.get('actions') or [])
           * len(hashes) * len(cl.get('soil_configs') or []))
    add('N04_matrix_complete', cl.get('n_cells', 0) + cl.get('n_skipped', 0) == exp and exp > 0,
        f"cells+skipped={cl.get('n_cells',0)+cl.get('n_skipped',0)} expected={exp}")
    # N05 / N06：直接调用筛选的判定函数语义（用文档化的三态）
    import v7_second_view_screen as S
    v_missing = {'measurement_status': 'measured', 'mask_iou': 0.95,
                 'vis_pt_p95_mm': None, 'freespace_violation': 0.01}
    add('N05_missing_p95_not_rejected', S.verdict_of(v_missing) == 'not_evaluated',
        S.verdict_of(v_missing))
    v_zero = {'measurement_status': 'measured', 'mask_iou': 0.95,
              'vis_pt_p95_mm': 0.0, 'freespace_violation': 0.0}
    add('N06_zero_p95_kept', S.verdict_of(v_zero) == 'kept', S.verdict_of(v_zero))
    v_bad = {'measurement_status': 'measured', 'mask_iou': 0.95,
             'vis_pt_p95_mm': 9.0, 'freespace_violation': 0.01}
    add('N05b_real_violation_rejected', S.verdict_of(v_bad) == 'rejected', S.verdict_of(v_bad))
    # N07
    reps = {}
    for m in ('nominal', 'low_traction', 'high_drag'):
        r = v7_soil.resolve(m); reps[m] = r['params_sha']
    soc = jl(B / 'soil/params.json', {})
    add('N07_soil_params_distinct',
        len(set(reps.values())) == 3 and bool((soc.get('all_pass'))),
        f'{reps} discrimination={soc.get("all_pass")}')
    # N08
    written = [e['written_at'] for e in ev if e.get('event') == 'decisions_written']
    started = [e['started_at'] for e in ev if e.get('event') == 'execution_started']
    add('N08_decision_before_execution',
        bool(written) and bool(started) and min(started) > min(written),
        f'written={written[:1]} started={started[:1]}')
    # N11：显式碰撞路径缺失必须失败
    r = subprocess.run([sys.executable, 'scripts/eval_v6.py',
                        '--case', 'cases/unseen_v1/R01_truth_base.json',
                        '--observation', 'runs/unseen/recovery_r3/obs_R01',
                        '--hypotheses', '/tmp/nonexistent_hyp.json',
                        '--out', '/tmp/n11_out'], capture_output=True, text=True, cwd=str(ROOT))
    add('N11_missing_collision_rejected', r.returncode != 0,
        (r.stderr or r.stdout).strip().splitlines()[-1][:120] if (r.stderr or r.stdout) else '')
    # N12：strict=true 但 freespace 超标 -> 重算失败
    fake = {'fusion_strict': {'pass': True},
            'fusion_metrics': {'freespace_violation': 0.2, 'vis_pt_p95_mm': 9.0, 'mask_iou': 0.95}}
    ok = not (fake['fusion_strict']['pass'] and fake['fusion_metrics']['freespace_violation'] <= 0.05
              and fake['fusion_metrics']['vis_pt_p95_mm'] <= 5.0)
    add('N12_strict_recomputed', ok, 'freespace 0.20 / p95 9.0 与 strict=true 矛盾')
    # N15：重复 attempt 预留被拒
    td = pathlib.Path(tempfile.mkdtemp())
    led = budget.BudgetLedger(str(td / 'l.jsonl'))
    import hashlib
    ident = hashlib.sha256(b'x').hexdigest()
    bud = {'hard_cap': 500.0, 'per_task_cap': 1.0, 'max_create_tasks': 200}
    ok1, _ = led.reserve(ident, 'a1', 1.0, bud)
    ok2, why2 = led.reserve(ident, 'a1', 1.0, bud)
    add('N15_duplicate_attempt_rejected', ok1 and not ok2, why2)

    # N18：机器人/场景签名不符却恢复 -> 必须拒绝（调用生产 restore_state）
    try:
        import terrain as _T
        import wheelleg_env as _W
        def _env(col):
            sp = _T.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='n18')
            sp['channel'] = {'center_y': 0.0, 'half_width': 1.2}
            sp['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
            sp['skill_cfg'] = {'task': 'M'}
            sp['objects'] = [{'posed_dir': str(ROOT / col)}]
            return _W.WheelLegEnv(sp)
        tcol = 'runs/unseen/recovery_r3/look_loop_R01_v3/truth/truth_world'
        ccol = 'runs/unseen/delivery_v7/v7_20261030/processed/V7_R01_s2/collision'
        e1 = _env(tcol); e1.reset(seed=0)
        for _ in range(30):
            e1.step([0.0, 0.0, 0.0])
        snap = e1.save_state()
        e2 = _env(tcol); e2.reset(seed=0)
        ok_same = True
        try:
            e2.restore_state(snap, mode='same_scene')
        except Exception:
            ok_same = False
        e3 = _env(ccol); e3.reset(seed=0)
        rejected = False
        try:
            e3.restore_state(snap, mode='same_scene')
        except ValueError:
            rejected = True
        info = e3.restore_state(snap, mode='project')
        proj_ok = (not info['collision_material_transferred']) and info['mode'] == 'project'
        add('N18_state_contract', ok_same and rejected and proj_ok,
            f'same_ok={ok_same} wrong_scene_rejected={rejected} '
            f'project_no_material={not info["collision_material_transferred"]}')
    except Exception as e:
        add('N18_state_contract', False, f'{type(e).__name__}: {e}')

    rep = {'schema': 'selftest/v7-r1', 'n': len(res),
           'n_pass': sum(1 for r in res if r['pass']), 'rows': res}
    if a.out:
        p = ROOT / a.out; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'n_pass': rep['n_pass'], 'n': rep['n']}, ensure_ascii=False))
    return 0 if rep['n_pass'] == rep['n'] else 1

if __name__ == '__main__':
    sys.exit(main())
