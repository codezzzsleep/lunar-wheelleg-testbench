"""v7.2 重新决策：同一观测、同一批 Lux3D 结果，只换修正后的尺寸比（从地面量起）。

不调用 Lux3D，不改动原运行目录，结果写到 --out。

    MUJOCO_GL=egl python3 scripts/v7/v7_redecide.py --run runs/v7/route_full_r2 --out runs/v7/route_full_r2_v72

对每个遭遇的每一眼重新运行 v7_encounter.decide（完整 8 个动作 × 3 种扰动），
再把每个遭遇最终选中的动作与原运行实际执行的动作（events.jsonl）对比：
  全部相同 -> 退出码 0：原运行的执行轨迹就是 v7.2 决策会产生的轨迹，无需重跑路线；
  有不同   -> 退出码 3：停下回报。
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(HERE))
import v7_encounter as VE  # noqa: E402


def glbs_of(look_dir):
    res = json.loads((look_dir / 'lux_result.json').read_text())
    return [{'id': t['id'], 'glb': str(ROOT / t['glb'])} for t in res['tasks'] if t.get('status') == 'ok' and t.get('glb')]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--run', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    run = (ROOT / a.run).resolve(); out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    events = [json.loads(l) for l in (run / 'events.jsonl').read_text().splitlines() if l.strip()]
    executed = {e['encounter']: e['action'] for e in events if 'action' in e and 'encounter' in e}
    rows, final = [], {}
    for enc in ('E1', 'E2'):
        for look in ('look1', 'look2'):
            ld = run / enc / look
            if not (ld / 'state.json').exists():
                continue
            if look == 'look2' and final.get(enc, {}).get('branch') == 'accept':
                rows.append({'encounter': enc, 'look': look, 'note': 'v7.2 在第一眼已采纳，不会走到第二眼'}); continue
            dec = VE.decide(ld, glbs_of(ld), out / enc / f'decide_{look}')
            r = {'encounter': enc, 'look': look, 'branch': dec['branch'], 'n_candidates': dec['n_candidates'], 'n_admitted': dec['n_admitted'],
                 'full_chosen': dec['full']['chosen'], 'worst_rule': dec['full']['worst_rule'], 'obs_chosen': dec['obs_cons']['chosen'],
                 'fallback': dec['full']['fallback'],
                 'candidates': [{k: c[k] for k in ('id', 'admitted', 'scale_ratio', 'scale_ratio_v5', 'contour_iou', 'free_intrusion_frac')}
                                for c in json.loads((out / enc / f'decide_{look}' / 'candidates.json').read_text())]}
            rows.append(r); final[enc] = r
            print(json.dumps({k: r[k] for k in ('encounter', 'look', 'branch', 'n_admitted', 'full_chosen', 'obs_chosen')}, ensure_ascii=False))
    cmp = {enc: {'v72_action': final[enc]['full_chosen'], 'executed': executed.get(enc),
                 'same': final[enc]['full_chosen'] == executed.get(enc)} for enc in final}
    summ = {'schema': 'v7-redecide/v1', 'metric_version': 2, 'run': str(run.relative_to(ROOT)), 'rows': rows, 'compare': cmp,
            'all_same': all(v['same'] for v in cmp.values())}
    (out / 'summary.json').write_text(json.dumps(summ, indent=2, ensure_ascii=False))
    print(json.dumps(cmp, ensure_ascii=False))
    sys.exit(0 if summ['all_same'] else 3)


if __name__ == '__main__':
    main()
