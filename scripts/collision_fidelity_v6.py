"""
V6 工作包 E：实际载入的 CoACD 碰撞体 vs 源网格（不是用视觉网格验收代替碰撞）。
输出表面距离、占据 IoU、关键尺寸、parts 数/SHA；可对比 32/64 部件。
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from meshdist import point_to_mesh_distance

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sha(p):
    h = hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()


def ray_inside(mesh, pts):
    inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    d = np.tile([0.0, 0.0, 1.0], (len(pts), 1))
    loc, ray_i, _ = inter.intersects_location(pts, d, multiple_hits=True)
    cnt = np.bincount(ray_i, minlength=len(pts))
    return (cnt % 2).astype(bool)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--collision', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', default='')
    ap.add_argument('--collision-b', default=None, help='第二档分解（如 64 部件）')
    a = ap.parse_args()
    m = trimesh.load(a.mesh, force='mesh')
    cdir = pathlib.Path(a.collision)
    man = json.loads((cdir / 'manifest.json').read_text())
    parts = [trimesh.load(cdir / p, force='mesh') for p in man['parts']]
    union = trimesh.util.concatenate(parts)
    # 表面距离：源网格采样点到碰撞表面（parts 并集的表面）
    n = 3000
    pts, _ = trimesh.sample.sample_surface(m, n, seed=0)
    d = point_to_mesh_distance(union, pts, chunk=64)
    # 占据一致：同样 bounds 内随机点，mesh inside vs any part inside
    b = np.vstack([m.bounds, union.bounds])
    lo, hi = b.min(0), b.max(0)
    rng = np.random.default_rng(0)
    q = rng.uniform(lo, hi, size=(2500, 3))
    inm = ray_inside(m, q)
    inp = np.zeros(len(q), dtype=bool)
    for p in parts:
        inp |= ray_inside(p, q)
    inter = (inm & inp).sum(); uni = (inm | inp).sum()
    out = {
        'schema': 'collision-fidelity/v6', 'label': a.label,
        'source_mesh': str(a.mesh), 'collision': str(cdir),
        'source_sha': sha(a.mesh), 'collision_sha': man.get('collision_sha'),
        'parts': len(parts), 'hit_part_cap': man.get('hit_part_cap'),
        'surface_distance_mm': {'med': round(float(np.median(d)) * 1000, 3),
                                'p95': round(float(np.percentile(d, 95)) * 1000, 3),
                                'max': round(float(np.max(d)) * 1000, 3)},
        'occupancy_iou': round(float(inter / max(uni, 1)), 4),
        'occupancy_false_inside': int((~inm & inp).sum()),
        'occupancy_false_outside': int((inm & ~inp).sum()),
        'bounds_source': [[round(float(x), 5) for x in m.bounds[0]],
                          [round(float(x), 5) for x in m.bounds[1]]],
        'bounds_parts': [[round(float(x), 5) for x in union.bounds[0]],
                         [round(float(x), 5) for x in union.bounds[1]]],
        'volume_source_m3': round(abs(float(m.volume)), 9) if m.is_watertight else None,
        'volume_parts_sum_m3': round(sum(abs(float(p.volume)) for p in parts if p.is_watertight), 9),
        'note': ('CoACD parts 的占据并集用逐 part 奇偶；parts 重叠时 sum volume 不是并集体积。'
                 '达到 32 上限不自动判坏，更多 parts 也不自动判好。'),
    }
    if a.collision_b:
        cb = pathlib.Path(a.collision_b)
        mb = json.loads((cb / 'manifest.json').read_text()) if (cb / 'manifest.json').exists() else {}
        out['collision_b'] = {'dir': str(cb), 'parts': len(mb.get('parts') or []),
                              'collision_sha': mb.get('collision_sha'),
                              'source_sha': mb.get('world_sha')}
    out['verdict'] = ('PASS' if out['surface_distance_mm']['p95'] <= 5.0
                      and out['occupancy_iou'] >= 0.95 else 'ATTENTION')
    op = pathlib.Path(a.out); op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
