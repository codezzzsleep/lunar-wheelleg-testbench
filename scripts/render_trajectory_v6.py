"""
V6 工作包 I2：只读轨迹回放渲染（不在渲染中推进物理/改控制）。
输入 trajectory/v1；输出 GIF + 首帧 PNG。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import terrain
import wheelleg_env
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trajectory', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--width', type=int, default=640)
    ap.add_argument('--height', type=int, default=480)
    ap.add_argument('--fps', type=int, default=10)
    ap.add_argument('--max-frames', type=int, default=360)
    a = ap.parse_args()
    tr = json.loads(pathlib.Path(a.trajectory).read_text())
    frames = tr['frames']
    spec = terrain.make_spec(kind='flat', seed=tr['seed'], objects=[], goal_x=tr['goal_x'],
                             name='v6_replay')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': tr['collision']}]
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=tr['time_limit_s'],
                                   v_ref=1.0, tip_deg=60.0)
    env.reset(seed=tr['seed'])
    cid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    m, d = env.model, env.data
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [1.15, 0.0, 0.18]
    cam.distance = 2.0
    cam.azimuth = 135.0
    cam.elevation = -18.0
    m.vis.global_.offwidth = a.width
    m.vis.global_.offheight = a.height
    r = mujoco.Renderer(m, a.height, a.width)
    step = max(1, int(round((1.0 / a.fps) / 0.02)))
    idx = list(range(0, len(frames), step))[:a.max_frames]
    imgs = []
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    for n, i in enumerate(idx):
        f = frames[i]
        d.qpos[:] = np.asarray(f['qpos'], dtype=np.float64)
        d.qvel[:] = np.asarray(f['qvel'], dtype=np.float64)
        mujoco.mj_forward(m, d)
        r.update_scene(d, camera=cam)
        rgb = r.render()
        im = Image.fromarray(rgb)
        dr = ImageDraw.Draw(im)
        dr.rectangle([0, 0, 220, 34], fill=(0, 0, 0))
        dr.text((6, 5), f"{tr['label']}  t={f['t']:.2f}s", fill=(255, 255, 255))
        dr.text((6, 19), f"frame {i}/{len(frames)-1}  {tr['result']['reason']}",
                fill=(220, 220, 220))
        imgs.append(im.convert('P', palette=Image.ADAPTIVE, colors=128))
    if not imgs:
        raise SystemExit('没有帧')
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=int(1000 / a.fps),
                 loop=0, optimize=True)
    imgs[0].convert('RGB').save(out.with_suffix('.png'))
    print(json.dumps({'out': str(out), 'frames': len(imgs), 'png': str(out.with_suffix('.png')),
                      'reason': tr['result']['reason']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
