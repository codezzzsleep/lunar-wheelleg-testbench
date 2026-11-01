"""新留出集筛选（下一批任务书 §7.2）：按冻结规则扫描候选池。

规则在 `plans/holdout_protocol.json` 里先冻结，再扫描：

  入选 = 简单方法在三个确认初态里失败 ≥ 2 次
         且 存在一个非 A0 动作在三个初态全成功

本实现优先复用已有真值扫描（scan_v2.jsonl）；池中缺少扫描记录的对象明确写
`not_scanned`，不补造结果。

  python scripts/v7_holdout_select.py --scan <scan_v2.jsonl> --protocol plans/holdout_protocol.json \
      --out runs/.../holdout
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_scan(path):
    p = ROOT / path if not pathlib.Path(path).is_absolute() else pathlib.Path(path)
    files = sorted(p.glob('*.jsonl')) if p.is_dir() else [p]
    rows = []
    for f in files:
        for line in f.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def screen(rows, protocol, seeds_required=(7, 11, 13)):
    """按规则逐对象判定，返回明细与结论。"""
    seeds = list(seeds_required)
    have_seeds = sorted({r['seed'] for r in rows})
    simple = protocol['selection_rule']['simple_methods']
    out = []
    objs = sorted({(r.get('rock') or r['case'], r.get('scale')) for r in rows})
    for case, scale in objs:
        cells = [r for r in rows if (r.get('rock') or r['case']) == case
                 and r.get('scale') == scale]
        # 简单基线：**实际执行**它们的决策动作，再看该动作的真实结局
        fail_states, detail, missing = 0, {}, []
        for s in seeds:
            per = [r for r in cells if r['seed'] == s]
            if not per:
                missing.append(s)
                detail[f'seed{s}'] = {'evaluated': False}
                continue
            decided = (per[0].get('simple') or {})
            acts = [a for a in decided.values() if a]
            outcomes = {a: next((r['outcome'] for r in per if r['action'] == a), None)
                        for a in acts}
            ok_any = any(o == 'success' for o in outcomes.values())
            detail[f'seed{s}'] = {'evaluated': True, 'simple_actions': decided,
                                  'simple_outcomes': outcomes, 'simple_ok': ok_any,
                                  'actions_ok': sorted({r['action'] for r in per
                                                        if r['outcome'] == 'success'})}
            if not ok_any:
                fail_states += 1
        # 存在非 A0 动作在三个初态全成功
        robust = []
        for act in sorted({r['action'] for r in cells}):
            if act == 'A0':
                continue
            got = {r['seed']: r['outcome'] for r in cells if r['action'] == act}
            if all(got.get(s) == 'success' for s in seeds):
                robust.append(act)
        evaluated = len(seeds) - len(missing)
        status = ('selected' if (evaluated == len(seeds) and fail_states >= 2 and robust)
                  else ('not_evaluated' if missing else 'not_selected'))
        selected = status == 'selected'
        out.append({'object': case if scale is None else f'{case}@{scale}',
                    'case': case, 'scale': scale, 'status': status,
                    'simple_fail_states': fail_states,
                    'evaluated_seeds': evaluated, 'missing_seeds': missing,
                    'robust_actions': robust, 'selected': bool(selected),
                    'detail': detail})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', required=True,
                    help='扫描 jsonl 文件或目录（目录则合并其中所有 *.jsonl）')
    ap.add_argument('--protocol', default='plans/holdout_protocol.json')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    protocol = json.loads((ROOT / a.protocol).read_text())
    rows = load_scan(a.scan)
    res = screen(rows, protocol)
    out_root = ROOT / a.out if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    out_root.mkdir(parents=True, exist_ok=True)
    sel = [r for r in res if r['selected']]
    rep = {'schema': 'holdout-selection/v1', 'protocol': a.protocol,
           'scan': a.scan, 'n_scanned_objects': len(res),
           'n_selected': len(sel), 'selected': [r['object'] for r in sel],
           'seeds_used': sorted({r['seed'] for r in rows}),
           'protocol_confirm_seeds': protocol['confirm_initial_states'],
           'rows': res,
           'pool': protocol['pool'],
           'note': ('只对已扫描对象判定；池中其余对象写 not_scanned，不补造。'
                    '新增真实几何需要付费生成，本批未授权。')}
    (out_root / 'selection.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'n_scanned': len(res), 'n_selected': len(sel),
                      'selected': [r['object'] for r in sel]}, ensure_ascii=False))
    for r in res:
        print(f"  {r['object']:<10} fail_states={r['simple_fail_states']} "
              f"robust={r['robust_actions']} selected={r['selected']}")


if __name__ == '__main__':
    main()
