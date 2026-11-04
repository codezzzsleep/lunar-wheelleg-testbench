"""Stage008 修正：唯一真实执行场景（真实岩石+墙+地面+nominal），冻结碰撞 SHA、共同 S0 与共享 V。"""
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
import observe  # noqa: E402
import v3_fuse  # noqa: E402

PITCH = 0.004
ORIGIN = np.array([0.60, -0.80, 0.0])
DIMS = np.array([200, 400, 105])
ROCK = ROOT / 'assets/v3/rocks/moon_rock_05/h1/body.stl'
H = 0.30


def rock_world():
    m = trimesh.load(str(ROCK), force='mesh')
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
    m.apply_scale(H / float(m.bounds[1][2] - m.bounds[0][2]))
    m.apply_translation([-float((m.bounds[0][0] + m.bounds[1][0]) / 2) + 1.0,
                         -float((m.bounds[0][1] + m.bounds[1][1]) / 2),
                         -float(m.bounds[0][2])])
    return m


def wall_meshes():
    out = []
    for y in (-0.55, 0.55):
        b = trimesh.creation.box(extents=[0.5, 0.5, 0.32])
        b.apply_translation([1.0, y, 0.16])
        out.append(b)
    return out


def main():
    out = (ROOT / 'runs/v3/stage008/truth_v2').resolve()
    out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    rock = rock_world()
    occ = np.zeros(tuple(DIMS), bool)
    vg = rock.voxelized(pitch=PITCH).fill()
    idx = np.floor((np.asarray(vg.points) - ORIGIN) / PITCH).astype(int)
    ok = ((idx >= 0) & (idx < DIMS)).all(axis=1); idx = idx[ok]
    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    for w in wall_meshes():
        wv = w.voxelized(pitch=PITCH).fill()
        wi = np.floor((np.asarray(wv.points) - ORIGIN) / PITCH).astype(int)
        ok = ((wi >= 0) & (wi < DIMS)).all(axis=1); wi = wi[ok]
        occ[wi[:, 0], wi[:, 1], wi[:, 2]] = True
    truth_sha = hashlib.sha256(np.ascontiguousarray(occ).tobytes()).hexdigest()
    grid = out / 'truth_occ.npz'
    np.savez_compressed(grid, occupied=occ, origin=ORIGIN, pitch=np.float64(PITCH),
                        dims=DIMS, content_sha=np.array(truth_sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    coll = out / 'truth_coll'
    r = v3_core.build_collision(grid, coll, pitch=PITCH, downsample=1)
    if not r.get('ok'):
        raise SystemExit(f'collision failed: {r.get("error")}')
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=2.6,
                             name='stage8_truth_v2', objects=[{'posed_dir': str(coll)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=120.0); env.reset(seed=0)
    for _ in range(30):
        env.brake_step()
    snap = env.save_state()
    (out / 'scene_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    (out / 'state_snapshot.json').write_text(json.dumps(snap, ensure_ascii=False))
    tdir = out / 'truth'; tdir.mkdir(exist_ok=True)
    rock.export(tdir / 'body_world.stl')
    (tdir / 'manifest.json').write_text(json.dumps(
        {'schema': 'v3-truth/v1', 'rock_id': 'moon_rock_05', 'height_m': H,
         'world_pose': {'pos': [1.0, 0.0, 0.0]}, 'truth_occ_sha256': truth_sha,
         'collision': str(coll.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    # 观测场景：真实纹理/网格可见体（岩石 + 墙），S0 姿态一致
    rock_local = rock.copy(); rock_local.apply_translation([-1.0, 0.0, 0.0])
    rock_local.export(out / 'rock_local.stl')
    for i, w in enumerate(wall_meshes()):
        w.export(out / f'wall_{i}.stl')
    ospec = terrain.make_spec(kind='flat', seed=0, goal_x=2.6, objects=[], name='stage8_obs_v2')
    cam = proto['cameras']['planning']
    ospec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    ospec['front_cam'] = {'pos': [float(x) for x in cam['local_pos']],
                          'pitch_deg': float(cam['pitch_deg']), 'fovy': float(cam['fovy_deg'])}
    ospec['start'] = [0.0, 0.0]
    ospec['objects'] = [{'mesh_file': str(out / 'rock_local.stl'), 'x': 1.0, 'y': 0.0,
                         'yaw_deg': 0.0, 'target_height_m': H},
                        {'mesh_file': str(out / 'wall_0.stl'), 'x': 0.0, 'y': 0.0,
                         'yaw_deg': 0.0, 'target_height_m': 0.32},
                        {'mesh_file': str(out / 'wall_1.stl'), 'x': 0.0, 'y': 0.0,
                         'yaw_deg': 0.0, 'target_height_m': 0.32}]
    ospec['soil'] = v7_soil.resolve('nominal')
    oenv = wheelleg_env.WheelLegEnv(ospec, max_seconds=120.0); oenv.reset(seed=0)
    for _ in range(30):
        oenv.brake_step()
    observe.capture_observation(oenv, out, width=int(cam['width']), height=int(cam['height']),
                                fovy=float(cam['fovy_deg']), obs_id='stage8_truth_v2',
                                extra={'reconstructed': True})
    for name in ('rgb.png', 'mask.png', 'depth.npy', 'visible_points.npy', 'observation.json'):
        src = out / name
        if src.exists():
            od = out / 'observation'; od.mkdir(exist_ok=True)
            src.replace(od / name)
    obs = json.loads((out / 'observation' / 'observation.json').read_text())
    obs['reconstructed'] = True
    obs['note'] = 'reconstructed observation from the single truth scene at the common S0'
    (out / 'observation' / 'observation.json').write_text(json.dumps(obs, ensure_ascii=False, indent=2))
    obs_sha = hashlib.sha256((out / 'observation' / 'observation.json').read_bytes()).hexdigest()
    (out / 'state.json').write_text(json.dumps(
        {'state_id': 'stage8_truth_v2', 'visible': obs['visible'],
         'observation_sha256': obs_sha, 'observation_kind': 'reconstructed',
         'truth_occ_sha256': truth_sha, 's0_state_hash': snap.get('state_hash')},
        ensure_ascii=False, indent=2))
    art = v3_fuse.write_v_artifact(out, proto)
    (out / 'truth_manifest.json').write_text(json.dumps(
        {'schema': 'stage8-truth-scene/v1', 'truth_occ_sha256': truth_sha,
         'coll_dir': str(coll.relative_to(ROOT)), 's0_state_hash': snap.get('state_hash'),
         'v_sha': art['v_sha'], 'v_stats': art['stats'],
         'observation_sha256': obs_sha, 'reconstructed_observation': True,
         'note': 'single truth scene for every FULL/OBS/reference execution'},
        ensure_ascii=False, indent=2))
    print(json.dumps({'truth_sha': truth_sha[:16], 's0': snap.get('state_hash'),
                      'v': art['v_sha'][:16], 'visible': obs['visible']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
