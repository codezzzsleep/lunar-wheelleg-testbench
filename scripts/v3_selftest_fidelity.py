"""回归：同一 spec/快照/动作，same_scene 与 project 必须给出同一结局。

锁住"预演不恢复土壤状态"那次修复（详见 de3dc70b3）。任一模式两次重复也必须一致。
  python scripts/v3_selftest_fidelity.py --state runs/v3/states/<sid> --action L2
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default='runs/v3/states/moon_rock_04_h1v0')
    ap.add_argument('--action', default='L2')
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    sd = ROOT / a.state
    st = v3_core.load_state(sd)
    spec = v3_core.truth_spec(st)
    rows = {}
    for mode in ('same_scene', 'project'):
        outs = []
        for _ in range(2):
            env = v3_core.make_env(spec, proto)
            r = v3_core.run_action(env, st['snapshot'], a.action, st['visible'],
                                   mode=mode, seed=0)
            outs.append({'outcome': r.get('outcome'),
                         'final_x': round(float(r.get('final_x') or 0), 3)})
            del env
        rows[mode] = outs
    same_mode = all(len({(o['outcome'], o['final_x']) for o in v}) == 1
                    for v in rows.values())
    cross = {(o['outcome'], o['final_x']) for v in rows.values() for o in v}
    res = {'schema': 'v3-fidelity-selftest/v1', 'state': a.state, 'action': a.action,
           'runs': rows, 'deterministic_within_mode': same_mode,
           'modes_agree': len(cross) == 1,
           'pass': bool(same_mode and len(cross) == 1)}
    out = ROOT / 'runs/v3/selftest_fidelity'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'pass': res['pass'], 'modes_agree': res['modes_agree'],
                      'deterministic': same_mode, 'runs': rows}, ensure_ascii=False))
    return 0 if res['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
