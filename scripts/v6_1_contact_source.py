"""
V6.1：接触来源映射（E5）。

把一次执行回合里记录的接触位置，分类到「接触的是哪一类表面」：

  observed_face      观测到的可见面（距 visible_points <= 阈值）
  parent_hidden      父候选的隐藏面（在父网格实体内部/表面，且不在可见面附近）
  collision_added    碰撞体新增区域（在碰撞并集内部，但不在父实体内部）

意义：**接触到隐藏面本身，不等于生成方法带来了额外价值**。只有当隐藏面的差异
改变了决策、且决策在同真值下更好时，才算收益。

  .venv/bin/python scripts/v6_1_contact_source.py \
      --trajectory <traj.json> --visible <observation/visible_points.npy> \
      --parent-world <dir> --collision <box dir> --out <json>
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fuse_observed as FZ


def nearest(points, ref, chunk=512):
    out = np.full(len(points), np.inf)
    for i in range(0, len(points), chunk):
        d = np.linalg.norm(points[i:i + chunk, None, :] - ref[None, :, :], axis=2).min(axis=1)
        out[i:i + chunk] = d
    return out


def inside_mesh(mesh, pts):
    if len(pts) == 0:
        return np.zeros(0, dtype=bool)
    inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    d = np.tile(np.array([0.0, 0.0, 1.0]), (len(pts), 1))
    _, ray_i, _ = inter.intersects_location(pts, d, multiple_hits=True)
    cnt = np.bincount(ray_i, minlength=len(pts))
    return (cnt % 2).astype(bool)


def inside_boxes(boxes, origin, pitch, pts):
    out = np.zeros(len(pts), dtype=bool)
    for (i0, i1, j0, j1, k0, k1) in boxes:
        lo = origin + np.array([i0, j0, k0]) * pitch
        hi = origin + np.array([i1 + 1, j1 + 1, k1 + 1]) * pitch
        out |= ((pts >= lo) & (pts < hi)).all(axis=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trajectory', required=True)
    ap.add_argument('--visible', required=True)
    ap.add_argument('--parent-world', required=True)
    ap.add_argument('--collision', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--vis-tol-mm', type=float, default=15.0)
    ap.add_argument('--obstacle-body', default='obstacle0',
                    help='只统计与障碍 body 的接触；地面接触不算')
    a = ap.parse_args()
    traj = json.loads(pathlib.Path(a.trajectory).read_text())
    frames = traj.get('frames') or []
    pts = []
    n_all = 0
    for f in frames:
        for c in (f.get('contacts') or []):
            n_all += 1
            bodies = {c.get('g1_body'), c.get('g2_body')}
            if a.obstacle_body not in bodies:
                continue                      # 地面/机身自接触不算障碍接触
            p = c.get('pos') or c.get('position')
            if p and len(p) == 3:
                pts.append([float(x) for x in p])
    pts = np.asarray(pts, dtype=float) if pts else np.zeros((0, 3))
    rep = {'schema': 'contact-source/v6_1', 'trajectory': a.trajectory,
           'option': traj.get('option'), 'seed': traj.get('seed'),
           'n_contact_points': int(len(pts)), 'n_contacts_all': n_all,
           'obstacle_body': a.obstacle_body}
    if len(pts) == 0:
        rep['note'] = '该回合没有与障碍的接触点（可能绕开了，或只与地面接触）'
        rep['counts'] = {}
        pathlib.Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(json.dumps({'n': 0}, ensure_ascii=False))
        return 0
    vis = np.load(a.visible)
    parent = FZ._load_mesh(pathlib.Path(a.parent_world) / 'body.stl')
    man = json.loads((pathlib.Path(a.collision) / 'manifest.json').read_text())
    boxes = man.get('boxes'); org = np.asarray(man['grid_origin'], float); pitch = float(man['pitch_m'])
    d_vis = nearest(pts, vis)
    near_vis = d_vis * 1000 <= a.vis_tol_mm
    in_parent = inside_mesh(parent, pts)
    in_coll = inside_boxes(boxes, org, pitch, pts) if boxes else np.zeros(len(pts), bool)
    cls = np.array(['collision_added'] * len(pts), dtype=object)
    cls[in_parent] = 'parent_hidden'
    cls[near_vis] = 'observed_face'
    counts = {k: int((cls == k).sum()) for k in ('observed_face', 'parent_hidden', 'collision_added')}
    rep.update({'counts': counts,
                'fractions': {k: round(v / len(pts), 4) for k, v in counts.items()},
                'vis_tol_mm': a.vis_tol_mm,
                'd_vis_mm': {'med': round(float(np.median(d_vis)) * 1000, 3),
                             'p95': round(float(np.percentile(d_vis, 95)) * 1000, 3)},
                'n_in_parent': int(in_parent.sum()), 'n_in_collision': int(in_coll.sum()),
                'in_parent_but_not_collision': int((in_parent & ~in_coll).sum()),
                'note': ('接触来源只是归因工具：接触到隐藏面不等于生成方法带来收益；'
                         '需要与同真值下的决策差异一起看。')})
    pathlib.Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'counts': counts, 'n': int(len(pts))}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
