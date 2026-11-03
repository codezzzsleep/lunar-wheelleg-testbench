"""按预登记顺序把筛选选中的状态整理成正式集合（供生成/执行使用）。

  python scripts/v3_select.py --protocol plans/v3_protocol.json --max 24
写 runs/v3/selected.json 与 runs/v3/selected.txt，并打印漏斗。
"""
import argparse
import glob
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def key_fn(rocks, levels, views):
    def k(sid):
        try:
            rock, rest = sid.rsplit('_h', 1)
            h, v = rest.split('v')
            return (rocks.index(rock) if rock in rocks else 99, int(h), int(v))
        except Exception:
            return (99, 99, 99)
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--max', type=int, default=24)
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    rocks = proto['grid']['rocks']
    rows = []
    for f in glob.glob(str(ROOT / 'runs/v3/screen/*.json')):
        try:
            d = json.loads(pathlib.Path(f).read_text())
        except Exception:
            continue
        if d.get('state_id'):
            rows.append(d)
    rows.sort(key=lambda d: key_fn(rocks, None, None)(d['state_id']))
    sel = [d['state_id'] for d in rows if d.get('selected')][:a.max]
    funnel = {
        'n_pool_rocks': len(rocks),
        'n_states_planned': len(rocks) * len(proto['grid']['levels']) * len(proto['grid']['views']),
        'n_states_captured': len(rows),
        'n_complete_feasible': sum(1 for d in rows if d.get('complete_feasible')),
        'n_hidden_sensitive': sum(1 for d in rows if d.get('hidden_sensitive')),
        'n_selected': len(sel),
        'rocks_in_selection': sorted({r.split('_h')[0] for r in sel}),
        'layers': {},
        'exclusions': {},
    }
    for d in rows:
        funnel['layers'][d.get('layer', 'none')] = \
            funnel['layers'].get(d.get('layer', 'none'), 0) + 1
        if not d.get('complete_feasible'):
            k = 'no_feasible_traversal'
        elif not d.get('hidden_sensitive'):
            k = 'not_hidden_sensitive'
        else:
            continue
        funnel['exclusions'][k] = funnel['exclusions'].get(k, 0) + 1
    out = {'schema': 'v3-selected/v1', 'protocol': a.protocol,
           'selection_rule': 'hidden_sensitive AND complete_feasible，按来源顺序取样',
           'funnel': funnel, 'selected': sel}
    (ROOT / 'runs/v3/selected.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    (ROOT / 'runs/v3/selected.txt').write_text('\n'.join(sel) + '\n')
    print(json.dumps({'n': len(sel), 'ids': sel,
                      'rocks': funnel['rocks_in_selection']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
