"""从 run 的 record/ 50 Hz 轨迹渲染三维回放（不改轨迹）。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_replay.py \
    --run runs/v3/stage003/s4_state1f --out runs/v3/stage003/replay/leg_state1.mp4
"""
import argparse
import json
import pathlib
import subprocess
import sys

import mujoco
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain            # noqa: E402
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402
import v3_climb as vc     # noqa: E402


def load_qpos(record_dir):
    chunks = sorted(pathlib.Path(record_dir).glob('chunk_*.npz'))
    qs = []
    for c in chunks:
        z = np.load(c)
        if 'qpos' in z:
            qs.append(np.asarray(z['qpos'], dtype=np.float64))
    if not qs:
        raise SystemExit(f'no qpos in {record_dir}')
    return np.concatenate(qs, axis=0)


def build_env(run_dir, soil):
    step_fr = run_dir / 'step_fr.stl'
    step_fl = run_dir / 'step_fl.stl'
    if not step_fr.exists():
        raise SystemExit(f'missing {step_fr}')
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=2.95, name='stage003_replay',
                             objects=[{'mesh_file': str(step_fr), 'x': 1.65,
                                       'y': -0.115, 'yaw_deg': 0.0},
                                      {'mesh_file': str(step_fl), 'x': 1.74,
                                       'y': 0.185, 'yaw_deg': 0.0}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(soil)
    spec['render'] = {'size': [1920, 1080]}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=200.0)
    env.reset(seed=0)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--soil', default='nominal', choices=['rigid', 'nominal'])
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--width', type=int, default=1920)
    ap.add_argument('--height', type=int, default=1080)
    a = ap.parse_args()
    run_dir = (ROOT / a.run).resolve()
    qpos = load_qpos(run_dir / 'record')
    env = build_env(run_dir, a.soil)
    d = env.data
    if qpos.shape[0] == 0:
        raise SystemExit('empty qpos')
    n_out = int(len(qpos) / 50.0 * a.fps)
    frames = run_dir / 'replay_frames'
    frames.mkdir(parents=True, exist_ok=True)
    renderer = mujoco.Renderer(env.model, a.height, a.width)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
    cam.trackbodyid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    cam.distance = 2.6
    cam.azimuth = 135.0
    cam.elevation = -18.0
    nq = env.model.nq
    for i in range(n_out):
        k = min(len(qpos) - 1, int(i / a.fps * 50.0))
        d.qpos[:nq] = qpos[k][:nq]
        mujoco.mj_forward(env.model, d)
        renderer.update_scene(d, camera=cam)
        img = renderer.render()
        Image.fromarray(img).save(frames / f'{i:05d}.png')
    renderer.close()
    out = (ROOT / a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(['ffmpeg', '-y', '-framerate', str(a.fps),
                           '-i', str(frames / '%05d.png'), '-c:v', 'libx264',
                           '-pix_fmt', 'yuv420p', '-crf', '18', str(out)])
    print(json.dumps({'out': str(out), 'frames': n_out, 'qpos_frames': len(qpos)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
