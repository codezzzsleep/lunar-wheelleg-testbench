"""G1：固定 V/U/S0/动作库/保守规则，比较完美补全 V∪(truth∩U) 与仅观测 V。"""
import argparse, hashlib, json, pathlib, sys
import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core, v3_fuse, wheelleg_env, stage8_matrix2 as M, stage6_matrix as S6M

SCEN = {
    'ref_full':  ('original', None),
    'rear_short':('compress', 0.25),
    'rear_mid':  ('compress', 0.60),
    'rear_low':  ('low', 0.55),
    'rear_high': ('high', 0.02),
    'rear_long': ('stretch', 1.5),
}
XSPLIT = 0.95


def variant_mesh(base, kind, param):
    m = base.copy(); v = np.asarray(m.vertices).copy()
    if kind is None:
        return m
    sel = v[:, 0] > XSPLIT
    if kind == 'compress':
        v[sel, 0] = XSPLIT + (v[sel, 0] - XSPLIT) * float(param)
    elif kind == 'stretch':
        v[sel, 0] = XSPLIT + (v[sel, 0] - XSPLIT) * float(param)
    elif kind == 'low':
        v[sel, 2] = v[sel, 2] * float(param)
    elif kind == 'high':
        v[sel, 2] = np.minimum(v[sel, 2] + float(param), 0.30)
    m.vertices = v
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage010/g1')
    ap.add_argument('--only', default=None)
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / 'configs/stage6_protocol.json').read_text())
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    tm = json.loads((truth / 'truth_manifest.json').read_text())
    snap = json.loads((truth / 'state_snapshot.json').read_text())
    s0 = tm['s0_state_hash']
    zv = np.load(truth / 'fusion/V.npz')
    V = zv['shell']; space = zv['space']; vo = np.asarray(zv['origin'], float); vp = float(zv['pitch'])
    vdims = tuple(int(x) for x in zv['dims'])
    grid = {'origin': vo, 'pitch': vp, 'dims': np.array(vdims)}
    grid['xs'] = vo[0] + (np.arange(vdims[0]) + 0.5) * vp
    grid['ys'] = vo[1] + (np.arange(vdims[1]) + 0.5) * vp
    grid['zs'] = vo[2] + (np.arange(vdims[2]) + 0.5) * vp
    base = trimesh.load(str(truth / 'truth/body_world.stl'), force='mesh', process=False)
    ts = json.loads((truth / 'scene_spec.json').read_text())
    actions = cfg['actions']
    tenv0 = wheelleg_env.WheelLegEnv(ts, max_seconds=float(cfg['budget_s'])); tenv0.reset(seed=0)
    tenv0.restore_state(snap, mode='same_scene')
    s0_ref = (np.asarray(tenv0.data.qpos, float).copy(), np.asarray(tenv0.data.qvel, float).copy())
    res = {'schema': 'g1-screening/v1', 'x_split': XSPLIT, 'denominator': len(SCEN), 'scenarios': {}}
    for name, (kind, param) in SCEN.items():
        if a.only and name != a.only:
            continue
        d = out / name; d.mkdir(parents=True, exist_ok=True)
        vm = variant_mesh(base, kind, param)
        P, pinfo = v3_fuse.voxelize_columns(vm, grid)
        U = (space == 0)
        full = V | (P & U)
        obs = V
        # hidden rear from the candidate's own hidden part (not truth constants)
        xs = grid['xs']; added = full & ~V
        ax = added.any(axis=(1, 2))
        far = float(xs[ax].max()) if ax.any() else float(xs[V.any(axis=(1, 2))].max())
        full_plan = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
                     'lower_at_x': round(far + 0.10, 4), 'end_x': 2.6, 'stop_tilt_deg': 12.0,
                     'far_edge_source': 'hidden_part_of_this_scenario'}
        full_plan['plan_id'] = hashlib.sha256(json.dumps(full_plan, sort_keys=True).encode()).hexdigest()[:16]
        obs_plan = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
                    'lower_at_x': 2.45, 'end_x': 2.6, 'stop_tilt_deg': 12.0,
                    'far_edge_source': 'unknown_hold'}
        obs_plan['plan_id'] = hashlib.sha256(json.dumps(obs_plan, sort_keys=True).encode()).hexdigest()[:16]
        arms = {}
        for arm, occ, plan, tag in (('full', full, full_plan, 'completion'), ('obs', obs, obs_plan, 'obs_only')):
            scene_occ = M.resample_walls(occ, vo, vp)
            (d / arm).mkdir(parents=True, exist_ok=True)
            spec, env, sha = M.make_scene(scene_occ, d / arm, f'{name}_{arm}')
            M.restore_common(env, snap, s0, ref=None)
            core = {'spec': spec, 'snapshot': snap,
                    'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
                    'state': {'state_id': f'g1_{name}_{arm}', 'state_hash': s0}}
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
            arms[arm] = {'geometry_sha': sha, 'plan': plan, 'chosen': dec['chosen'],
                         'votes': dec['votes'], 'rows': [{k: r.get(k) for k in
                             ('action','success','outcome','reason','cost','chassis_contacts')} for r in rows]}
        # 两臂决策都在同一完整真值场景执行
        truth_occ = M.resample_walls(P, vo, vp)
        (d / 'truth').mkdir(parents=True, exist_ok=True)
        tspec, tenv, tsha = M.make_scene(truth_occ, d / 'truth', f'{name}_truth')
        M.restore_common(tenv, snap, s0, mode='project', ref=s0_ref)
        tcore = {'spec': tspec, 'snapshot': snap,
                 'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
                 'state': {'state_id': f'g1_truth_{name}', 'state_hash': s0}}
        for arm in ('full', 'obs'):
            ex = v3_core.truth_execute(tcore, arms[arm]['chosen'], proto, d / 'exec', arm.upper(),
                                       mode='project', body_plan=arms[arm]['plan'],
                                       budget=float(cfg['budget_s']))
            arms[arm]['exec'] = {k: ex.get(k) for k in
                                 ('action','outcome','t_end','chassis_contacts','safe_pass','reached','plan_id')}
        res['scenarios'][name] = {'kind': kind, 'param': param, 'truth_sha': tsha,
                                  'hidden_rear_x': round(far, 4), 'arms': arms}
        (out / 'g1_partial.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print(json.dumps({'scenario': name, 'full': arms['full']['exec'], 'obs': arms['obs']['exec']},
                         ensure_ascii=False))
    (out / 'g1_result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
