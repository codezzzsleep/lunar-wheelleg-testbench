"""G1 v2（U 一致场景）：完美补全 vs 仅观测，同一完整真值场景执行。"""
import argparse, hashlib, json, pathlib, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core, wheelleg_env, stage8_matrix2 as M, stage6_matrix as S6M
from stage10_scenes_v2 import SCEN


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage010/g1v2_run')
    ap.add_argument('--only', default=None)
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / 'configs/stage6_protocol.json').read_text())
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    tm = json.loads((truth / 'truth_manifest.json').read_text())
    snap = json.loads((truth / 'state_snapshot.json').read_text())
    s0 = tm['s0_state_hash']; actions = cfg['actions']
    ts = json.loads((truth / 'scene_spec.json').read_text())
    ref_env = wheelleg_env.WheelLegEnv(ts, max_seconds=120.0); ref_env.reset(seed=0)
    ref_env.restore_state(snap, mode='same_scene')
    s0_ref = (np.asarray(ref_env.data.qpos, float).copy(), np.asarray(ref_env.data.qvel, float).copy())
    zv = np.load(truth / 'fusion/V.npz')
    V = zv['shell']; o = np.asarray(zv['origin'], float); p = float(zv['pitch'])
    U = (zv['space'] == 0)
    xs = o[0] + (np.arange(int(zv['dims'][0])) + 0.5) * p
    res = {'schema': 'g1v2-screening/v1', 'denominator': len(SCEN), 'scenarios': {}}
    for name in SCEN:
        if a.only and name != a.only:
            continue
        d = out / name; d.mkdir(parents=True, exist_ok=True)
        z2 = np.load(ROOT / 'runs/v3/stage010/g1v2' / f'occ2_{name}.npz')
        P = z2['P']
        full = V | (P & U); obs = V
        added = full & ~V; ax = added.any(axis=(1, 2))
        far = float(xs[ax].max()) if ax.any() else float(xs[V.any(axis=(1, 2))].max())
        full_plan = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
                     'lower_at_x': round(far + 0.10, 4), 'end_x': 2.6, 'stop_tilt_deg': 12.0,
                     'far_edge_source': 'hidden_part_of_this_scenario'}
        full_plan['plan_id'] = hashlib.sha256(json.dumps(full_plan, sort_keys=True).encode()).hexdigest()[:16]
        obs_plan = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15, 'lower_at_x': 2.45,
                    'end_x': 2.6, 'stop_tilt_deg': 12.0, 'far_edge_source': 'unknown_hold'}
        obs_plan['plan_id'] = hashlib.sha256(json.dumps(obs_plan, sort_keys=True).encode()).hexdigest()[:16]
        arms = {}
        for arm, occ, plan, tag in (('full', full, full_plan, 'completion'), ('obs', obs, obs_plan, 'obs_only')):
            occ4 = M.resample_walls(occ, o, p)
            (d / arm).mkdir(parents=True, exist_ok=True)
            spec, env, sha = M.make_scene(occ4, d / arm, f'{name}_{arm}')
            M.restore_common(env, snap, s0, mode='project', ref=s0_ref)
            core = {'spec': spec, 'snapshot': snap,
                    'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
                    'state': {'state_id': f'g1v2_{name}_{arm}', 'state_hash': s0}}
            rows, app = v3_core.rehearse_on_spec(core, spec, snap, proto, mode='project',
                                                 options=actions, body_plan=plan,
                                                 budget=float(cfg['budget_s']),
                                                 record_cells=True, record_root=d / arm / 'record')
            for r in rows:
                tref = r.get('trajectory_ref')
                if tref:
                    c = S6M.chassis_contacts_from_record(tref)
                    r['chassis_contacts'] = c
                    if c > 0 and r.get('success'):
                        r['success'] = False; r['outcome'] = 'chassis_contact'; r['reason'] = 'chassis_obstacle_contact'
                r['candidate'] = tag
            dec = v3_core.aggregate(rows, [tag], {}, 'majority', proto, threshold_mode='majority',
                                    applic=app, options=actions)
            v3_core.write_decision(d / arm, core, arm.upper(), rows, dec, {'plan': plan})
            arms[arm] = {'geometry_sha': sha, 'plan': plan, 'chosen': dec['chosen'], 'votes': dec['votes'],
                         'rows': [{k: r.get(k) for k in ('action','success','outcome','reason','cost','chassis_contacts')} for r in rows]}
        truth4 = M.resample_walls(P, o, p)
        (d / 'truth').mkdir(parents=True, exist_ok=True)
        tspec, tenv, tsha = M.make_scene(truth4, d / 'truth', f'{name}_truth')
        M.restore_common(tenv, snap, s0, mode='project', ref=s0_ref)
        tcore = {'spec': tspec, 'snapshot': snap,
                 'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
                 'state': {'state_id': f'g1v2_truth_{name}', 'state_hash': s0}}
        for arm in ('full', 'obs'):
            ex = v3_core.truth_execute(tcore, arms[arm]['chosen'], proto, d / 'exec', arm.upper(),
                                       mode='project', body_plan=arms[arm]['plan'],
                                       budget=float(cfg['budget_s']))
            arms[arm]['exec'] = {k: ex.get(k) for k in
                                 ('action','outcome','t_end','chassis_contacts','safe_pass','reached','plan_id')}
        res['scenarios'][name] = {'hidden_rear_x': round(far, 4), 'truth_sha': tsha, 'arms': arms}
        (out / 'g1v2_partial.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print(json.dumps({'scenario': name, 'full': arms['full']['exec'], 'obs': arms['obs']['exec']}, ensure_ascii=False), flush=True)
    (out / 'g1v2_result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
