"""
候选 / 真值的三维预览图：主角是几何本身，不被机器人遮挡。

  MUJOCO_GL=osmesa .venv/bin/python scripts/render_preview.py \
      --items "P1=runs/.../world/P1" "truth=runs/.../six_v2/truth" \
      --out runs/unseen/recovery_r3/six_v2/view

为什么重写（d067614 复核）：
  · 旧图用 mjCAMERA_FREE 但未按候选 bounds 设 distance，且机器人仍在场景里，
    结果 hyp_P1_side.png 主要是机器人轮子与机身；hyp_P3_side.png 是彩色噪点。
  · 现在：**不加载机器人**，只放候选与地面；相机按候选 bounds 自动定距。
  · 渲染数组立刻 copy() 再保存，避免帧缓冲被下一次渲染覆盖。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import trimesh
from PIL import Image

W, H = 800, 600


def scene_xml(mesh_path, checkered=True):
    """只含地面 + 一个网格的极简场景（无机器人、无遮挡）。"""
    tex = ''
    if checkered:
        tex = ('<texture name="grid" type="2d" builtin="checker" rgb1=".28 .26 .24" '
               'rgb2=".22 .20 .19" width="128" height="128"/>'
               '<material name="mgrid" texture="grid" texrepeat="6 6"/>')
    mat = ' material="mgrid"' if checkered else ''
    return f"""
<mujoco>
  <visual><headlight ambient="0.45 0.45 0.45" diffuse="0.55 0.55 0.55"/></visual>
  <asset>{tex}<mesh name="m" file="{mesh_path}"/></asset>
  <worldbody>
    <light pos="-1.4 -1.0 2.0" dir="0.5 0.35 -0.8" diffuse="0.85 0.82 0.75" castshadow="false"/>
    <geom type="plane" size="3 3 .1"{mat}/>
    <geom name="obj" type="mesh" mesh="m" rgba=".72 .58 .40 1"/>
  </worldbody>
</mujoco>"""


def render(mesh_path, out_png, azimuth, elevation, zoom=1.9):
    m = mujoco.MjModel.from_xml_string(scene_xml(mesh_path))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'obj')
    # 用几何的实际包围盒定相机，保证主角充满画面
    # geom_aabb 的语义是 **(center, size)**，不是 (lo, hi)：
    #   aabb[:3] = 几何局部中心，aabb[3:] = 半尺寸
    # 之前把 center/size 当 lo/hi，导致 lookat 偏移、物体被画面裁掉。
    c_local = np.asarray(m.geom_aabb[gid][:3], dtype=float)
    half = np.asarray(m.geom_aabb[gid][3:], dtype=float)
    R = np.asarray(d.geom_xmat[gid], dtype=float).reshape(3, 3)
    # 局部中心先按几何旋转再平移到世界
    center = np.asarray(d.geom_xpos[gid]) + R @ c_local
    diag = float(2.0 * np.linalg.norm(half))
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    r = mujoco.Renderer(m, H, W)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = [float(center[0]), float(center[1]), float(center[2])]
    cam.distance = float(max(diag * zoom, 0.08))
    cam.azimuth = float(azimuth)
    cam.elevation = float(elevation)
    r.update_scene(d, camera=cam)
    img = np.array(r.render(), copy=True)      # 立刻复制，避免缓冲被复用
    Image.fromarray(img).save(out_png)
    g = img.astype(float)
    # 目标在画面内的占比（用非背景像素估计），确保四周留白可读
    obj_px = int((np.abs(g - np.median(g)) > 12).sum())
    return {'file': pathlib.Path(out_png).name, 'mean': round(float(g.mean()), 1),
            'object_px_frac': round(obj_px / float(g.size), 4),
            'std': round(float(g.std()), 2),
            'unique_colors': int(len(np.unique(img.reshape(-1, 3), axis=0))),
            'distance_m': round(float(cam.distance), 4),
            'center': [round(float(x), 4) for x in center]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--items', nargs='+', required=True,
                    help='name=dir，目录内需有 body.stl 或 manifest.json')
    ap.add_argument('--out', required=True)
    ap.add_argument('--views', default='side,back,top')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    ang = {'side': (35, -18), 'back': (215, -12), 'top': (35, -62), 'front': (0, -5)}
    rows = []
    for spec in a.items:
        name, wd = spec.split('=', 1)
        p = pathlib.Path(wd)
        mesh = p / 'body.stl'
        if not mesh.exists():
            man = p / 'manifest.json'
            if man.exists():
                mj = json.loads(man.read_text())
                parts = mj.get('parts') or []
                if parts:
                    mesh = p / parts[0]
        if not mesh.exists():
            rows.append({'item': name, 'error': 'no mesh'})
            continue
        for v in a.views.split(','):
            az, el = ang.get(v, (35, -18))
            info = render(str(mesh.resolve()), out / f'{name}_{v}.png', az, el)
            rows.append({'item': name, 'view': v, **info})
    (out / 'preview_manifest.json').write_text(json.dumps(
        {'version': 'preview/v2',
         'note': '只含地面与几何，无机器人遮挡；相机按 bounds 定距；渲染后立即 copy',
         'rows': rows}, indent=2, ensure_ascii=False))
    for r in rows:
        print(r)
    return 0


if __name__ == '__main__':
    sys.exit(main())
