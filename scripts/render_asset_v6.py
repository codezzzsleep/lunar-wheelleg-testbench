"""V6：单帧资产对照渲染（raw / H5-F / B3-F / truth），不推进物理。"""
import argparse
import pathlib
import sys

import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import wheelleg_env
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--posed', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', default='')
    ap.add_argument('--width', type=int, default=640)
    ap.add_argument('--height', type=int, default=480)
    ap.add_argument('--lookat-x', type=float, default=1.72)
    ap.add_argument('--distance', type=float, default=0.62)
    a = ap.parse_args()
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='v6_asset')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['objects'] = [{'posed_dir': a.posed}]
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    m.vis.global_.offwidth = a.width
    m.vis.global_.offheight = a.height
    r = mujoco.Renderer(m, a.height, a.width)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [a.lookat_x, 0.0, 0.15]
    cam.distance = a.distance
    cam.azimuth = 135.0
    cam.elevation = -8.0
    mujoco.mj_forward(m, d)
    r.update_scene(d, camera=cam)
    im = Image.fromarray(r.render())
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, 260, 22], fill=(0, 0, 0))
    dr.text((5, 4), a.label, fill=(255, 255, 255))
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    print(str(out))


if __name__ == '__main__':
    main()
