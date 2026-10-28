"""
B3 标定件：最大平面不在底部，正面有可辨识缺口。

要求（任务书 B3 / 4.2d）：
  · 真正的窄底 / 圆底：底面面积远小于侧面；
  · 最大平面在侧面（倾斜大面）；
  · 正面（-x 侧）有缺口，可判断哪面是正面；
  · 流形、水密。
验收不看注释：从导出网格算**共面区域面积**，输出底部面积与最大其他平面面积。

  .venv/bin/python scripts/make_calibration_object.py --out cases/unseen_v1/calibration_asym.stl
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh


def _prism(profile_xz, depth_y):
    """把 x-z 平面上的凸多边形沿 y 挤出成闭合棱柱（不依赖布尔运算）。"""
    pts = np.asarray(profile_xz, dtype=np.float64)
    n = len(pts)
    hy = depth_y / 2.0
    V = np.vstack([np.column_stack([pts[:, 0], np.full(n, -hy), pts[:, 1]]),
                   np.column_stack([pts[:, 0], np.full(n, hy), pts[:, 1]])])
    F = []
    # 两个端盖（扇形三角化，凸多边形安全）
    for i in range(1, n - 1):
        F.append([0, i + 1, i])                    # y=-hy 侧
        F.append([n, n + i, n + i + 1])            # y=+hy 侧
    # 侧壁
    for i in range(n):
        j = (i + 1) % n
        F += [[i, j, n + j], [i, n + j, n + i]]
    m = trimesh.Trimesh(V, np.array(F, dtype=np.int64), process=False)
    if float(m.volume) < 0:
        m.invert()
    return m


def solid():
    """
    窄底三角棱柱 + 正面凸块（可辨识正面的不对称特征）。
      · 底面：0.03 m 宽的窄边（面积 0.03 x 0.10 = 0.003 m2）
      · 最大平面：+x 侧的大斜面（约 0.232 x 0.10 = 0.023 m2）
    这样"最大平面在底部"不成立，生成器无法靠把大平面压到底部来假装直立。
    """
    main = _prism([(-0.015, 0.00), (0.015, 0.00), (-0.060, 0.22)], 0.10)
    # 正面特征：在 -x 面的下半部分凸出一块（只有一侧），形成可辨识台阶
    step = _prism([(-0.075, 0.03), (-0.048, 0.03), (-0.062, 0.09)], 0.045)
    step.apply_translation([0.0, -0.022, 0.0])
    m = trimesh.util.concatenate([main, step])
    m.apply_translation([0, 0, -m.bounds[0][2]])
    return m


def coplanar_report(m, tol_deg=2.0, tol_mm=0.5):
    """
    按法向聚类面片，统计每个"共面区域"的面积。
    输出底部面积、最大其他平面面积及其法向/位置。
    """
    n = m.face_normals
    a = m.area_faces
    c = m.triangles_center
    used = np.zeros(len(n), bool)
    groups = []
    for i in range(len(n)):
        if used[i]:
            continue
        cosang = np.clip(n @ n[i], -1, 1)
        same_dir = np.degrees(np.arccos(cosang)) < tol_deg
        d_i = float(c[i] @ n[i])
        dist = np.abs(c @ n[i] - d_i)
        same = same_dir & (dist < tol_mm / 1000.0) & ~used
        used |= same
        groups.append({'area': float(a[same].sum()), 'normal': n[i].tolist(),
                       'point': c[same].mean(axis=0).tolist()})
    groups.sort(key=lambda g: -g['area'])
    bottom = [g for g in groups
              if g['normal'][2] < -0.98 and abs(g['point'][2]) < 0.002]
    bottom_area = max((g['area'] for g in bottom), default=0.0)
    others = [g for g in groups if g not in bottom]
    biggest_other = others[0] if others else {'area': 0.0, 'normal': [0, 0, 0],
                                              'point': [0, 0, 0]}
    return {'bottom_area_m2': round(bottom_area, 6),
            'largest_other_area_m2': round(biggest_other['area'], 6),
            'largest_other_normal': [round(x, 3) for x in biggest_other['normal']],
            'largest_other_point': [round(x, 4) for x in biggest_other['point']],
            'ratio_other_over_bottom': (round(biggest_other['area'] / bottom_area, 2)
                                        if bottom_area > 1e-9 else None),
            'n_coplanar_groups': len(groups),
            'top5': [{'area': round(g['area'], 6),
                      'normal': [round(x, 2) for x in g['normal']]} for g in groups[:5]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--report', default=None)
    a = ap.parse_args()
    m = solid()
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
    m.export(p)
    rep = coplanar_report(m)
    rep.update({'extents': [round(float(x), 4) for x in m.extents],
                'volume_m3': round(abs(float(m.volume)), 8),
                'watertight': bool(m.is_watertight),
                'n_faces': int(len(m.faces)),
                'max_plane_not_on_bottom': bool(
                    rep['largest_other_area_m2'] > rep['bottom_area_m2'])})
    if a.report:
        pathlib.Path(a.report).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print(json.dumps(rep, ensure_ascii=False))
    return 0 if rep['max_plane_not_on_bottom'] else 1


if __name__ == '__main__':
    sys.exit(main())
