"""Stage007 作品整合：窄通道布局冻结 + 参考几何验证（BODY vs 轮式）。"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import terrain  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import v3_record  # noqa: E402
import stage6_rock as S6R  # noqa: E402
import stage4_config as S4C  # noqa: E402
import stage6_matrix as S6M  # noqa: E402

PITCH = 0.004
ORIGIN = np.array([0.0, -0.8, 0.0]); DIMS = np.array([700, 400, 90])
END_X = 2.6


def build(out):
    (out / 'scene').mkdir(parents=True, exist_ok=True)
    spec, mesh, scale = S6R.build(out / 'scene', 0.30)
    coll0 = pathlib.Path(spec['objects'][0]['posed_dir'])
    z = np.load(coll0.parent / 'rock_occ.npz') if (coll0.parent / 'rock_occ.npz').exists() else None
    # 用与 stage6 相同的方法重建岩石占据（4 mm）
    rock = mesh
    occ = np.zeros(tuple(DIMS), bool)
    vg = rock.voxelized(pitch=PITCH).fill()
    idx = np.floor((np.asarray(vg.points) - ORIGIN) / PITCH).astype(int)
    ok = ((idx >= 0) & (idx < DIMS)).all(axis=1); idx = idx[ok]
    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    walls = [{'y': -0.55, 'inner_y': -0.30, 'size': [0.50, 0.50, 0.32]},
             {'y': 0.55, 'inner_y': 0.30, 'size': [0.50, 0.50, 0.32]}]
    for w in walls:
        x0, y0, z0 = 1.0 - w['size'][0] / 2, w['y'] - w['size'][1] / 2, 0.0
        x1, y1, z1 = x0 + w['size'][0], y0 + w['size'][1], z0 + w['size'][2]
        i0 = max(0, int(x0 / PITCH)); i1 = min(DIMS[0], int(x1 / PITCH))
        j0 = max(0, int((y0 - ORIGIN[1]) / PITCH)); j1 = min(DIMS[1], int((y1 - ORIGIN[1]) / PITCH))
        k1 = min(DIMS[2], int(z1 / PITCH))
        occ[i0:i1, j0:j1, :k1] = True
    grid = out / 'layout_occ.npz'
    sha = hashlib.sha256(np.ascontiguousarray(occ).tobytes()).hexdigest()[:32]
    np.savez_compressed(grid, occupied=occ, origin=ORIGIN, pitch=np.float64(PITCH),
                        dims=DIMS, content_sha=np.array(sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    coll = out / 'coll'
    r = v3_core.build_collision(grid, coll, pitch=0.002, downsample=2)
    if not r.get('ok'):
        raise SystemExit(f'collision build failed: {r.get("error")}')
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=END_X,
                             name='stage7_narrow_passage',
                             objects=[{'posed_dir': str(coll)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    return spec, scale, {'rock': {'id': 'moon_rock_05', 'height_m': 0.30, 'x': 1.0, 'y': 0.0,
                                   'scale': round(scale, 5)},
                          'walls': walls, 'grid_sha': sha,
                          'coll_dir': str(coll.relative_to(ROOT))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage007/layout')
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / 'configs/stage6_protocol.json').read_text())
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    spec, scale, layout = build(out)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s'])); env.reset(seed=0)
    snap = env.save_state()
    core = {'spec': spec, 'snapshot': snap,
            'visible': {'x_front': 0.855, 'W_vis': 0.30, 'H_vis': 0.30},
            'state': {'state_id': 'stage7_narrow', 'state_hash': snap.get('state_hash')}}
    params = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
              'lower_at_x': 1.495, 'end_x': END_X, 'stop_tilt_deg': 12.0}
    plan = dict(params, plan_id=hashlib.sha256(
        json.dumps(params, sort_keys=True).encode()).hexdigest()[:16],
        far_edge_source='truth_far_edge_known')
    rows, app = v3_core.rehearse_on_spec(core, spec, snap, proto, options=cfg['actions'],
                                         body_plan=plan, budget=float(cfg['budget_s']),
                                         record_cells=True, record_root=out / 'record')
    for r in rows:
        ref = r.get('trajectory_ref')
        if ref:
            c = S6M.chassis_contacts_from_record(ref)
            r['chassis_contacts'] = c
            if c > 0 and r.get('success'):
                r['success'] = False; r['outcome'] = 'chassis_contact'
                r['reason'] = 'chassis_obstacle_contact'
    dec = v3_core.aggregate(rows, ['truth'], {}, 'majority', proto,
                            threshold_mode='majority', applic=app, options=cfg['actions'])
    v3_core.write_decision(out, core, 'TRUTH', rows, dec, {'body_plan': plan})
    ex = v3_core.truth_execute(core, dec['chosen'], proto, out / 'truth_exec', 'TRUTH',
                               body_plan=plan, budget=float(cfg['budget_s']))
    res = {'schema': 'stage7-layout/v1', 'layout': layout, 'end_x': END_X,
           'budget_s': cfg['budget_s'], 'plan': plan,
           'votes': dec['votes'], 'chosen': dec['chosen'],
           'rows': [{k: r.get(k) for k in ('action', 'success', 'outcome', 'reason',
                                           'cost', 't_end', 'chassis_contacts',
                                           'safe_pass', 'reached', 'plan_id')} for r in rows],
           'exec': {'action': dec['chosen'], 'outcome': ex.get('outcome'),
                    't_end': ex.get('t_end')}}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    (out / 'state.json').write_text(json.dumps({'spec': spec, 'snapshot': snap,
                                                'layout': layout, 'plan': plan},
                                               ensure_ascii=False))
    print(json.dumps({'chosen': dec['chosen'], 'votes': dec['votes'],
                      'rows': res['rows'], 'exec': res['exec']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
