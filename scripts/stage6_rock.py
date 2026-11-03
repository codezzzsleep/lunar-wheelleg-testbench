"""Stage006：窄岩石通道上 普通站姿 vs BODY_CLEARANCE 同路径对照。"""
import argparse
import json
import pathlib
import sys

import numpy as np
import mujoco
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import terrain  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import v3_record  # noqa: E402
import v3_basic_cycle as bc  # noqa: E402
import stage6_body as SB  # noqa: E402
import stage4_config as S4C  # noqa: E402

ROCK = ROOT / 'assets/v3/rocks/moon_rock_05/h1/body.stl'
TARGET_H = 0.279
ROCK_X = 1.0


def build(out, target_h=TARGET_H):
    m = trimesh.load(str(ROCK), force='mesh')
    z0, z1 = float(m.bounds[0][2]), float(m.bounds[1][2])
    s = target_h / (z1 - z0)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0, 0, 1]))
    m.apply_scale(s)
    m.apply_translation([-float(m.bounds[0][0]) - (float(m.bounds[1][0]) - float(m.bounds[0][0])) / 2,
                         0, -float(m.bounds[0][2])])
    m.apply_translation([ROCK_X, 0.0, 0.0])
    pitch = 0.004
    origin = np.array([0.0, -0.4, 0.0]); dims = np.array([400, 200, 90])
    occ = np.zeros(tuple(dims), bool)
    vg = m.voxelized(pitch=pitch).fill()
    idx = np.floor((np.asarray(vg.points) - origin) / pitch).astype(int)
    ok = ((idx >= 0) & (idx < dims)).all(axis=1)
    idx = idx[ok]; occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    grid = out / 'rock_occ.npz'
    np.savez_compressed(grid, occupied=occ, origin=origin, pitch=np.float64(pitch),
                        dims=dims, content_sha=np.array('stage6_rock'),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    coll = out / 'coll'
    r = v3_core.build_collision(grid, coll, pitch=0.002, downsample=2)
    if not r.get('ok'):
        raise SystemExit('collision failed')
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=2.6, objects=[{'posed_dir': str(coll)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    return spec, m, s


def rock_body_id(env):
    base = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    for g in range(env.model.ngeom):
        b = int(env.model.geom_bodyid[g])
        if b != 0 and b != base and 'wheel' not in (mujoco.mj_id2name(env.model, mujoco.mjtObj.mjOBJ_BODY, b) or ''):
            nm = mujoco.mj_id2name(env.model, mujoco.mjtObj.mjOBJ_BODY, b) or ''
            if not any(k in nm for k in ('hip', 'thigh', 'calf', 'base')):
                return b
    return None


def contact_counts(env, rock_bid):
    base = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    out = {'base': 0, 'wheel': 0, 'leg': 0}
    for i in range(int(env.data.ncon)):
        c = env.data.contact[i]
        b1 = int(env.model.geom_bodyid[c.geom1]); b2 = int(env.model.geom_bodyid[c.geom2])
        other = None
        if b1 == rock_bid: other = b2
        elif b2 == rock_bid: other = b1
        if other is None: continue
        nm = mujoco.mj_id2name(env.model, mujoco.mjtObj.mjOBJ_BODY, other) or ''
        if other == base: out['base'] += 1
        elif 'wheel' in nm: out['wheel'] += 1
        else: out['leg'] += 1
    return out


def run(env, spec, snap, out, arm, raise_z, speed=0.15):
    rec = v3_record.Recorder(out / f'record_{arm}', {'arm': arm, 'skill': 'BODY_CLEARANCE' if raise_z else 'STANCE'}, hz=50.0)
    env.restore_state(snap, mode='same_scene')
    targets = {leg: dict(bc.STANCE) for leg in bc.LEG}
    k = 0; rows = []
    rock_bid = rock_body_id(env)
    # settle
    for _ in range(15):
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
        rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t)); k += 1
    if raise_z > 0:
        t2, r = SB.ramp(env, targets, 100, raise_z, k0=k)
        for _ in r:
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t)); k += 1
        targets = t2; rows += r
    # drive
    while env.t < 30.0 and float(env.data.qpos[0]) < 2.3 and not (env.terminated or env.truncated):
        env.step_command(joint_targets_rad=targets, wheel_omega_rad_s=np.full(4, speed / 0.086),
                         wheel_mode='velocity')
        rows.append({'t': round(float(env.t), 3), 'x': round(float(env.data.qpos[0]), 4),
                     'base_z': round(float(env.data.qpos[2]), 4),
                     'chassis': round(SB.chassis_min_z(env), 4),
                     'tilt': round(float(np.degrees(np.arccos(np.clip(env.data.xmat[
                         mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')][8], -1, 1)))), 3),
                     **{'contact_%s' % kk: vv for kk, vv in contact_counts(env, rock_bid).items()}})
        rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t)); k += 1

    x_end = float(env.data.qpos[0])
    if raise_z > 0:
        t3, r = SB.ramp(env, targets, 100, -raise_z, k0=k)
        for _ in r:
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t)); k += 1
        targets = t3
    ref = rec.close()
    hit = any((r.get('contact_base', 0) + r.get('contact_wheel', 0) + r.get('contact_leg', 0)) > 0 for r in rows)
    cats = {kk: max((r.get(f'contact_{kk}', 0) for r in rows), default=0) for kk in ('base', 'wheel', 'leg')}
    passed = bool(x_end > 2.2 and not env.terminated)
    res = {'arm': arm, 'raise_z': raise_z, 'x_end': round(x_end, 4),
           'terminated': bool(env.terminated), 'base_rock_contact': hit,
           'max_tilt': max((r['tilt'] for r in rows), default=0),
           'min_chassis': min((r.get('chassis', r.get('chassis_min_z')) for r in rows), default=None),
           'outcome': ('pass' if passed and cats.get('base', 0) == 0 else
                       'physical_failure' if env.terminated else
                       'blocked' if cats.get('base', 0) > 0 else 'abort'),
           'trajectory': ref,
           'n_frames': len(rows)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage006/rock')
    ap.add_argument('--height', type=float, default=TARGET_H)
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = S4C.load()
    spec, mesh, scale = build(out, a.height)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s']))
    env.reset(seed=0)
    snap = env.save_state()
    (out / 'state.json').write_text(json.dumps({'spec': spec, 'snapshot': snap,
                                                'rock_scale': scale, 'rock_height': TARGET_H},
                                               ensure_ascii=False))
    env_n = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s'])); env_n.reset(seed=0)
    r_norm = run(env_n, spec, snap, out, 'stance', 0.0)
    env_b = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s'])); env_b.reset(seed=0)
    r_body = run(env_b, spec, snap, out, 'body_clearance', 0.06)
    res = {'schema': 'stage6-rock/v1', 'rock': 'moon_rock_05', 'height_m': a.height,
           'scale': round(scale, 5), 'rock_x': ROCK_X, 'budget_s': cfg['budget_s'],
           'normal': r_norm, 'body_clearance': r_body,
           'delta': {'x_end': round(r_body['x_end'] - r_norm['x_end'], 4),
                     'contact': [r_norm['base_rock_contact'], r_body['base_rock_contact']]}}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({k: res[k] for k in ('normal', 'body_clearance', 'delta')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
