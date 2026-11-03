"""Stage006：从真实记录渲染 BODY_CLEARANCE 与普通轮式的并排回放。"""
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
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import stage6_rock as S6R  # noqa: E402


def load(rec):
    chunks = sorted(pathlib.Path(rec).glob('chunk_*.npz'))
    q = np.concatenate([np.load(c)['qpos'] for c in chunks])
    t = np.concatenate([np.load(c)['t'] for c in chunks])
    return q, t


def render(spec, rec, out, fps=30, w=1920, h=1080):
    spec = dict(spec); spec['render'] = {'size': [w, h]}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=120.0); env.reset(seed=0)
    q, t = load(rec)
    d = env.data
    frames = out.parent / (out.stem + '_frames'); frames.mkdir(parents=True, exist_ok=True)
    ren = mujoco.Renderer(env.model, h, w)
    cam = mujoco.MjvCamera(); cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
    cam.trackbodyid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    cam.distance = 1.6; cam.azimuth = 135.0; cam.elevation = -12.0
    t0 = float(t[0]); n = int((float(t[-1]) - t0) * fps) + 1
    nq = env.model.nq
    for i in range(n):
        k = min(len(q) - 1, max(0, int(np.searchsorted(t, t0 + i / fps))))
        d.qpos[:nq] = q[k][:nq]
        mujoco.mj_forward(env.model, d)
        ren.update_scene(d, camera=cam)
        Image.fromarray(ren.render()).save(frames / f'{i:05d}.png')
    ren.close()
    subprocess.check_call(['ffmpeg', '-y', '-framerate', str(fps), '-i', str(frames / '%05d.png'),
                           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', str(out)])
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--records', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = ROOT / a.out; out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / 'scene_tmp'; tmp.mkdir(parents=True, exist_ok=True)
    spec, mesh, scale = S6R.build(tmp, 0.30)
    spec['soil'] = v7_soil.resolve('nominal')
    recs = a.records.split(',')
    vids = []
    for r in recs:
        name = pathlib.Path(r).name
        v = out.parent / f'{name}.mp4'
        n = render(spec, ROOT / r, v)
        vids.append(v)
        print(json.dumps({'record': r, 'mp4': str(v), 'frames': n}))
    labels = ['STANCE (chassis contact)', 'BODY_CLEARANCE (+6 cm)']
    if len(vids) == 2:
        subprocess.check_call(['ffmpeg', '-y', '-i', str(vids[0]), '-i', str(vids[1]),
                               '-filter_complex',
                               f"[0:v]scale=1920:540,drawtext=text='{labels[0]}':fontsize=30:fontcolor=white:x=20:y=20[v0];"
                               f"[1:v]scale=1920:540,drawtext=text='{labels[1]}':fontsize=30:fontcolor=white:x=20:y=20[v1];"
                               "[v0][v1]vstack=inputs=2[v]", '-map', '[v]',
                               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', str(out)])
    print(json.dumps({'out': str(out)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
