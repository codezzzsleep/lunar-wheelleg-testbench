"""Stage008：为 layout2 建立一次重建观测（固定场景/S0/相机）与真值母体。"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import observe  # noqa: E402

ROCK = ROOT / 'assets/v3/rocks/moon_rock_05/h1/body.stl'
H = 0.30


def rock_local():
    m = trimesh.load(str(ROCK), force='mesh')
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
    m.apply_scale(H / float(m.bounds[1][2] - m.bounds[0][2]))
    m.apply_translation([-float((m.bounds[0][0] + m.bounds[1][0]) / 2),
                         -float((m.bounds[0][1] + m.bounds[1][1]) / 2),
                         -float(m.bounds[0][2])])
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage008/state_layout2')
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((ROOT / a.protocol).read_text())
    m = rock_local()
    mesh_p = out / 'rock_local.stl'; m.export(mesh_p)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=2.6, objects=[],
                             name='stage8_layout2_ref')
    sc = proto['scene']; cam = proto['cameras']['planning']
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['front_cam'] = {'pos': [float(x) for x in cam['local_pos']],
                         'pitch_deg': float(cam['pitch_deg']),
                         'fovy': float(cam['fovy_deg'])}
    spec['start'] = [0.0, 0.0]
    spec['objects'] = [{'mesh_file': str(mesh_p), 'x': 1.0, 'y': 0.0,
                        'yaw_deg': 0.0, 'target_height_m': H}]
    spec['soil'] = v7_soil.resolve('nominal')
    env = wheelleg_env.WheelLegEnv(spec, control_hz=float(sc['control_hz']),
                                   max_seconds=float(sc['budget_s']), v_ref=1.0,
                                   tip_deg=float(sc['tip_deg']))
    env.reset(seed=int(sc['reset_seed']))
    for _ in range(30):
        env.brake_step()
    snap = env.save_state()
    (out / 'scene_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    (out / 'state_snapshot.json').write_text(json.dumps(snap, ensure_ascii=False))
    plan = proto['cameras']['planning']
    observe.capture_observation(env, out, width=int(plan['width']), height=int(plan['height']),
                                fovy=float(plan['fovy_deg']), obs_id='stage8_layout2_ref',
                                extra={'reconstructed': True,
                                       'note': 're-rendered from the frozen layout; not an original capture'})
    # capture_observation 把文件写在根目录；整理成 v3_fuse 期望的 observation/ 布局
    obs_dir = out / 'observation'; obs_dir.mkdir(exist_ok=True)
    for name in ('rgb.png', 'mask.png', 'depth.npy', 'visible_points.npy', 'observation.json'):
        src = out / name
        if src.exists():
            src.replace(obs_dir / name)
    obs = json.loads((obs_dir / 'observation.json').read_text())
    obs['reconstructed'] = True
    obs['note'] = 'reconstructed observation from the frozen Stage008 layout; not an original field capture'
    (obs_dir / 'observation.json').write_text(json.dumps(obs, ensure_ascii=False, indent=2))
    import hashlib
    obs_sha = hashlib.sha256((obs_dir / 'observation.json').read_bytes()).hexdigest()
    (out / 'state.json').write_text(json.dumps(
        {'state_id': 'stage8_layout2_ref', 'visible': obs['visible'],
         'observation_sha256': obs_sha,
         'observation_kind': 'reconstructed'}, ensure_ascii=False, indent=2))
    tdir = out / 'truth'; tdir.mkdir(exist_ok=True)
    world = m.copy(); world.apply_translation([1.0, 0.0, 0.0])
    world.export(tdir / 'body_world.stl')
    (tdir / 'manifest.json').write_text(json.dumps(
        {'schema': 'v3-truth/v1', 'rock_id': 'moon_rock_05', 'height_m': H,
         'world_pose': {'pos': [1.0, 0.0, 0.0], 'yaw_deg': 90.0},
         'note': 'truth mesh for parent-prior diagnostics only'}, ensure_ascii=False, indent=2))
    print(json.dumps({'state': str(out), 'visible': obs.get('visible'),
                      'mask_px': obs.get('mask_box')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
