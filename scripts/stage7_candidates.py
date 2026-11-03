"""Stage007：6 个 Lux3D 候选 -> FULL/OBS 几何 -> 预演筛选（BODY + 轮式）。"""
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
import stage6_matrix as S6M  # noqa: E402

PITCH = 0.004
ORIGIN = np.array([0.0, -0.8, 0.0]); DIMS = np.array([700, 400, 90])
ROCK_X, ROCK_Y, TARGET_H = 1.0, 0.0, 0.30
END_X = 2.6
WALLS = [(-0.55, 0.5, 0.5, 0.32), (0.55, 0.5, 0.5, 0.32)]
ACTIONS = ['R2', 'D1', 'BODY_CLEARANCE']


def mesh_from_glb(p):
    s = trimesh.load(str(p), force='scene')
    geoms = [g for g in s.geometry.values() if len(g.faces)]
    m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0].copy()
    return m


def orient(m):
    m = m.copy()
    v = np.asarray(m.vertices); ext = v.max(0) - v.min(0)
    # 最窄水平轴朝 y（轮间可容纳的方向），与参考岩石一致
    if ext[0] < ext[1]:
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
    v = np.asarray(m.vertices); z0 = v[:, 2].min()
    m.apply_translation([0, 0, -z0])
    v = np.asarray(m.vertices); h = v[:, 2].max()
    m.apply_scale(TARGET_H / h)
    v = np.asarray(m.vertices); cx = (v[:, 0].min() + v[:, 0].max()) / 2
    cy = (v[:, 1].min() + v[:, 1].max()) / 2
    m.apply_translation([ROCK_X - cx, ROCK_Y - cy, 0])
    return m


def vox(m, pitch=PITCH, origin=ORIGIN, dims=DIMS):
    occ = np.zeros(tuple(dims), bool)
    vg = m.voxelized(pitch=pitch).fill()
    idx = np.floor((np.asarray(vg.points) - origin) / pitch).astype(int)
    ok = ((idx >= 0) & (idx < dims)).all(axis=1); idx = idx[ok]
    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return occ


def add_walls(occ):
    for y, sx, sy, sz in WALLS:
        x0, x1 = ROCK_X - sx / 2, ROCK_X + sx / 2
        y0, y1 = y - sy / 2, y + sy / 2
        i0 = max(0, int(x0 / PITCH)); i1 = min(DIMS[0], int(x1 / PITCH))
        j0 = max(0, int((y0 - ORIGIN[1]) / PITCH)); j1 = min(DIMS[1], int((y1 - ORIGIN[1]) / PITCH))
        k1 = min(DIMS[2], int(sz / PITCH))
        occ[i0:i1, j0:j1, :k1] = True
    return occ


def face_far(occ):
    xs = ORIGIN[0] + (np.arange(DIMS[0]) + 0.5) * PITCH
    anyx = occ.any(axis=(1, 2))
    idx = np.where(anyx)[0]
    return float(xs[idx[0]]), float(xs[idx[-1]])


def build_arm(out, mesh, arm):
    occ = vox(mesh, dims=DIMS, origin=ORIGIN, pitch=PITCH)
    face, far = face_far(occ)
    if arm == 'obs':
        xs = ORIGIN[0] + (np.arange(DIMS[0]) + 0.5) * PITCH
        occ &= (xs[:, None, None] <= face + 0.10)
    add_walls(occ)
    grid = out / f'{arm}_occ.npz'
    sha = hashlib.sha256(np.ascontiguousarray(occ).tobytes()).hexdigest()[:32]
    np.savez_compressed(grid, occupied=occ, origin=ORIGIN, pitch=np.float64(PITCH),
                        dims=DIMS, content_sha=np.array(sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    coll = out / f'{arm}_coll'
    r = v3_core.build_collision(grid, coll, pitch=0.002, downsample=2)
    if not r.get('ok'):
        raise SystemExit(f'collision failed {arm}: {r.get("error")}')
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=END_X,
                             name=f'stage7_{arm}', objects=[{'posed_dir': str(coll)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    return spec, coll, {'face_x': round(face, 4), 'far_x': round(far, 4),
                        'obs_truncated_x': round(face + 0.10, 4) if arm == 'obs' else None,
                        'grid_sha': sha}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage007/candidates')
    ap.add_argument('--only', type=int, default=None)
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / 'configs/stage6_protocol.json').read_text())
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    tasks = sorted((ROOT / 'runs/v3/stage007/lux3d/generation').glob('task_*.json'))
    results = []
    for ti, tf in enumerate(tasks):
        if a.only is not None and ti != a.only:
            continue
        td = json.loads(tf.read_text())
        glbs = sorted((tf.parent / f"task_{td['task_id']}").rglob('*.glb'),
                      key=lambda x: x.stat().st_size, reverse=True)
        if not glbs:
            print(json.dumps({'skip': td['task_id'], 'reason': 'no glb'})); continue
        glb = glbs[0]
        mesh = orient(mesh_from_glb(glb))
        rec = {'schema': 'stage7-candidate/v1', 'task_id': td['task_id'],
               'glb_sha256': td.get('glb_sha'), 'arms': {}}
        for arm in ('full', 'obs'):
            armdir = out / f"task_{td['task_id']}" / arm
            armdir.mkdir(parents=True, exist_ok=True)
            spec, coll, geo = build_arm(armdir, mesh, arm)
            env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s'])); env.reset(seed=0)
            snap = env.save_state()
            core = {'spec': spec, 'snapshot': snap,
                    'visible': {'x_front': geo['face_x'], 'W_vis': 0.30, 'H_vis': TARGET_H},
                    'state': {'state_id': f"lux_{td['task_id']}_{arm}",
                              'state_hash': snap.get('state_hash')}}
            params = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
                      'lower_at_x': (geo['far_x'] + 0.35) if arm == 'full' else END_X - 0.15,
                      'end_x': END_X, 'stop_tilt_deg': 12.0}
            plan = dict(params, plan_id=hashlib.sha256(
                json.dumps(params, sort_keys=True).encode()).hexdigest()[:16],
                far_edge_source='complete_geometry' if arm == 'full' else 'unknown_hold')
            rows, app = v3_core.rehearse_on_spec(core, spec, snap, proto, options=ACTIONS,
                                                 body_plan=plan, budget=float(cfg['budget_s']),
                                                 record_cells=True, record_root=armdir / 'record')
            for r in rows:
                ref = r.get('trajectory_ref')
                if ref:
                    c = S6M.chassis_contacts_from_record(ref)
                    r['chassis_contacts'] = c
                    if c > 0 and r.get('success'):
                        r['success'] = False; r['outcome'] = 'chassis_contact'
                        r['reason'] = 'chassis_obstacle_contact'
            dec = v3_core.aggregate(rows, ['truth'], {}, 'majority', proto,
                                    threshold_mode='majority', applic=app, options=ACTIONS)
            rec['arms'][arm] = {'geometry': geo, 'plan': plan,
                                'rows': [{k: r.get(k) for k in ('action', 'success', 'outcome',
                                                               'reason', 'cost', 't_end',
                                                               'chassis_contacts', 'plan_id')}
                                         for r in rows],
                                'chosen': dec['chosen'], 'votes': dec['votes']}
        results.append(rec)
        (out / 'screen.json').write_text(json.dumps({'schema': 'stage7-screen/v1',
                                                     'partial': True,
                                                     'candidates': results},
                                                    ensure_ascii=False, indent=2))
    (out / 'screen.json').write_text(json.dumps({'schema': 'stage7-screen/v1',
                                                 'candidates': results}, ensure_ascii=False, indent=2))
    print(json.dumps([{'task': r['task_id'],
                       'full': {k: r['arms']['full'][k] for k in ('chosen', 'votes')},
                       'obs': {k: r['arms']['obs'][k] for k in ('chosen', 'votes')},
                       'body_full': next((x for x in r['arms']['full']['rows']
                                          if x['action'] == 'BODY_CLEARANCE'), None),
                       'body_obs': next((x for x in r['arms']['obs']['rows']
                                         if x['action'] == 'BODY_CLEARANCE'), None)}
                      for r in results], ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
