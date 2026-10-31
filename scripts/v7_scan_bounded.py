"""有界案例扫描（任务书 §二）：4 对象 × 3 尺寸 × 7 动作 × 2 初态 ≤ 168 回合。

协议先冻结在 plans/unseen_r1_scan_protocol.json；本脚本只执行，不按结果追加。
每个回合记录 outcome（success / not_applicable / sim_error / timeout / tipped / out_of_bounds）、
时间、位移与 final_x，全部保留分母。

  /opt/lunar/bin/python scripts/v7_scan_bounded.py --out runs/.../scan_r1 --limit 168
"""
import argparse, json, pathlib, sys, traceback
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np
import eval_six, runner, skills, actions as ACT


def one(case_dir, action, seed, soil, seconds, goal_x):
    env = eval_six.build_env(ROOT / case_dir, goal_x, seconds, soil, seed)
    obs, _ = env.reset(seed=seed)
    vis = {}
    try:
        import v7_visible_public as VP
        vis = VP.visible_from_obs(ROOT / case_dir) if hasattr(VP, 'visible_from_obs') else {}
    except Exception:
        vis = {}
    ok, why = ACT.applicable(action, vis)
    if not ok:
        return {'outcome': 'not_applicable', 'reason': why}
    r = runner.EpisodeRunner(env, skills.make_skill(action), visible=vis, seed=seed)
    o = r.run()
    reason = (o.get('reason') or '').lower()
    if o.get('success'):
        outcome = 'success'
    elif 'tip' in reason or (o.get('max_tilt') or 0) > 60:
        outcome = 'tipped'
    elif 'bound' in reason or 'oob' in reason:
        outcome = 'out_of_bounds'
    elif 'time' in reason:
        outcome = 'timeout'
    else:
        outcome = 'abort'
    return {'outcome': outcome, 'reason': o.get('reason'),
            'final_x': o.get('final_x'), 'displacement_x': o.get('displacement_x'),
            't_end': o.get('t_end'), 'max_tilt': o.get('max_tilt')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/unseen_r1_scan_protocol.json')
    ap.add_argument('--out', required=True)
    ap.add_argument('--limit', type=int, default=168)
    ap.add_argument('--seconds', type=float, default=30.0)
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--objects', default=None, help='只跑指定对象，逗号分隔')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    out = ROOT / a.out; out.mkdir(parents=True, exist_ok=True)
    rows = []
    n = 0
    objs = a.objects.split(',') if a.objects else proto['objects']
    for obj in objs:
        for scale in proto['size_levels']['scales']:
            cand = f'runs/unseen/delivery_v7/v7_20261030/processed/V7_{obj}_s1/collision'
            if not (ROOT / cand).exists():
                rows.append({'object': obj, 'scale': scale, 'action': None,
                             'outcome': 'missing_asset', 'asset': cand})
                continue
            for act in proto['actions']:
                for st in proto['initial_states']:
                    if n >= min(a.limit, proto['max_episodes']):
                        break
                    rec = {'object': obj, 'scale': scale, 'action': act, 'seed': st['seed'],
                           'asset': cand}
                    try:
                        rec.update(one(cand, act, st['seed'], proto['soil'], a.seconds, a.goal_x))
                    except Exception as e:
                        rec.update({'outcome': 'sim_error',
                                    'error': f'{type(e).__name__}: {e}',
                                    'trace': traceback.format_exc().splitlines()[-3:]})
                    rows.append(rec); n += 1
                    (out / 'scan.jsonl').write_text(
                        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
    summary = {}
    for r in rows:
        summary.setdefault(r['object'], {}).setdefault(r['outcome'], 0)
        summary[r['object']][r['outcome']] += 1
    (out / 'scan_summary.json').write_text(json.dumps(
        {'n_episodes': n, 'protocol': a.protocol, 'by_object': summary}, ensure_ascii=False, indent=2))
    print(json.dumps({'n': n, 'by_object': summary}, ensure_ascii=False))


if __name__ == '__main__':
    main()
