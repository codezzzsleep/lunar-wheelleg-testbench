"""
程序化障碍生成器——对照组。

输出与 Lux3D 资产**完全相同的 manifest 结构**，所以考场代码不需要区分来源。
唯一区别是 `source_kind` 字段，用来在结果里分组。

设计要点：几何量（相对高度、相对宽度、凹度）必须能和 Lux3D 组对齐，
否则两边不可比。方块/圆柱的凹度天然接近 0，这正是"形状细节"这个自变量。
"""
import json, pathlib, sys
import numpy as np
import trimesh

WHEEL_R = 0.086
WHEELBASE = 0.38


def make_box(h, width=0.30, depth=0.30):
    m = trimesh.creation.box(extents=[depth, width, h])
    return m, {'shape': 'box', 'rel_width_override': width / WHEELBASE}


def make_cylinder(h, radius=0.15):
    m = trimesh.creation.cylinder(radius=radius, height=h, sections=48)
    return m, {'shape': 'cylinder', 'rel_width_override': 2 * radius / WHEELBASE}


def make_ramp(h, run=0.6, width=0.34):
    """
    楔形坡道：**低端朝机器人来向（-x）**，沿 +x 逐渐升高。

    旧实现的竖直高面在 x=0、低端在 x=+run，机器人从 -x 开来正好撞墙，
    与"爬坡"语义相反。现在改成低端在 x=0，并在构建后校验水密性与体积符号。
    """
    w2 = width / 2
    verts = np.array([
        [0.0, -w2, 0.0],   # 0 低端 后
        [run, -w2, 0.0],   # 1 高端 后 下
        [run, -w2, h],     # 2 高端 后 上
        [0.0,  w2, 0.0],   # 3 低端 前
        [run,  w2, 0.0],   # 4 高端 前 下
        [run,  w2, h],     # 5 高端 前 上
    ])
    faces = np.array([
        [0, 1, 4], [0, 4, 3],   # 底面
        [1, 2, 5], [1, 5, 4],   # 高端竖直面 (+x)
        [0, 3, 5], [0, 5, 2],   # 斜面
        [0, 2, 1],              # 侧面 -y
        [3, 4, 5],              # 侧面 +y
    ])
    m = trimesh.Trimesh(verts, faces, process=True)
    _assert_closed(faces, 'ramp')
    if float(m.volume) < 0:      # 面朝向内 -> 翻转，否则体积与法向都是反的
        m.invert()
    m.apply_translation([-run / 2, 0, 0])
    m.apply_translation([0, 0, -m.bounds[0][2]])
    return m, {'shape': 'ramp', 'ramp_low_end': '-x', 'rel_width_override': width / WHEELBASE}


def _assert_closed(faces, name):
    """不依赖 scipy 的闭合性检查：每条无向边必须恰好被两个面共享。"""
    from collections import Counter
    edges = Counter()
    for f in faces:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            edges[tuple(sorted((int(a), int(b))))] += 1
    bad = {e: c for e, c in edges.items() if c != 2}
    assert not bad, f'{name} 网格不闭合，异常边 {list(bad.items())[:4]}'


SHAPES = {'box': make_box, 'cylinder': make_cylinder, 'ramp': make_ramp}


def build(shape, height_m, out_root='assets/processed', **kw):
    import manifold3d as m3
    gen = SHAPES[shape]
    mesh, extra = gen(height_m, **kw)

    mesh.apply_translation([-mesh.centroid[0], -mesh.centroid[1], -mesh.bounds[0][2]])
    pts = np.asarray(mesh.vertices, dtype=np.float32)
    hull_vol = abs(float(m3.Manifold.hull_points(pts).volume()))

    name = f'proc_{shape}_h{int(round(height_m * 1000)):03d}'
    out = pathlib.Path(out_root) / name
    if out.exists():
        import shutil; shutil.rmtree(out)
    (out / 'parts').mkdir(parents=True, exist_ok=True)

    # 凸形状本身就是一块，无需 CoACD
    part = out / 'parts' / 'part_00.stl'
    mesh.export(part)

    man = {
        'source': f'procedural:{shape}',
        'source_kind': 'procedural',
        'shape': extra['shape'],
        'raw_extents_m': [round(float(x), 4) for x in mesh.extents],
        'applied_scale': 1.0,
        'height_m': round(float(mesh.extents[2]), 4),
        'width_x_m': round(float(mesh.extents[0]), 4),
        'width_y_m': round(float(mesh.extents[1]), 4),
        'rel_height': round(float(mesh.extents[2]) / WHEEL_R, 3),
        'rel_width': round(extra['rel_width_override'], 3),
        'watertight': bool(mesh.is_watertight),
        'faces': int(len(mesh.faces)),
        'volume_m3': round(float(abs(mesh.volume)), 6),
        'convex_hull_volume_m3': round(hull_vol, 6),
        'concavity': round(float(1 - abs(float(mesh.volume)) / hull_vol), 4) if hull_vol else None,
        'coacd_parts': 1,
        'coacd_seconds': 0.0,
        'hit_part_cap': False,
        'near_convex_hull_substituted': False,
        'parts_volume_m3': round(float(abs(float(mesh.volume))), 6),
        'parts': [f'parts/{part.name}'],
        'pass': True,
    }
    (out / 'manifest.json').write_text(json.dumps(man, indent=2, ensure_ascii=False))
    return name, man


if __name__ == '__main__':
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument('--shapes', default='box', help='逗号分隔：box,cylinder,ramp')
    ARGS = ap.parse_args()
    SHAPES_TO_BUILD = [x.strip() for x in ARGS.shapes.split(',') if x.strip()]
    # 1) 固定阶梯：画出能力曲线
    ladder = [0.05, 0.09, 0.13, 0.17, 0.228, 0.285, 0.40, 0.593]
    # 2) 自动对齐：每个 Lux3D 资产实测出的相对高度，各生成一个同宽同高的方块
    lux_h = []
    for mf in pathlib.Path('assets/processed').glob('*_w300/manifest.json'):
        try:
            d = json.loads(mf.read_text())
            lux_h.append(round(d['rel_height'] * WHEEL_R, 4))
        except Exception:
            pass
    for h in sorted(set(ladder) | set(lux_h)):
        for shape in SHAPES_TO_BUILD:
            name, man = build(shape, h)
            print(f"{name:26s} rel_h={man['rel_height']:5.2f} rel_w={man['rel_width']:5.2f}")
