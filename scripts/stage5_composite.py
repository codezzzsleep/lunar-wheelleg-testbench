"""Stage005：组合岩石场景构建 + 落轮承载面检查 + 真值验证。"""
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
import stage4_config as S4C  # noqa: E402
import stage4_geometry as S4G  # noqa: E402

PITCH = 0.004
ORIGIN = np.array([0.60, -0.50, 0.0])
DIMS = np.array([500, 250, 50])
TARGET_H = 0.12


def load_rock(rid, level='h1'):
    d = ROOT / 'assets' / 'v3' / 'rocks' / rid / level
    mesh = trimesh.load(str(d / 'body.stl'), force='mesh')
    man = json.loads((ROOT / 'assets/v3/rocks' / rid / 'rock.json').read_text())
    return mesh, man


def prep(mesh, target_h, face_target, y_center, auto_yaw=True):
    m0 = mesh.copy()
    z0 = float(m0.bounds[0][2]); z1 = float(m0.bounds[1][2])
    scale = target_h / (z1 - z0)
    m0.apply_scale(scale)
    m0.apply_translation([0, 0, -float(m0.bounds[0][2])])
    best = None
    for yaw in ((0.0, 90.0) if auto_yaw else (0.0,)):
        m = m0.copy()
        if yaw:
            m.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(yaw), [0, 0, 1]))
        v = np.asarray(m.vertices)
        ext = float(v[:, 0].max() - v[:, 0].min())
        if best is None or ext > best[0]:
            best = (ext, m)
    m = best[1]
    v = np.asarray(m.vertices)
    cx = 0.5 * (float(v[:, 1].min()) + float(v[:, 1].max()))
    m.apply_translation([-cx, 0, 0])
    m.apply_translation([0, y_center, 0])
    v = np.asarray(m.vertices)
    m.apply_translation([face_target - float(v[:, 0].min()), 0, 0])
    return m, scale


def voxelize(meshes, pitch=PITCH, origin=ORIGIN, dims=DIMS):
    occ = np.zeros(tuple(dims), dtype=bool)
    for m in meshes:
        vg = m.voxelized(pitch=pitch).fill()
        pts = np.asarray(vg.points, dtype=float)
        idx = np.floor((pts - origin) / pitch).astype(int)
        ok = ((idx[:, 0] >= 0) & (idx[:, 0] < dims[0])
              & (idx[:, 1] >= 0) & (idx[:, 1] < dims[1])
              & (idx[:, 2] >= 0) & (idx[:, 2] < dims[2]))
        idx = idx[ok]
        occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return occ


def surface(occ, origin=ORIGIN, pitch=PITCH):
    zs = origin[2] + (np.arange(occ.shape[2]) + 0.5) * pitch
    xs = origin[0] + (np.arange(occ.shape[0]) + 0.5) * pitch
    ys = origin[1] + (np.arange(occ.shape[1]) + 0.5) * pitch
    h = np.zeros((occ.shape[0], occ.shape[1]))
    has = occ.any(axis=2)
    for i in range(occ.shape[0]):
        for j in range(occ.shape[1]):
            if has[i, j]:
                h[i, j] = zs[np.where(occ[i, j])[0].max()] + pitch / 2
    return xs, ys, h


def bearing_metrics(xs, ys, h, landing_x, cfg):
    out = {'landing_x': landing_x, 'wheel_lines': {}, 'front_slope': {}, 'rear_drop': {}}
    top_all = float(h.max())
    # 承载带：x in [landing-0.04, landing+0.04]，y 覆盖
    i0 = np.searchsorted(xs, landing_x - 0.04); i1 = np.searchsorted(xs, landing_x + 0.04)
    band = h[i0:i1]
    cov = (band >= top_all - 0.02).any(axis=0)
    yy = ys[cov]
    gap = 0.0
    if len(yy):
        dy = np.diff(yy)
        gap = float(max(0.0, dy.max() - PITCH)) if len(dy) else 0.0
    out['coverage_y'] = [round(float(yy.min()), 3), round(float(yy.max()), 3)] if len(yy) else None
    out['max_gap_m'] = round(gap, 4)
    out['effective_area_frac'] = round(float(cov.mean()), 4)
    for name, yc in (('FR', -0.19), ('FL', 0.19)):
        j = int(np.argmin(np.abs(ys - yc)))
        i = int(np.argmin(np.abs(xs - landing_x)))
        z = float(h[i, j])
        dx = float(h[min(i + 3, len(xs) - 1), j] - h[max(i - 3, 0), j]) / 0.024
        dy_ = float(h[i, min(j + 3, len(ys) - 1)] - h[i, max(j - 3, 0)]) / 0.024
        patch = h[max(0, i - 6):i + 7, max(0, j - 6):j + 7]
        area = float((np.abs(patch - z) <= 0.01).mean()) if patch.size else 0.0
        out['wheel_lines'][name] = {'y': round(float(ys[j]), 3), 'z': round(z, 4),
                                    'slope_x': round(dx, 3), 'slope_y': round(dy_, 3),
                                    'flat_area_frac': round(area, 3)}
        # 前坡：landing 前 10 cm 的高度差；后坡：landing 后 10 cm 的高度差
        ia = int(np.argmin(np.abs(xs - (landing_x - 0.10))))
        ib = int(np.argmin(np.abs(xs - (landing_x + 0.10))))
        out['front_slope'][name] = round(float(z - h[ia, j]), 4)
        out['rear_drop'][name] = round(float(z - h[ib, j]), 4)
    # 列贯通性：每块轮位所在的 y 列，从 face 到 far 是否连续有支撑
    out['passable_columns'] = {}
    for name, yc in (('FR', -0.19), ('FL', 0.19)):
        j = int(np.argmin(np.abs(ys - yc)))
        col = h[:, j]
        wet = np.where(col >= 0.02)[0]
        out['passable_columns'][name] = (bool(len(wet)), 
                                         round(float(xs[wet[0]]), 3) if len(wet) else None,
                                         round(float(xs[wet[-1]]), 3) if len(wet) else None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--rocks', default='moon_rock_02,moon_rock_05,moon_rock_07')
    ap.add_argument('--spacing', type=float, default=0.09)
    ap.add_argument('--height', type=float, default=TARGET_H)
    ap.add_argument('--run-truth', action='store_true')
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = S4C.load(); climb = cfg['climb']
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    rocks = [x.strip() for x in a.rocks.split(',') if x.strip()]
    loaded = [load_rock(r) for r in rocks]
    n = len(loaded); spacing = float(a.spacing)
    meshes, scales = [], []
    for i, (m, man) in enumerate(loaded):
        yc = (i - (n - 1) / 2.0) * spacing
        mm, sc = prep(m, a.height, 1.00, yc)
        meshes.append(mm); scales.append(sc)
    occ = voxelize(meshes)
    grid = out / 'composite_occ.npz'
    sha = hashlib.sha256(np.ascontiguousarray(occ).tobytes()).hexdigest()[:32]
    np.savez_compressed(grid, occupied=occ, origin=ORIGIN, pitch=np.float64(PITCH),
                        dims=DIMS, content_sha=np.array(sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    coll = out / 'coll'
    r = v3_core.build_collision(grid, coll, pitch=0.002, downsample=2)
    if not r.get('ok'):
        raise SystemExit(f'collision build failed: {r.get("error")}')
    xs, ys, h = surface(occ)
    top = float(h.max())
    face = float(xs[np.where((h >= 0.02).any(axis=1))[0][0]])
    far = float(xs[np.where((h >= 0.02).any(axis=1))[0][-1]])
    landing = face + 0.07
    bear = bearing_metrics(xs, ys, h, landing, climb)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=far + 0.6,
                             name='stage5_composite', objects=[{'posed_dir': str(coll)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    scene = {'schema': 'stage5-composite/v1', 'rocks': [
        {'id': rid, 'level': 'h1', 'license': man['license'],
         'source_url': man['source_url'], 'scale': round(sc, 5),
         'y_center': round((i - (n - 1) / 2.0) * spacing, 4),
         'target_face_x': 1.00}
        for i, (rid, (m, man), sc) in enumerate(zip(rocks, loaded, scales))],
        'grid': {'origin': ORIGIN.tolist(), 'pitch': PITCH, 'dims': DIMS.tolist(),
                 'content_sha': sha},
        'collision': {'representation': 'box_union (4 mm boxes from 4 mm occupancy)',
                      'coll_dir': str(coll.relative_to(ROOT)), 'n_boxes': r.get('n_boxes')},
        'top_z': round(top, 4), 'face_x': round(face, 4), 'far_x': round(far, 4),
        'landing_x': round(landing, 4), 'bearing': bear}
    (out / 'scene.json').write_text(json.dumps(scene, ensure_ascii=False, indent=2))
    res = {'schema': 'stage5-composite-check/v1', 'scene': scene}
    if a.run_truth:
        env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s']))
        env.reset(seed=0)
        snap = env.save_state()
        gp = S4G.derive_skill_params({'face_FR': face, 'face_FL': face,
                                      'top_z': top, 'far_x': far, 'landing': None,
                                      'source': 'truth_composite'})
        plan = {'action': 'CLIMB', 'params': gp['params'], 'applicable': True,
                'plan_id': hashlib.sha256(json.dumps(gp['params'], sort_keys=True).encode()).hexdigest()[:16]}
        core = {'spec': spec, 'snapshot': snap,
                'visible': {'x_front': face, 'W_vis': 0.45, 'H_vis': top},
                'state': {'state_id': 'stage5_composite', 'state_hash': snap.get('state_hash')}}
        r_climb = v3_core.run_climb_cell(spec, snap, plan, proto, mode='same_scene',
                                         record_dir=out / 'record_climb',
                                         budget=float(cfg['budget_s']))
        res['climb'] = {k: r_climb.get(k) for k in
                        ('success', 'outcome', 'reason', 't_end', 'checks')}
        res['plan'] = plan
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'top': scene['top_z'], 'face': scene['face_x'], 'far': scene['far_x'],
                      'bearing': {k: bear[k] for k in ('coverage_y', 'max_gap_m',
                                                       'effective_area_frac')},
                      'climb': res.get('climb')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
