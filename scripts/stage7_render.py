"""Stage007：按冻结布局渲染目标岩石的场景图与生成输入图（真实纹理）。"""
import argparse
import json
import pathlib
import sys

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import mujoco  # noqa: E402

ROCK = ROOT / 'assets/v3/rocks/moon_rock_05'
SCALE = 1.74419
ROCK_POS = (1.0, 0.0, 0.0)
YAW = 90.0


def xml(include_walls, w=1536, h=1536):
    walls = ''
    if include_walls:
        walls = ('<geom type="box" pos="1.0 -0.55 0.16" size="0.25 0.25 0.16" rgba="0.62 0.60 0.57 1"/>'
                 '<geom type="box" pos="1.0 0.55 0.16" size="0.25 0.25 0.16" rgba="0.62 0.60 0.57 1"/>')
    return f'''<mujoco>
  <compiler meshdir="{ROCK / 'h1'}" texturedir="{ROCK}"/>
  <visual><global offwidth="{w}" offheight="{h}"/></visual>
  <asset>
    <texture name="rocktex" type="2d" file="texture.png"/>
    <material name="rockmat" texture="rocktex" rgba="1 1 1 1"/>
    <texture name="checker" type="2d" builtin="checker" rgb1="0.72 0.72 0.70" rgb2="0.62 0.62 0.60"
             width="512" height="512"/>
    <material name="floormat" texture="checker" texrepeat="8 8" rgba="1 1 1 1"/>
  </asset>
  <worldbody>
    <light pos="0 0 3" dir="0 0 -1" diffuse="0.9 0.9 0.9"/>
    <light pos="2 -2 2" dir="-1 1 -0.5" diffuse="0.35 0.35 0.35"/>
    <geom name="floor" type="plane" size="6 6 0.1" material="floormat"/>
    {walls}
    <body name="rock" pos="{ROCK_POS[0]} {ROCK_POS[1]} {ROCK_POS[2]}" euler="0 0 {YAW}">
      <geom type="mesh" mesh="rockmesh" material="rockmat"/>
    </body>
  </worldbody>
</mujoco>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage007/render')
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    # rockmesh 需要在 XML 里声明；单独补一个 asset 项
    base = xml(True).replace('<texture name="rocktex"',
                             f'<mesh name="rockmesh" file="body_vis.obj" scale="{SCALE} {SCALE} {SCALE}"/>\n    <texture name="rocktex"')
    scene_xml = out / 'scene.xml'; scene_xml.write_text(base)
    target_xml = out / 'target.xml'; target_xml.write_text(base.replace(
        '<geom type="box" pos="1.0 -0.55 0.16" size="0.25 0.25 0.16" rgba="0.62 0.60 0.57 1"/><geom type="box" pos="1.0 0.55 0.16" size="0.25 0.25 0.16" rgba="0.62 0.60 0.57 1"/>', ''))
    meta = {'source_rock': 'moon_rock_05', 'scale': SCALE, 'yaw_deg': YAW,
            'rock_pos': ROCK_POS, 'layout': 'stage7 narrow passage'}
    for name, x in (('scene', scene_xml), ('target', target_xml)):
        m = mujoco.MjModel.from_xml_path(str(x))
        d = mujoco.MjData(m); mujoco.mj_forward(m, d)
        r = mujoco.Renderer(m, 1536, 1536)
        cam = mujoco.MjvCamera()
        cam.lookat[:] = [1.0, 0.0, 0.16]; cam.distance = 0.95
        cam.azimuth = 133.0; cam.elevation = -14.0
        r.update_scene(d, camera=cam)
        img = r.render(); r.close()
        Image.fromarray(img).save(out / f'{name}_1536.png')
        meta[name] = f'{name}_1536.png'
    (out / 'render.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(json.dumps(meta))
    return 0


if __name__ == '__main__':
    sys.exit(main())
