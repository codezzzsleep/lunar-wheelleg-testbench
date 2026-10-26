"""
实验 2：参考 → 场景。

  .venv/bin/python scripts/reference_to_scene.py --reference references/pack_A --out runs/ref_scene

输入是一个**参考包**（图片 + 任务描述 + 来源声明），输出是可运行的 scene_spec 与渲染图。

诚实边界：
  · 本包的图片是**程序化渲染的合成参考**（synthetic），不是照片、不是真实地形数据。
    因此不能声称"照片重建"或"真实地形恢复"。
  · 场景里的几何来自 Lux3D 生成的资产（已有授权额度内），地形由 scene_spec 参数化。
  · 参考图 → scene_spec 的映射是**显式规则**（读参考包的 JSON 参数），不是视觉模型推理。
    这一点必须写清楚，否则会被误读成"看图生成场景"。
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_pack(pack):
    p = pathlib.Path(pack)
    meta = json.loads((p / 'meta.json').read_text())
    text = (p / 'task.txt').read_text().strip()
    return p, meta, text


def spec_from_reference(meta, text):
    """
    显式规则映射（不是视觉推理）：
      meta.terrain      -> scene kind / slope / roughness
      meta.objects      -> 放哪些生成资产、放哪
      meta.difficulty   -> 目标横向偏移与高度档
    """
    t = meta['terrain']
    objs = []
    for i, o in enumerate(meta['objects']):
        objs.append({'asset': o['asset'], 'x': o.get('x', 1.8),
                     'y': o.get('y', 0.0), 'yaw_deg': o.get('yaw_deg', 0.0)})
    spec = terrain.make_spec(
        kind=t['kind'], seed=meta.get('seed', 0),
        slope_deg=t.get('slope_deg', 0.0), roughness=t.get('roughness', 0.0),
        pits=t.get('pits', 0), pit_depth=t.get('pit_depth', 0.0),
        objects=objs, goal_x=meta.get('goal_x', 3.4),
        name=meta.get('name', 'ref_scene'))
    spec['provenance'] = {
        'reference': str(meta.get('_pack_name', 'unknown')),
        'reference_kind': meta.get('reference_kind', 'synthetic'),
        'task_text': text,
        'mapping': 'explicit_rules',
        'terrain_representation': 'heightfield',
        'note': '参考图为程序化渲染的合成图；映射为显式规则，非视觉模型推理',
    }
    return spec


def render_scene(spec, out_png, frames=3):
    import mujoco
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset()
    m, d = env.model, env.data
    W, H = 900, 520
    m.vis.global_.offwidth = W
    m.vis.global_.offheight = H
    r = mujoco.Renderer(m, H, W)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.distance, cam.elevation, cam.azimuth = 3.4, -22, 108
    shots = []
    for k in range(frames):
        for _ in range(90):
            env.step([0.0] * wheelleg_env.ACT_DIM)
        cam.lookat[:] = [float(d.qpos[0]) + 0.8, 0.0, 0.15]
        r.update_scene(d, camera=cam)
        shots.append(Image.fromarray(r.render()))
    strip = Image.new('RGB', (W, H * frames))
    for i, im in enumerate(shots):
        strip.paste(im, (0, i * H))
    strip.save(out_png)
    return out_png, [float(d.qpos[0])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reference', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    pack, meta, text = load_pack(a.reference)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    spec = spec_from_reference(meta, text)
    (out / 'scene_spec.json').write_text(json.dumps(spec, indent=2, ensure_ascii=False))

    env = wheelleg_env.WheelLegEnv(spec)
    obs, _ = env.reset()
    roll = []
    info = {'reason': None, 't': 0.0, 'x': 0.0, 'tilt_deg': 0.0}
    for i in range(int(env.max_seconds / (env.substeps * env.dt)) + 5):
        obs, r, te, tr, info = env.step([0.0] * wheelleg_env.ACT_DIM)
        if i % 20 == 0:
            roll.append({'t': info['t'], 'x': info['x'], 'tilt': info['tilt_deg']})
        if te or tr:
            break
    (out / 'rollout.json').write_text(json.dumps(
        {'final': info, 'trace': roll}, indent=2, ensure_ascii=False))

    png, _ = render_scene(spec, out / 'scene_render.png')
    result = {
        'reference_pack': str(pack.relative_to(ROOT)) if str(pack).startswith(str(ROOT)) else str(pack),
        'reference_kind': meta.get('reference_kind', 'synthetic'),
        'task_text': text,
        'scene_identity': terrain.scene_identity(spec),
        'objects': spec['objects'],
        'terrain': spec['terrain'],
        'robot_outcome': {'reason': info['reason'], 'x': info['x'],
                          'contact_scene': True},
        'artifacts': {'scene_spec': 'scene_spec.json', 'rollout': 'rollout.json',
                      'render': 'scene_render.png'},
        'honesty': ['参考图为合成渲染，不是照片或真实地形数据',
                    '参考→spec 为显式规则映射，不是视觉模型推理',
                    '地形为 heightfield，物体为 Lux3D 生成的静态碰撞体'],
    }
    (out / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
