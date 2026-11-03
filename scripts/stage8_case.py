"""Stage008：正式单案例：FULL/OBS 两臂预演、多数聚合、决策先落盘、独立真值执行。"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import terrain  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import stage6_matrix as S6M  # noqa: E402

END_X = 2.6
PITCH = 0.004


def build_scene_occ(occ, origin, pitch):
    """把融合占据放进覆盖整条走廊的场景栅格，再补上两侧墙（同一 2 mm 栅格）。"""
    origin = np.asarray(origin, float)
    so = np.array([0.60, -0.80, 0.0])
    dims = np.array([int(np.ceil((1.40 - so[0]) / pitch)),
                     int(np.ceil(1.60 / pitch)),
                     int(np.ceil(0.42 / pitch))], int)
    scene = np.zeros(tuple(dims), bool)
    idx = np.floor((origin - so) / pitch).astype(int)
    x0, y0, z0 = idx
    nx, ny, nz = occ.shape
    scene[x0:x0 + nx, y0:y0 + ny, z0:z0 + nz] |= occ
    for y, sx, sy, sz in ((-0.55, 0.5, 0.5, 0.32), (0.55, 0.5, 0.5, 0.32)):
        xa, xb = 1.0 - sx / 2, 1.0 + sx / 2
        ya, yb = y - sy / 2, y + sy / 2
        i0 = max(0, int((xa - so[0]) / pitch)); i1 = min(dims[0], int((xb - so[0]) / pitch))
        j0 = max(0, int((ya - so[1]) / pitch)); j1 = min(dims[1], int((yb - so[1]) / pitch))
        k1 = min(dims[2], int(sz / pitch))
        scene[i0:i1, j0:j1, :k1] = True
    return scene, so, dims


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fusion', required=True)
    ap.add_argument('--arm', choices=['full', 'obs'], required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--protocol', default='configs/stage6_protocol.json')
    ap.add_argument('--truth-fusion', default=None, help='真值执行用的完整几何（默认同 --fusion）')
    a = ap.parse_args()
    fus = (ROOT / a.fusion).resolve(); out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / a.protocol).read_text())
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    truth_fus = (ROOT / a.truth_fusion).resolve() if a.truth_fusion else fus
    src = fus / ('occ_full.npz' if a.arm == 'full' else 'occ_obs_only.npz')
    z = np.load(src)
    occ = np.asarray(z['occupied'], bool); origin = np.asarray(z['origin'], float)
    pitch = float(z['pitch']); dims = np.asarray(z['dims'], int)
    occ, scene_origin, scene_dims = build_scene_occ(occ, origin, pitch)
    grid = out / 'scene_occ.npz'
    sha = hashlib.sha256(np.ascontiguousarray(occ).tobytes()).hexdigest()[:32]
    np.savez_compressed(grid, occupied=occ, origin=scene_origin, pitch=np.float64(pitch),
                        dims=scene_dims, content_sha=np.array(sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    coll = out / 'coll'
    r = v3_core.build_collision(grid, coll, pitch=0.002, downsample=2)
    if not r.get('ok'):
        raise SystemExit(f'collision failed: {r.get("error")}')
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=END_X,
                             name=f'stage8_{a.arm}', objects=[{'posed_dir': str(coll)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s'])); env.reset(seed=0)
    snap = env.save_state()
    # 真值执行：完整几何（FULL_i）场景；OBS 臂的预演不能当自己的真值
    zt = np.load(truth_fus / 'occ_full.npz')
    tocc = np.asarray(zt['occupied'], bool); torigin = np.asarray(zt['origin'], float)
    tpitch = float(zt['pitch']); tdims = np.asarray(zt['dims'], int)
    tocc, to, td = build_scene_occ(tocc, torigin, tpitch)
    tgrid = out / 'truth_occ.npz'
    tsha = hashlib.sha256(np.ascontiguousarray(tocc).tobytes()).hexdigest()[:32]
    np.savez_compressed(tgrid, occupied=tocc, origin=to, pitch=np.float64(tpitch),
                        dims=td, content_sha=np.array(tsha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    tcoll = out / 'truth_coll'
    rt = v3_core.build_collision(tgrid, tcoll, pitch=0.002, downsample=2)
    if not rt.get('ok'):
        raise SystemExit('truth collision failed')
    tspec = terrain.make_spec(kind='flat', seed=0, goal_x=END_X,
                              name=f'stage8_truth_{a.arm}', objects=[{'posed_dir': str(tcoll)}])
    tspec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    tspec['soil'] = v7_soil.resolve('nominal')
    tenv = wheelleg_env.WheelLegEnv(tspec, max_seconds=float(cfg['budget_s'])); tenv.reset(seed=0)
    tsnap = tenv.save_state()
    params = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
              'lower_at_x': 1.495, 'end_x': END_X, 'stop_tilt_deg': 12.0}
    plan = dict(params, plan_id=hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16],
                far_edge_source='complete_geometry_reference')
    core = {'spec': spec, 'snapshot': snap,
            'visible': {'x_front': 0.83, 'W_vis': 0.28, 'H_vis': 0.30},
            'state': {'state_id': f'stage8_{a.arm}', 'state_hash': snap.get('state_hash')}}
    rows, app = v3_core.rehearse_on_spec(core, spec, snap, proto, options=cfg['actions'],
                                         body_plan=plan, budget=float(cfg['budget_s']),
                                         record_cells=True, record_root=out / 'record')
    for row in rows:
        ref = row.get('trajectory_ref')
        if ref:
            c = S6M.chassis_contacts_from_record(ref)
            row['chassis_contacts'] = c
            if c > 0 and row.get('success'):
                row['success'] = False; row['outcome'] = 'chassis_contact'
                row['reason'] = 'chassis_obstacle_contact'
    dec = v3_core.aggregate(rows, ['truth'], {}, 'majority', proto,
                            threshold_mode='majority', applic=app, options=cfg['actions'])
    v3_core.write_decision(out, core, 'TRUTH', rows, dec,
                           {'arm': a.arm, 'fusion': str(fus), 'plan': plan})
    tcore = {'spec': tspec, 'snapshot': tsnap,
             'visible': core['visible'],
             'state': {'state_id': f'stage8_truth_{a.arm}', 'state_hash': tsnap.get('state_hash')}}
    ex = v3_core.truth_execute(tcore, dec['chosen'], proto, out / 'truth_exec', 'TRUTH',
                               body_plan=plan, budget=float(cfg['budget_s']))
    res = {'schema': 'stage8-case/v1', 'fusion': str(fus.relative_to(ROOT)), 'arm': a.arm,
           'plan': plan, 'grid_sha': sha, 'votes': dec['votes'], 'chosen': dec['chosen'],
           'rows': [{k: row.get(k) for k in ('action', 'success', 'outcome', 'reason', 'cost',
                                             't_end', 'chassis_contacts', 'plan_id')} for row in rows],
           'exec': {'action': dec['chosen'], 'outcome': ex.get('outcome'), 't_end': ex.get('t_end'),
                    'chassis_contacts': ex.get('chassis_contacts'),
                    'safe_pass': ex.get('safe_pass'), 'reached': ex.get('reached')},
           'truth': {'fusion': str(truth_fus.relative_to(ROOT)), 'grid_sha': tsha}}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    (out / 'state.json').write_text(json.dumps({'spec': spec, 'snapshot': snap, 'plan': plan},
                                               ensure_ascii=False))
    print(json.dumps({'arm': a.arm, 'chosen': dec['chosen'], 'votes': dec['votes'],
                      'body': next((r for r in res['rows'] if r['action'] == 'BODY_CLEARANCE'), None),
                      'exec': res['exec']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
