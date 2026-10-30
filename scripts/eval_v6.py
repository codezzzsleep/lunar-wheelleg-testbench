"""
V6 正式比较：H5_raw / H5_F_single / B3_F / H5_F_multi / B0 / U_truth。

同一真值、同一初态、同一 30 s 协议；决策统一走 decision.worst-case-risk/v2。
方法只使用自己允许的候选；H5_F/B3_F 不读真值；U_truth 是拥有完整真值的上限参考。
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import actions as ACT
import decision
import eval_six as ES
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
OPTIONS = list(ACT.OPTIONS)


def sha(p):
    h = hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()


def build_truth(case, out):
    case = json.loads(pathlib.Path(case).read_text()) if isinstance(case, (str, pathlib.Path)) else case
    m = trimesh.load(case['mesh'], force='mesh')
    m.apply_translation([float(case.get('obstacle_x', 0.0)), 0.0, -float(m.bounds[0][2])])
    d = pathlib.Path(out) / 'truth_world'; d.mkdir(parents=True, exist_ok=True)
    m.export(d / 'body.stl')
    h = sha(d / 'body.stl')
    (d / 'manifest.json').write_text(json.dumps({'schema': 'asset-manifest/v1',
                                                 'coordinate_frame': 'world',
                                                 'parts': ['body.stl'], 'world_sha': h,
                                                 'source_kind': 'truth'}, indent=2))
    return d, h


def collize(world, out, hid, max_parts=32, skip_probe=True):
    d = pathlib.Path(out) / hid
    if (d / 'manifest.json').exists():
        return d, json.loads((d / 'manifest.json').read_text())
    cmd = [sys.executable, str(ROOT / 'scripts/physicalize.py'), '--mesh', str(world / 'body.stl'),
           '--out', str(d), '--hypothesis-id', hid, '--max-parts', str(max_parts)]
    if skip_probe:
        cmd.append('--skip-probe')
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f'physicalize failed {hid}: {r.stderr[-500:]}')
    return d, json.loads((d / 'manifest.json').read_text())


def rehearse(hyp, visible, seeds, goal_x, time_limit):
    rows = []
    for o in OPTIONS:
        if o == 'A0':
            continue
        ok, why = ACT.applicable(o, visible)
        for sd in seeds:
            if not ok:
                rows.append({'hypothesis_id': hyp['id'], 'option': o, 'seed': sd,
                             'not_applicable': why, 'success': False, 'abort': False,
                             'reason': why, 't_end': None, 'cost': None,
                             'source_kind': hyp['source_kind']})
                continue
            r = ES.run_episode(hyp['collision'], o, sd, visible, goal_x, time_limit)
            r.update({'hypothesis_id': hyp['id'], 'source_kind': hyp['source_kind'],
                      'phase': 'rehearsal', 'truth_sha': None,
                      'collision_sha': hyp.get('collision_sha')})
            rows.append(r)
    return rows


def execute_truth(truth_col, truth_sha, method, option, seeds, visible, goal_x, time_limit):
    rows = []
    for sd in seeds:
        r = ES.run_episode(truth_col, option, sd, visible, goal_x, time_limit)
        r.update({'method': method, 'option': option, 'seed': sd,
                  'phase': 'execution', 'truth_sha': truth_sha,
                  'is_truth': True})
        rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--observation', required=True)
    ap.add_argument('--hypotheses', required=True,
                    help='JSON list {id,kind,world,collision(optional),source_kind,strict_pass}')
    ap.add_argument('--out', required=True)
    ap.add_argument('--methods', default='H5_raw,H5_F_single,B3_F,B0_blind,U_truth')
    ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--validation-seeds', default='3,4,5,6,7')
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--time-limit', type=float, default=30.0)
    ap.add_argument('--max-parts', type=int, default=32)
    ap.add_argument('--truth-collision', default=None,
                    help='可选：真值执行用的碰撞体目录（如 box 并集），缺省则用 CoACD')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    obs = json.loads((pathlib.Path(a.observation) / 'observation.json').read_text())
    visible = obs['visible']
    seeds = [int(x) for x in a.seeds.split(',') if x.strip()]
    vseeds = [int(x) for x in a.validation_seeds.split(',') if x.strip()]
    methods = [x for x in a.methods.split(',') if x]
    hyps_in = json.loads(pathlib.Path(a.hypotheses).read_text())
    truth_world, truth_sha = build_truth(a.case, out)
    if a.truth_collision and pathlib.Path(a.truth_collision).exists():
        truth_col = pathlib.Path(a.truth_collision)
        truth_man = json.loads((truth_col / 'manifest.json').read_text())
    else:
        truth_col, truth_man = collize(truth_world, out / 'collision', 'TRUTH', a.max_parts)
    truth_col_sha = truth_man.get('collision_sha')

    hyps = {}
    for h in hyps_in:
        wd = pathlib.Path(h['world'])
        if h.get('collision'):
            # 显式指定碰撞目录时必须可用；不允许静默换成 CoACD 继续比较
            cd = pathlib.Path(h['collision'])
            if not cd.exists():
                raise SystemExit(f'指定的碰撞目录不存在：{cd}（拒绝回退到 CoACD）')
            mf = cd / 'manifest.json'
            if not mf.exists():
                raise SystemExit(f'碰撞目录缺少 manifest.json：{cd}')
            cm = json.loads(mf.read_text())
            if not (cm.get('boxes') or cm.get('parts')):
                raise SystemExit(f'碰撞 manifest 没有几何：{cd}')
            if not cm.get('collision_sha'):
                raise SystemExit(f'碰撞 manifest 缺少 collision_sha：{cd}')
            src_sha = (cm.get('cache_identity') or {}).get('source_sha') or cm.get('world_sha')
            world_sha = sha(pathlib.Path(h['world']) / 'body.stl')
            if src_sha and src_sha != world_sha:
                raise SystemExit(
                    f'碰撞与源实体不匹配：collision 来自 {src_sha[:12]}，候选是 {world_sha[:12]}')
        else:
            cd, cm = collize(wd, out / 'collision', h['id'], a.max_parts)
        hyps[h['id']] = {**h, 'world_dir': str(wd), 'collision': str(cd),
                         'collision_sha': cm.get('collision_sha'),
                         'parts': cm.get('coacd_parts'),
                         'manifest': cm}

    records = []
    decisions = []
    pending = []
    summary_methods = []
    truth_records = {}
    for method in methods:
        if method == 'B0_blind':
            dec = {'rule': 'B0_blind', 'chosen': 'R1', 'safe_set': ['R1'],
                   'stats': {}, 'no_robust_option': False, 'insufficient_evidence': False}
            matrix = []
        elif method == 'U_truth':
            truth_hyp = {'id': 'U_truth', 'kind': 'truth', 'source_kind': 'truth',
                         'world_dir': str(truth_world), 'collision': str(truth_col),
                         'collision_sha': truth_col_sha}
            matrix = rehearse(truth_hyp, visible, seeds, a.goal_x, a.time_limit)
            dec = decision.evaluate(matrix, OPTIONS)
        elif method == 'H5_raw':
            if 'H5_raw' not in hyps:
                summary_methods.append({'method': method, 'no_candidate': True,
                                        'selected_action': None, 'n_expected': 0,
                                        'success': 0, 'n_exec': 0, 'complete': True,
                                        'no_robust_option': True, 'reason': 'no H5_raw'})
                continue
            matrix = rehearse(hyps['H5_raw'], visible, seeds, a.goal_x, a.time_limit)
            dec = decision.evaluate(matrix, OPTIONS)
        elif method == 'H5_F_single':
            if 'H5_F_single' not in hyps:
                summary_methods.append({'method': method, 'no_candidate': True,
                                        'selected_action': None, 'n_expected': 0,
                                        'success': 0, 'n_exec': 0, 'complete': True,
                                        'no_robust_option': True, 'reason': 'no H5_F_single'})
                continue
            matrix = rehearse(hyps['H5_F_single'], visible, seeds, a.goal_x, a.time_limit)
            dec = decision.evaluate(matrix, OPTIONS)
        elif method == 'H5_F_multi':
            members = [h for h in hyps.values() if h.get('multi_member')]
            if members:
                # 真正的多假设：每个候选各自预演，矩阵保持 (候选 × 动作 × 初态)，
                # 由 decision.evaluate 在假设内取最坏、再跨假设取最坏。
                matrix = []
                for h in sorted(members, key=lambda x: x['id']):
                    matrix += rehearse(h, visible, seeds, a.goal_x, a.time_limit)
                dec = decision.evaluate(matrix, OPTIONS)
                dec['n_members'] = len(members)
                dec['members'] = [h['id'] for h in sorted(members, key=lambda x: x['id'])]
            elif 'H5_F_multi' in hyps:
                matrix = rehearse(hyps['H5_F_multi'], visible, seeds, a.goal_x, a.time_limit)
                dec = decision.evaluate(matrix, OPTIONS)
                dec['n_members'] = 1
                dec['members'] = ['H5_F_multi']
            else:
                summary_methods.append({'method': method, 'no_candidate': True,
                                        'selected_action': None, 'n_expected': 0,
                                        'success': 0, 'n_exec': 0, 'complete': True,
                                        'no_robust_option': True,
                                        'reason': 'no multi members and no H5_F_multi'})
                continue
        elif method == 'B3_F':
            if 'B3_F' not in hyps:
                summary_methods.append({'method': method, 'no_candidate': True,
                                        'selected_action': None, 'n_expected': 0,
                                        'success': 0, 'n_exec': 0, 'complete': True,
                                        'no_robust_option': True, 'reason': 'no B3_F'})
                continue
            matrix = rehearse(hyps['B3_F'], visible, seeds, a.goal_x, a.time_limit)
            dec = decision.evaluate(matrix, OPTIONS)
        else:
            raise SystemExit(f'unknown method {method}')
        dec['method'] = method
        decisions.append(dec)
        records += matrix
        pending.append((method, dec))
    # ---- 决策先落盘：所有方法的决策在**任何真值执行之前**写入并定身份 ----
    import hashlib as _h, time as _t
    _dec_payload = json.dumps(decisions, ensure_ascii=False, sort_keys=True)
    _dec_sha = _h.sha256(_dec_payload.encode()).hexdigest()
    _written_at = _t.time()
    (out / 'decisions.json').write_text(json.dumps(
        {'schema': 'decision-bundle/v6_1', 'decision_sha': _dec_sha,
         'written_at': _written_at, 'decisions': decisions},
        ensure_ascii=False, indent=2))
    for method, dec in pending:
        _exec_started_at = __import__('time').time()
        chosen = 'R1' if method == 'B0_blind' else dec['chosen']
        exec_rows = execute_truth(truth_col, truth_sha, method, chosen,
                                  seeds, visible, a.goal_x, a.time_limit)
        if chosen != 'R1':
            exec_rows += execute_truth(truth_col, truth_sha, method, 'R1',
                                       seeds, visible, a.goal_x, a.time_limit)
        if chosen != 'A0':
            exec_rows += execute_truth(truth_col, truth_sha, method, 'A0',
                                       seeds, visible, a.goal_x, a.time_limit)
        val_rows = execute_truth(truth_col, truth_sha, method, chosen,
                                 vseeds, visible, a.goal_x, a.time_limit)
        for r in exec_rows + val_rows:
            r['decision_sha'] = _dec_sha
            r['decision_written_at'] = _written_at
            r.setdefault('started_at', _exec_started_at)
        records += exec_rows + val_rows
        chosen_rows = [r for r in exec_rows if r.get('option') == chosen]
        val_chosen = [r for r in val_rows if r.get('option') == chosen]
        abort = sum(1 for r in chosen_rows if r.get('abort'))
        fail = sum(1 for r in chosen_rows if not r.get('success') and not r.get('abort'))
        costs = [(r.get('t_end') if r.get('success') else
                  (40.0 if r.get('abort') else 60.0)) for r in chosen_rows]
        summary_methods.append({
            'method': method, 'selected_action': chosen,
            'n_exec': len(chosen_rows), 'n_expected': len(seeds),
            'complete': len(chosen_rows) == len(seeds),
            'success': sum(1 for r in chosen_rows if r.get('success')),
            'abort': abort, 'fail': fail,
            'mean_cost': round(float(np.mean(costs)), 3) if costs else None,
            'outcomes': [r.get('reason') for r in chosen_rows],
            'validation_success': sum(1 for r in val_chosen if r.get('success')),
            'validation_n': len(val_chosen),
            'decision_sha': _dec_sha,
            'n_hypotheses': dec.get('n_members', 1),
        })
        truth_records[method] = exec_rows + val_rows

    (out / 'rehearsal.jsonl').write_text('\n'.join(
        json.dumps(r, ensure_ascii=False) for r in records
        if r.get('phase') == 'rehearsal') + '\n')
    (out / 'execution.jsonl').write_text('\n'.join(
        json.dumps(r, ensure_ascii=False) for m in truth_records.values() for r in m) + '\n')
    summary = {
        'schema': 'eval-v6/v1', 'case': json.loads(pathlib.Path(a.case).read_text()).get('case_id'),
        'truth_sha': truth_sha, 'truth_collision_sha': truth_col_sha,
        'time_limit_s': a.time_limit, 'seeds': seeds, 'validation_seeds': vseeds,
        'decision_sha': _dec_sha, 'decision_written_at': _written_at,
        'decision_rule': 'worst-case-risk/v2', 'methods': summary_methods,
        'hypotheses': [{'id': h['id'], 'kind': h.get('kind'),
                        'world_sha': sha(pathlib.Path(h['world_dir']) / 'body.stl'),
                        'collision_sha': h.get('collision_sha'),
                        'parts': h.get('parts'), 'strict_pass': h.get('strict_pass'),
                        'source_kind': h.get('source_kind')} for h in hyps.values()],
        'note': ('H5_F/B3_F 的可见面由观测约束构造；visible strict pass 不等于 Lux3D 原始模型通过。'
                 'U_truth 是上限参考，不冒充真实可用方法。'),
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({m['method']: {'chosen': m.get('selected_action'),
                                    'success': f"{m.get('success')}/{m.get('n_exec')}",
                                    'val': f"{m.get('validation_success')}/{m.get('validation_n')}"}
                      for m in summary_methods}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
