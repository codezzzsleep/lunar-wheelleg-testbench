"""Stage004：用冻结动作集重新聚合既有矩阵，并对改变后的选择做真值执行。"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import stage4_perturb as S4P  # noqa: E402

FROZEN = ['R1', 'R2', 'D1', 'D2', 'L1', 'L2']


def read_matrix(p):
    return [json.loads(l) for l in pathlib.Path(p).read_text().splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--state', required=True)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--perturb', default='')
    ap.add_argument('--execute', action='store_true')
    a = ap.parse_args()
    out = (ROOT / a.dir).resolve()
    proto = json.loads((ROOT / a.protocol).read_text())
    rows_f = read_matrix(out / 'matrix_FULL.jsonl')
    rows_o = read_matrix(out / 'matrix_OBS.jsonl')
    cand_ids = sorted({r['candidate'] for r in rows_f})
    geom_sha = {}
    dec_old = json.loads((out / 'decision_FULL.json').read_text())
    geom_sha = dec_old.get('full_occ_sha') or {}
    import actions as ACT
    # 明确覆盖 ACT.OPTIONS 的每个动作：不在冻结集的动作一律标记为不适用，
    # 即使矩阵里根本没有它的行（否则会默认成 required，导致 valid 为空）
    applic = {a: (a in FROZEN, None if a in FROZEN else 'not_in_frozen_set')
              for a in ACT.OPTIONS if a != 'A0'}
    dec_f = v3_core.aggregate(rows_f, cand_ids, geom_sha, 'majority', proto,
                              threshold_mode='majority', applic=applic)
    dec_o = v3_core.aggregate(rows_o, ['OBS'], {}, 'majority', proto,
                              threshold_mode='majority', applic=applic)
    res = {'schema': 'stage4-reaggregate/v1', 'frozen_actions': FROZEN,
           'excluded': ['S1'], 'threshold_rule': 'majority',
           'FULL_old': dec_old['decision']['chosen'], 'FULL_new': dec_f['chosen'],
           'OBS_old': json.loads((out / 'decision_OBS.json').read_text())['decision']['chosen'],
           'OBS_new': dec_o['chosen'],
           'FULL_votes': dec_f['votes'], 'OBS_votes': dec_o['votes'],
           'FULL_costs': dec_f['mean_cost_s'], 'OBS_costs': dec_o['mean_cost_s'],
           'FULL_cost_reason': dec_f['reason'], 'OBS_cost_reason': dec_o['reason']}
    if a.execute:
        core = v3_core.load_state((ROOT / a.state).resolve())
        dx = dy = dyaw = 0.0
        if a.perturb:
            parts = [float(x) for x in a.perturb.split(',')]
            while len(parts) < 3:
                parts.append(0.0)
            dx, dy, dyaw = parts[:3]
        if dx or dy or dyaw:
            snap, diag = S4P.env_perturb_snapshot(core, proto, dx, dy, dyaw)
            core['snapshot'] = snap
            core['state']['state_hash'] = snap.get('state_hash')
            res['perturb_diag'] = diag
        ex = {}
        for arm, act in (('FULL', dec_f['chosen']), ('OBS', dec_o['chosen'])):
            ex[arm] = v3_core.truth_execute(core, act, proto, out / 'truth_exec_reagg', arm)
        res['exec'] = {k: {'action': v.get('action'), 'outcome': v.get('outcome'),
                           'reason': v.get('reason'), 't_end': v.get('t_end')}
                       for k, v in ex.items()}
    (out / 'reaggregate_frozen.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({k: res[k] for k in ('FULL_old', 'FULL_new', 'OBS_old', 'OBS_new',
                                          'FULL_votes', 'OBS_votes')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
