"""复核 len_short/len_mid 的 D2：与 BODY 同一安全标准，字段从记录计算。"""
import json, pathlib, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import stage6_matrix as S6M

RUN = ROOT / 'runs/v3/stage010/g1v2_run'
SCEN = ['len_short', 'len_mid', 'ref', 'len_long']
END_X = 2.6; TOL = 0.05; BUDGET = 120.0; TIP_DEG = 30.0


def quat_tilt_deg(q):
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    r20 = 2 * (x * z - w * y); r21 = 2 * (y * z + w * x); r22 = 1 - 2 * (x * x + y * y)
    up = np.clip(r22, -1.0, 1.0)
    return np.degrees(np.arccos(up))


def metrics(rec_dir):
    rec_dir = pathlib.Path(rec_dir)
    chunks = sorted(rec_dir.glob('chunk_*.npz'))
    if not chunks:
        return None
    q = np.concatenate([np.load(c)['qpos'] for c in chunks])
    t = np.concatenate([np.load(c)['t'] for c in chunks])
    chassis = S6M.chassis_contacts_from_record({'trajectory_path': str(rec_dir / 'index.json')})
    info = json.loads((rec_dir / 'index.json').read_text())
    return {'frames': len(q), 't_end': round(float(t[-1]), 3),
            'final_x': round(float(q[-1, 0]), 4),
            'final_y': round(float(q[-1, 1]), 4),
            'max_abs_y': round(float(np.abs(q[:, 1]).max()), 4),
            'max_tilt_deg': round(float(quat_tilt_deg(q[:, 3:7]).max()), 3),
            'chassis_contacts': int(chassis),
            'reached': bool(abs(float(q[-1, 0]) - END_X) <= TOL),
            'within_budget': bool(float(t[-1]) <= BUDGET + 1e-6),
            'contacts_n': int(info.get('contacts_n', 0))}


def verdict(m, channel_half=0.55):
    if m is None:
        return {'safe': False, 'reason': 'no_record'}
    checks = {'reached': m['reached'], 'no_chassis_contact': m['chassis_contacts'] == 0,
              'tilt_ok': m['max_tilt_deg'] <= TIP_DEG,
              'lateral_ok': m['max_abs_y'] <= channel_half, 'budget_ok': m['within_budget']}
    return {'safe': bool(all(checks.values())), 'checks': checks}


def main():
    out = ROOT / 'runs/v3/stage010/d2_verification.json'
    rep = {'schema': 'g1v2-d2-verification/v1',
           'standard': {'end_x': END_X, 'tolerance_m': TOL, 'budget_s': BUDGET,
                        'tip_deg': TIP_DEG, 'channel_half_m': 0.55,
                        'chassis_contacts_must_be': 0,
                        'note': 'same standard as BODY; fields computed from recorded qpos/contacts'},
           'scenarios': {}}
    for s in SCEN:
        d = RUN / s
        ej = {a: json.loads((d / 'exec' / f'execution_{a.upper()}.json').read_text())
              for a in ('full', 'obs') if (d / 'exec' / f'execution_{a.upper()}.json').exists()}
        row = {}
        for arm, action in (('full', None), ('obs', 'BODY_CLEARANCE')):
            rec = d / 'exec' / 'record' / arm.upper()
            m = metrics(rec)
            v = verdict(m)
            ex = ej.get(arm, {})
            row[arm] = {'action': ex.get('action'), 'outcome': ex.get('outcome'),
                        'metrics': m, 'verdict': v,
                        'exec_reported': {k: ex.get(k) for k in
                                          ('t_end', 'final_x', 'safe_pass', 'reached', 'chassis_contacts')}}
        # 仅当 D2 是 FULL 选择时比较
        if row['full']['action'] == 'D2':
            row['comparison'] = {'D2_safe_same_standard': row['full']['verdict']['safe'],
                                 'BODY_safe_same_standard': row['obs']['verdict']['safe'],
                                 'cost_D2_s': row['full']['metrics']['t_end'] if row['full']['metrics'] else None,
                                 'cost_BODY_s': row['obs']['metrics']['t_end'] if row['obs']['metrics'] else None}
        rep['scenarios'][s] = row
        print(json.dumps({s: {'full_action': row['full']['action'],
                              'full_safe': row['full']['verdict']['safe'],
                              'full_metrics': row['full']['metrics'],
                              'obs_action': row['obs']['action'],
                              'obs_safe': row['obs']['verdict']['safe'],
                              'obs_metrics': row['obs']['metrics'],
                              'cmp': row.get('comparison')}}, ensure_ascii=False))
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
