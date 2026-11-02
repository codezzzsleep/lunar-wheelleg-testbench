"""v2 主评测状态筛选：按冻结规则从 C 对照结果选状态。

入选条件（冻结，先于任何 Lux3D 结果）：
  1. 真实几何在主规划土壤集合（5 点）下至少有一个动作全部通过；
  2. 同一状态直接冲 R1 不能完成任务（R1 在 5 点上不全部通过）。

  python scripts/v2_select_states.py --soil-c <dir> --out <json> --target 30
"""
import argparse, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--soil-c', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--target', type=int, default=30)
    a = ap.parse_args()
    d = ROOT/a.soil_c if not pathlib.Path(a.soil_c).is_absolute() else pathlib.Path(a.soil_c)
    files = sorted(d.rglob('soil_c.json')) if d.is_dir() else [d]
    states = {}
    for f in files:
        j = json.loads(f.read_text())
        for k, v in j['states'].items():
            states[k] = v
    rows = []
    for k, v in sorted(states.items()):
        robust = v['robust_actions']
        # R1 判据：当前真实状态下 R1 的**单次真实结局**必须失败
        r1 = v['actions'].get('R1', {})
        outs = r1.get('outcomes') or []
        # outcomes[0] 是 nominal 单点（C 的第一点集顺序固定），失败即视为"直接冲不能完成"
        r1_fails_now = bool(outs) and outs[0] != 'success'
        selected = bool(robust) and r1_fails_now
        rows.append({'state': k, 'robust_actions': robust,
                     'R1_current_outcome': (r1.get('outcomes') or [None])[0],
                     'R1_fails_now': r1_fails_now,
                     'selected': selected})
    sel = [r for r in rows if r['selected']][:a.target]
    out = {'schema': 'v2-state-selection/v1', 'rule': ['truth robust on 5-point soil set',
                                                       'R1 not robust'],
           'n_scanned_states': len(rows), 'n_selected': len(sel),
           'objects': sorted({r['state'].split('|')[0] for r in sel}),
           'selected': [r['state'] for r in sel],
           'rows': rows}
    p = ROOT/a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'scanned': len(rows), 'selected': len(sel),
                      'objects': out['objects']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
