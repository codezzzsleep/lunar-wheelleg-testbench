"""
V7-R1 §7/§8：观察后的**动作矩阵**、决策先落盘、独立真值续行。

修正（对应审查 P0-1/2/3）：
  · 续行走 `runner.run_from_state`（不 reset）；action_id 不允许为 None；
  · 矩阵 = 候选 × 动作 × **真实不同的观察后状态** × 公开土壤配置；
    同一份快照不会贴成多个 seed，只有一份快照就报告 n=1；
  · 每个单元格各自从对应快照重启，不复用上一个动作执行后的环境；
  · A0 不进入安全集合；`not_applicable` 单元格显式保留；
  · 决策先落盘并定身份，执行行引用 decision_sha；
  · 位移 = final_x - start_x，不把 final_x 当位移。

  .venv/bin/python scripts/v7_closed_loop.py \
      --drive <drive_observe.json> --hypotheses <hyp.json> [--screen <screen.json>] \
      --truth-collision <truth collision dir> --truth-world <truth world dir> \
      --out <dir> [--soil-configs nominal,low_traction]
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import actions as ACT
import decision
import eval_six
import terrain
import v7_soil
import wheelleg_env

TRAVERSE_ACTIONS = ['R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2']


def build_env(col_dir, goal_x, time_limit, soil_label):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=goal_x,
                             name=pathlib.Path(col_dir).name)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}   # 初态由快照给定
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(col_dir)}]
    if soil_label and soil_label != 'rigid':
        r = v7_soil.resolve(soil_label)
        spec['soil'] = {'mode': 'soil', 'label': r.get('label'), 'params': r['params']}
    return wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                    v_ref=1.0, tip_deg=60.0)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--drive', required=True)
    ap.add_argument('--hypotheses', default=None)
    ap.add_argument('--screen', default=None)
    ap.add_argument('--truth-collision', required=True)
    ap.add_argument('--truth-world', required=True)
    ap.add_argument('--visible-json', default=None,
                    help='公共可见量 JSON（W_vis/H_vis/x_front 等）')
    ap.add_argument('--soil-configs', default='nominal')
    ap.add_argument('--actions', default=','.join(TRAVERSE_ACTIONS))
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--time-limit', type=float, default=30.0)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    soil_cfgs = [x for x in a.soil_configs.split(',') if x]
    acts = [x for x in a.actions.split(',') if x]

    drv = json.loads((ROOT / a.drive).read_text())
    vis = json.loads((ROOT / a.visible_json).read_text()) if a.visible_json else {}
    states = []
    for r in drv.get('runs', []):
        if not r.get('usable') or 'env_state' not in r:
            continue
        states.append({'seed': int(r['seed']), 'snapshot': r['env_state'],
                       'state_hash': r['env_state'].get('state_hash'),
                       'start_x': float((r.get('state_snapshot') or {}).get('qpos', [0])[0])})
    if not states:
        raise SystemExit('没有可用的观察后快照（需要 usable 且有 env_state）')
    uniq = {}
    for s in states:
        uniq.setdefault(s['state_hash'], s)
    states = list(uniq.values())

    hyps = []
    if a.hypotheses:
        hyps = json.loads((ROOT / a.hypotheses).read_text())
        if a.screen:
            sc = json.loads((ROOT / a.screen).read_text())
            kept = {r['candidate'] for r in sc.get('rows', [])
                    if r.get('verdict_final') == 'kept'}
            hyps = [h for h in hyps if h['id'] in kept]

    matrix, skipped = [], []
    for h in hyps:
        col = h.get('collision') or h['world']
        for st in states:
            for soil_label in soil_cfgs:
                for act in acts:
                    ok, why = ACT.applicable(act, vis)
                    if not ok:
                        skipped.append({'candidate': h['id'], 'action': act,
                                        'state_hash': st['state_hash'],
                                        'soil_config': soil_label,
                                        'not_applicable': True, 'reason': why})
                        continue
                    try:
                        env = build_env(ROOT / col, a.goal_x, a.time_limit, soil_label)
                        rows = eval_six.run_episode_from_env(
                            env, act, st['seed'], vis, a.goal_x, a.time_limit,
                            hid=h['id'], snapshot=st['snapshot'])
                        for r in rows:
                            r.update({'soil_config': soil_label,
                                      'state_hash': st['state_hash'],
                                      'state_seed': st['seed'], 'candidate': h['id']})
                        matrix += rows
                    except Exception as e:
                        skipped.append({'candidate': h['id'], 'action': act,
                                        'state_hash': st['state_hash'],
                                        'soil_config': soil_label,
                                        'error': f'{type(e).__name__}: {e}'})

    dec = decision.evaluate([r for r in matrix if r.get('option') != 'A0'],
                            [x for x in ACT.OPTIONS if x != 'A0'])
    # 决策矩阵合同校验（重复/缺格/A0 入安全集/无候选未写原因 -> 直接失败）
    import v7_decision_contract as DC
    _exp = {'candidates': [h['id'] for h in hyps], 'actions': acts,
            'states': [s_['state_hash'] for s_ in states], 'soil_configs': soil_cfgs}
    _chk = DC.validate(matrix, dict(dec, safe_set=dec.get('safe_set') or [],
                                    reason=dec.get('reason') or (
                                        'no_candidate_after_second_view' if not hyps else '')),
                       _exp, not_applicable=skipped)
    if not _chk['ok']:
        raise SystemExit(f'决策矩阵合同失败：{_chk["errors"][:3]}')
    dec['contract'] = _chk['stats']
    dec.update({'n_cells': len(matrix), 'n_skipped': len(skipped),
                'n_states': len(states), 'n_candidates': len(hyps),
                'n_soil': len(soil_cfgs), 'actions': acts,
                'decision_rule': 'worst-case-risk/v2'})

    payload = json.dumps(dec, ensure_ascii=False, sort_keys=True)
    dec_sha = sha(payload)
    written_at = time.time()
    (out / 'decisions.json').write_text(json.dumps(
        {'schema': 'closed-loop-decisions/v7', 'decision_sha': dec_sha,
         'written_at': written_at, 'decision': dec}, ensure_ascii=False, indent=2))
    events = [{'event': 'decisions_written', 'decision_sha': dec_sha,
               'written_at': written_at, 'n_cells': len(matrix)}]

    chosen = 'A0' if not hyps else dec['chosen']
    branch = 'a0_fallback_no_candidate' if not hyps else 'matrix_decision'
    exec_rows = []
    for st in states:
        tenv = build_env(ROOT / a.truth_collision, a.goal_x, a.time_limit, soil_cfgs[0])
        started = time.time()
        rows = eval_six.run_episode_from_env(
            tenv, chosen, st['seed'], vis, a.goal_x, a.time_limit,
            hid='TRUTH_continue', snapshot=st['snapshot'])
        for r in rows:
            r.update({'method': 'closed_loop', 'phase': 'execution',
                      'decision_sha': dec_sha, 'execution_started_at': started,
                      'truth_world': a.truth_world,
                      'truth_collision': a.truth_collision,
                      'start_x': st['start_x'], 'state_hash': st['state_hash'],
                      'state_seed': st['seed']})
            r['displacement_x'] = round(float(r['final_x']) - float(st['start_x']), 4)
        exec_rows += rows
        events.append({'event': 'execution_started', 'decision_sha': dec_sha,
                       'seed': st['seed'], 'action': chosen, 'started_at': started,
                       'after_decision_write': started > written_at})

    with (out / 'decision_events.jsonl').open('w') as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    with (out / 'matrix.jsonl').open('w') as f:
        for r in matrix:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    rec = {
        'schema': 'closed-loop/v7',
        'drive': a.drive, 'hypotheses': [h['id'] for h in hyps],
        'n_states': len(states), 'state_hashes': [s['state_hash'] for s in states],
        'n_cells': len(matrix), 'n_skipped': len(skipped),
        'soil_configs': soil_cfgs, 'actions': acts,
        'decision': {k: dec.get(k) for k in ('chosen', 'safe_set', 'reason', 'n_cells')},
        'decision_sha': dec_sha, 'decision_written_at': written_at,
        'branch': branch, 'execution': exec_rows, 'skipped': skipped,
        'contract': ('续行走 runner.run_from_state（不 reset）；每个单元格各自从快照重启；'
                     '决策先落盘并定身份，执行行引用 decision_sha；A0 不计任务成功；'
                     '位移 = final_x - start_x；不适用单元格显式保留。'),
    }
    (out / 'closed_loop.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({'chosen': chosen, 'branch': branch, 'n_cells': len(matrix),
                      'n_states': len(states), 'n_hypotheses': len(hyps),
                      'exec': [{k: r.get(k) for k in ('option', 'success', 'reason',
                                                      'displacement_x', 'sim_time_s_')}
                               for r in exec_rows]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
