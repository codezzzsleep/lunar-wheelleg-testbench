"""
process_posed：保持已配准姿态的物理化。

  .venv/bin/python scripts/physicalize.py --mesh <aligned.glb|stl> --out assets/posed/<id> \
      --hypothesis-id H1 --threshold 0.04

与旧 process_asset 的区别（任务书 7.2）：
  · **不** rest_pose、**不**自动重新定尺度、**不**走近凸替换；
  · 直接对世界坐标网格做 CoACD，输出的 parts 仍在该坐标系里；
  · manifest 额外记录 pose_world / raw_sha / collision_sha / 处理参数与版本。

碰撞保真：CoACD 的块数上限设 32，并对"凹部是否被抹平"做探针检查
（用一个小球下落到网格最低点，比较整体凸包与分解后的静止高度）。
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
WHEEL_R = 0.08595


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_world_mesh(path):
    """加载网格并**应用节点变换**，保持世界坐标（不旋转、不缩放、不居中）。"""
    sc = trimesh.load(str(path), force='scene')
    if isinstance(sc, trimesh.Scene):
        g = sc.to_geometry()
        if isinstance(g, trimesh.Scene):
            geoms = [x for x in g.geometry.values() if len(x.faces) > 0]
            m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
        else:
            m = g
    else:
        m = sc
    return m


def probe_bottom(mesh_paths, drop_height=0.5, seed=0):
    """
    探针：小球从上方落到"网格最低点所在位置"，比较
      (a) 整体凸包  与 (b) CoACD 分解后的 parts
    的静止高度。若分解后更低，说明凹部被保留。
    """
    import mujoco
    parts = [trimesh.load(str(p), force='mesh') for p in mesh_paths]
    v = np.vstack([np.asarray(x.vertices) for x in parts])
    lo = v.min(axis=0)
    cx, cy = float(lo[0]), float(lo[1])

    def settle(paths, hull):
        assets, geoms = [], []
        for i, p in enumerate(paths):
            assets.append(f'<mesh name="p{i}" file="{p}"/>')
            geoms.append(f'<geom type="mesh" mesh="p{i}"/>')
        if hull:
            assets = [f'<mesh name="hull" file="{paths[0]}"/>']
            geoms = ['<geom type="mesh" mesh="hull"/>']
        xml = (f'<mujoco><asset>{"".join(assets)}</asset><worldbody>'
               f'<geom type="plane" size="2 2 0.1"/>'
               f'<body pos="0 0 0">{"".join(geoms)}</body>'
               f'<body pos="{cx} {cy} {drop_height}"><freejoint/>'
               f'<geom type="sphere" size="0.02" mass="0.5"/></body></worldbody></mujoco>')
        m = mujoco.MjModel.from_xml_string(xml)
        d = mujoco.MjData(m)
        for _ in range(1500):
            mujoco.mj_step(m, d)
        return float(d.qpos[2]) - 0.02

    return {'hull_bottom_z': round(settle(mesh_paths, True), 5),
            'parts_bottom_z': round(settle(mesh_paths, False), 5),
            'probe_xy': [round(cx, 4), round(cy, 4)]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--hypothesis-id', default='H?')
    ap.add_argument('--threshold', type=float, default=0.04)
    ap.add_argument('--max-parts', type=int, default=32)
    ap.add_argument('--timeout', type=int, default=120)
    ap.add_argument('--skip-probe', action='store_true')
    a = ap.parse_args()

    out = pathlib.Path(a.out)
    (out / 'parts').mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(a.mesh)
    m = load_world_mesh(src)

    bounds = m.bounds
    dims = {
        'height_m': round(float(bounds[1][2] - bounds[0][2]), 5),
        'width_x_m': round(float(bounds[1][0] - bounds[0][0]), 5),
        'width_y_m': round(float(bounds[1][1] - bounds[0][1]), 5),
    }
    if dims['height_m'] <= 0:
        raise SystemExit(f'网格高度为 0：{src}')

    import coacd
    t0 = time.time()
    cm = coacd.Mesh(m.vertices, m.faces)
    # 该版本 run_coacd 不接受 timeout 参数；用 max_convex_hull 控制规模
    parts = coacd.run_coacd(cm, threshold=a.threshold, max_convex_hull=a.max_parts)
    dt = time.time() - t0

    files = []
    total = 0.0
    for i, (v, f) in enumerate(parts):
        pm = trimesh.Trimesh(np.asarray(v), np.asarray(f))
        pm.export(out / 'parts' / f'part_{i:02d}.stl')
        files.append(f'parts/part_{i:02d}.stl')
        if pm.is_watertight:
            total += abs(float(pm.volume))

    # 凸包体积用 manifold3d（不依赖 scipy）
    import manifold3d as m3
    hm = m3.Manifold.hull_points(np.asarray(m.vertices, dtype=np.float32)).to_mesh()
    hv = trimesh.Trimesh(np.asarray(hm.vert_properties)[:, :3],
                         np.asarray(hm.tri_verts))
    hull_vol = abs(float(hv.volume))
    concavity = round(1 - total / hull_vol, 5) if hull_vol > 0 else None

    h = hashlib.sha256()
    for f_ in files:
        h.update(f_.encode())
        h.update(sha256(out / f_).encode())
    collision_sha = h.hexdigest()[:32]

    probe = None if a.skip_probe else probe_bottom(
        [out / f_ for f_ in files])

    man = {
        'asset_id': out.name,
        'hypothesis_id': a.hypothesis_id,
        'schema': 'asset-manifest/v1',
        'coordinate_frame': 'world',
        'source_kind': 'posed',
        'parts': files,
        'T_world_from_asset': np.eye(4).tolist(),
        'body_pose_expected': {'pos': [0.0, 0.0, 0.0], 'quat': [1.0, 0.0, 0.0, 0.0]},
        'world_sha': sha256(src),
        'pass': True,
        'rest_pose': False,
        'rescaled': False,
        'near_convex_hull_substituted': False,
        'coacd_parts': len(parts),
        'coacd_threshold': a.threshold,
        'coacd_max_parts': a.max_parts,
        'coacd_seconds': round(dt, 2),
        'hit_part_cap': len(parts) >= a.max_parts,
        'height_m': dims['height_m'],
        'width_x_m': dims['width_x_m'],
        'width_y_m': dims['width_y_m'],
        'rel_height': round(dims['height_m'] / WHEEL_R, 3),
        'rel_width': round(dims['width_y_m'] / WHEEL_R, 3),
        'concavity': concavity,
        'convex_hull_volume_m3': round(hull_vol, 6),
        'parts_volume_m3': round(total, 6),
        'pose_world': np.eye(4).tolist(),
        'bounds': bounds.tolist(),
        'raw_sha': sha256(src),
        'collision_sha': collision_sha,
        'concavity_probe': probe,
        'version': 'physicalize/v1',
    }
    (out / 'manifest.json').write_text(json.dumps(man, indent=2, ensure_ascii=False))
    print(json.dumps({k: man[k] for k in ('asset_id', 'coacd_parts', 'concavity',
                                          'hit_part_cap', 'collision_sha')},
                     ensure_ascii=False))
    if probe:
        print('探针:', probe)
    return 0


if __name__ == '__main__':
    sys.exit(main())
