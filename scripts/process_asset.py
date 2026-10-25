"""
资产管线：Lux3D GLB -> 可上考场的障碍物

做什么：
  1. 朝向归一（glTF 是 Y-up，MuJoCo 是 Z-up）
  2. 尺度归一（Lux3D 的"AI 估计尺寸"不可信，按目标高度定标，原始尺寸记档）
  3. 落地、居中
  4. 几何量：相对高度 / 相对宽度 / 凹度 / 水密性
  5. CoACD 拆凸块（MuJoCo 对闭合网格按凸包碰撞，不拆就丢凹槽）
  6. 输出 parts/*.stl + manifest.json

用法：python scripts/process_asset.py assets/raw/cargo_crate.glb --height 0.28
"""
import argparse, json, pathlib, shutil, time
import numpy as np
import trimesh

WHEEL_R = 0.086      # go2w 轮半径（从 wheel.stl 量得 0.086 m）
WHEELBASE = 0.38     # 左右轮心距（go2w 模型读数）


def load_glb(path):
    scene = trimesh.load(path, force='scene')
    if isinstance(scene, trimesh.Scene):
        # 用 to_geometry()：它会应用节点变换与实例。
        # 旧实现直接 concatenate(scene.geometry.values())，多节点/带位姿的 GLB 会丢变换。
        geom = scene.to_geometry()
        if isinstance(geom, trimesh.Scene):
            geoms = [g for g in geom.geometry.values() if len(g.faces) > 0]
            mesh = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
        else:
            mesh = geom
    else:
        mesh = scene
    return mesh


def rest_pose(mesh):
    """
    选最稳定的落地姿态：24 个轴对齐旋转里，取"高度最小（接地面积最大）"的那个。

    为什么需要：Lux3D 输出的朝向不受控。一块本来平放的太阳能板，如果按它的
    原始上轴立起来再按宽度归一到 0.30 m，就会变成一堵 2 m 高的墙（实测 rel_h 24.5），
    和"一块躺在地上的板"完全是两回事。
    """
    import itertools
    best, best_h = mesh, mesh.extents[2]
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product([1, -1], repeat=3):
            M = np.zeros((3, 3))
            for i, (src, sg) in enumerate(zip(perm, signs)):
                M[i, src] = sg
            if np.linalg.det(M) < 0:
                continue
            m = mesh.copy()
            T = np.eye(4)
            T[:3, :3] = M
            m.apply_transform(T)
            h = m.extents[2]
            if h < best_h - 1e-6:
                best, best_h = m, h
    return best


def to_z_up(mesh):
    """glTF/GLB 是 Y-up；绕 X 轴 +90° 把 +Y 转到 +Z。"""
    return mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))


def hull_volume_of(mesh):
    """
    凸包体积。凸包永远闭合，所以不依赖原网格是否水密。

    用 manifold3d 而不是 trimesh.convex_hull：后者需要 scipy，而本机装 scipy
    要几十分钟。manifold3d 已经是 CoACD/网格处理的依赖，且结果精确
    （单位立方体实测 1.0）。
    """
    try:
        import manifold3d as m3
        pts = np.asarray(mesh.vertices, dtype=np.float32)
        if len(pts) < 4:
            return None
        h = m3.Manifold.hull_points(pts)
        return abs(float(h.volume()))
    except Exception:
        return None


def concavity_from_parts(parts_volume, hull_volume):
    """
    凹度 = 1 - 凸块总体积 / 凸包体积。

    为什么不用「网格体积/凸包体积」：Lux3D 输出的网格基本都不是水密的
    （实测 191,926 面的椅子 watertight=False），网格体积不可靠。
    凸块由 CoACD 保证是凸多面体，体积稳定，因此改用凸块侧算。
    """
    if not hull_volume or hull_volume <= 0 or not parts_volume:
        return None
    return round(float(1 - parts_volume / hull_volume), 4)


def process(glb, target_height, out_dir, threshold=0.05, target_width=None, rest=True, quiet=True):
    import coacd
    out_dir = pathlib.Path(out_dir)
    # 清空旧输出，否则上一轮拆出的凸块会残留在目录里，
    # manifest 只引用新的一部分，旧文件会变成误导性的"幽灵资产"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / 'parts').mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    raw = load_glb(glb)
    raw_dims = raw.extents.copy()

    m = to_z_up(raw.copy())
    if rest:
        m = rest_pose(m)
    # 归一化轴必须和对照组一致：
    #   按高度归一 -> 物体可能窄得像石子（轮距 0.38 m 直接从旁边过去）
    #   按宽度归一 -> 保证"是否被轮子骑上"这个主导变量对齐
    # 所以正式对照一律按侧向宽度归一，测出的相对高度才是分层依据。
    if target_width is not None:
        scale = target_width / float(m.extents[1])
    else:
        scale = target_height / float(m.extents[2])
    m.apply_scale(scale)
    m.apply_translation([-m.centroid[0], -m.centroid[1], -m.bounds[0][2]])

    hull_vol = hull_volume_of(m)
    metrics = {
        'source': str(glb),
        'norm_axis': 'width' if target_width is not None else 'height',
        'target_width_m': None if target_width is None else round(float(target_width), 4),
        'raw_extents_m': [round(float(x), 4) for x in raw_dims],
        'applied_scale': round(float(scale), 6),
        'height_m': round(float(m.extents[2]), 4),
        'width_x_m': round(float(m.extents[0]), 4),
        'width_y_m': round(float(m.extents[1]), 4),
        'rel_height': round(float(m.extents[2]) / WHEEL_R, 3),
        'rel_width': round(float(m.extents[1]) / WHEELBASE, 3),
        'watertight': bool(m.is_watertight),
        'faces': int(len(m.faces)),
        'volume_m3': round(float(abs(m.volume)), 6) if m.is_watertight else None,
        'convex_hull_volume_m3': hull_vol,
        'concavity': None,   # 拆完凸块后再算
    }

    # 两段式：先用粗参数快速判断凹凸，近凸的直接用一个精确凸包（省掉一次全量拆分）
    t1 = time.time()
    cm = coacd.Mesh(m.vertices, m.faces)
    near_convex = False
    if hull_vol:
        coarse = coacd.run_coacd(cm, threshold=0.20, max_convex_hull=4)
        cvol = sum(abs(float(trimesh.Trimesh(np.asarray(v), np.asarray(f)).volume))
                   for v, f in coarse if len(f) >= 4)
        if cvol and 1 - cvol / hull_vol < 0.05:
            import manifold3d as m3
            hmesh = m3.Manifold.hull_points(np.asarray(m.vertices, dtype=np.float32)).to_mesh()
            parts = [(hmesh.vert_properties[:, :3], hmesh.tri_verts)]
            near_convex = True
    if not near_convex:
        parts = coacd.run_coacd(cm, threshold=threshold, max_convex_hull=32)
    metrics['coacd_seconds'] = round(time.time() - t1, 2)
    metrics['coacd_parts'] = len(parts)
    metrics['hit_part_cap'] = len(parts) >= 32   # 撞上限说明还没拆够，细节可能被抹掉
    metrics['near_convex_hull_substituted'] = near_convex

    files = []
    total_part_vol = 0.0
    for i, (v, f) in enumerate(parts):
        pm = trimesh.Trimesh(np.asarray(v), np.asarray(f))
        p = out_dir / 'parts' / f'part_{i:02d}.stl'
        pm.export(p)
        files.append(str(p))
        if pm.is_watertight:
            total_part_vol += abs(pm.volume)
    metrics['parts_volume_m3'] = round(total_part_vol, 6)
    metrics['concavity'] = concavity_from_parts(total_part_vol, hull_vol)
    metrics['volume_error_vs_mesh'] = (
        round(float((total_part_vol - abs(m.volume)) / abs(m.volume)), 4)
        if m.is_watertight and abs(m.volume) > 0 else None
    )
    metrics['total_seconds'] = round(time.time() - t0, 2)

    manifest = {**metrics, 'parts': files,
                'pass': bool(metrics['coacd_parts'] >= 1 and metrics['height_m'] > 0)}
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('--height', type=float, default=0.28, help='目标高度 m（相对高度≈3.3×轮半径）')
    ap.add_argument('--out', default=None)
    ap.add_argument('--threshold', type=float, default=0.05)
    a = ap.parse_args()
    out = a.out or str(pathlib.Path('assets/processed') / pathlib.Path(a.glb).stem)
    man = process(a.glb, a.height, out, a.threshold)
    print(json.dumps(man, indent=2, ensure_ascii=False))
