"""Stage004：从真实 record/ 渲染岩石场景回放（不改轨迹）。"""
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
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402


def load_qpos(record_dir):
    chunks = sorted(pathlib.Path(record_dir).glob('chunk_*.npz'))
    qs, ts = [], []
    for c in chunks:
        z = np.load(c)
        qs.append(np.asarray(z['qpos'], dtype=np.float64))
        ts.append(np.asarray(z['t'], dtype=np.float64))
    return np.concatenate(qs, axis=0), np.concatenate(ts, axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--record', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--width', type=int, default=1920)
    ap.add_argument('--height', type=int, default=1080)
    a = ap.parse_args()
    spec = json.loads((ROOT / a.state / 'scene_spec.json').read_text())
    spec['soil'] = v7_soil.resolve('nominal')
    spec['render'] = {'size': [a.width, a.height]}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=120.0)
    env.reset(seed=0)
    qpos, ts = load_qpos(ROOT / a.record)
    d = env.data
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = out.parent / (out.stem + '_frames')
    frames.mkdir(parents=True, exist_ok=True)
    ren = mujoco.Renderer(env.model, a.height, a.width)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
    cam.trackbodyid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    cam.distance = 2.2
    cam.azimuth = 135.0
    cam.elevation = -15.0
    t0 = float(ts[0])
    n_out = int((float(ts[-1]) - t0) * a.fps) + 1
    nq = env.model.nq
    for i in range(n_out):
        k = int(np.searchsorted(ts, t0 + i / a.fps))
        k = min(len(qpos) - 1, max(0, k))
        d.qpos[:nq] = qpos[k][:nq]
        mujoco.mj_forward(env.model, d)
        ren.update_scene(d, camera=cam)
        Image.fromarray(ren.render()).save(frames / f'{i:05d}.png')
    ren.close()
    subprocess.check_call(['ffmpeg', '-y', '-framerate', str(a.fps),
                           '-i', str(frames / '%05d.png'), '-c:v', 'libx264',
                           '-pix_fmt', 'yuv420p', '-crf', '20', str(out)])
    print(json.dumps({'out': str(out), 'frames': n_out,
                      't_first': round(t0, 3), 't_last': round(float(ts[-1]), 3)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
