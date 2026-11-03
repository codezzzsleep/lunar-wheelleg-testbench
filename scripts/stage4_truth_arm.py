"""Stage004：当前正式入口下的真值参考臂（同一状态/土壤/预算/冻结动作集）。"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import actions as ACT  # noqa: E402

import stage4_config as S4C  # noqa: E402
FROZEN = [a for a in S4C.traverse_actions() if a != 'CLIMB']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--perturb', default='')
    a = ap.parse_args()
    state_dir = (ROOT / a.state).resolve()
    out = (ROOT / a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((ROOT / a.protocol).read_text())
    core = v3_core.load_state(state_dir)
    if a.perturb:
        import stage4_perturb as S4P
        p = [float(x) for x in a.perturb.split(',')]
        snap, diag = S4P.env_perturb_snapshot(core, proto, *p[:3])
        core['snapshot'] = snap
        core['state']['state_hash'] = snap.get('state_hash')
        (out / 'perturb_diag.json').write_text(json.dumps(diag, ensure_ascii=False, indent=2))
    rows, app = v3_core.rehearse_on_spec(core, v3_core.truth_spec(core),
                                         core['snapshot'], proto,
                                         budget=float(S4C.budget()))
    applic = {x: (x in FROZEN, None if x in FROZEN else 'not_in_frozen_set')
              for x in ACT.OPTIONS if x != 'A0'}
    dec = v3_core.aggregate(rows, ['truth'], {}, 'majority', proto,
                            threshold_mode='majority', applic=applic)
    v3_core.write_decision(out, core, 'TRUTH', rows, dec, {'actions_frozen': FROZEN})
    ex = v3_core.truth_execute(core, dec['chosen'], proto, out / 'truth_exec', 'TRUTH')
    res = {'schema': 'stage4-truth-arm/v1', 'state_id': core['state']['state_id'],
           'frozen_actions': FROZEN, 'chosen': dec['chosen'], 'votes': dec['votes'],
           'costs': dec['mean_cost_s'], 'reason': dec['reason'],
           'threshold': dec['threshold'], 'exec': {
               'action': ex.get('action'), 'outcome': ex.get('outcome'),
               'reason': ex.get('reason'), 't_end': ex.get('t_end')},
           'snapshot_state_hash': core['snapshot'].get('state_hash')}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'chosen': res['chosen'], 'outcome': res['exec']['outcome'],
                      't_end': res['exec']['t_end'], 'votes': res['votes']},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
