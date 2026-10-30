"""碰撞并集评价器的已知答案回归（任务书 §5.2–§5.5）。

覆盖：单盒、相邻盒内部接缝、L 形部分暴露面、凹槽、通道、刚体平移、等比缩放、分块等价性。
全部调用生产函数（box_surface_distance / exposed_faces / sample_box_surfaces），不另写一套判据。

  .venv/bin/python scripts/v7_collision_known_answers.py --out <json>
"""
import argparse, json, sys, pathlib
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import collision_occupancy_metrics as M


def case(name, ok, detail):
    return {'case': name, 'pass': bool(ok), 'detail': detail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/unseen/delivery_v7/v7_20261030_r1/verify/collision_known_answers.json')
    a = ap.parse_args()
    out = []
    P = np.array([0.0, 0.0, 0.0])

    # 1 单盒：内部点到外边界等于到最近面的距离
    boxes = [(0, 0, 0, 0, 0, 0)]
    d = M.box_surface_distance([[0.5, 0.5, 0.5]], boxes, P, 1.0)[0]
    out.append(case('single_box_center', abs(d - 0.5) < 1e-12, {'d': float(d)}))

    # 2 相邻盒内部接缝：任务书给定 (1,0.5,0.5) 与 (1.01,0.5,0.5) 都应是 0.5
    boxes = [(0, 0, 0, 0, 0, 0), (1, 1, 0, 0, 0, 0)]
    d1 = M.box_surface_distance([[1.0, 0.5, 0.5]], boxes, P, 1.0)[0]
    d2 = M.box_surface_distance([[1.01, 0.5, 0.5]], boxes, P, 1.0)[0]
    out.append(case('seam_is_not_surface',
                    abs(d1 - 0.5) < 1e-9 and abs(d2 - 0.5) < 1e-9,
                    {'d_at_1.0': float(d1), 'd_at_1.01': float(d2)}))

    # 3 部分暴露面：L 形（两个 box 只共享一部分面），共享区域应被排除、非共享区域保留
    L = [(0, 0, 0, 0, 0, 0), (1, 1, 0, 0, 0, 0), (0, 0, 1, 1, 0, 0)]
    faces = M.exposed_faces(L, P, 1.0)
    # 内部接缝只在两个盒的公共面处产生：统计暴露面数量应少于 6*len(L)
    out.append(case('partial_exposure_kept', len(faces) < 6 * len(L) and len(faces) > 0,
                    {'exposed_faces': len(faces), 'max_possible': 6 * len(L)}))

    # 4 凹槽：U 形（三块围出中间空腔），腔心到并集边界的距离应 > 0（凸包会填平 -> 距离 0）
    U = [(0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0), (1, 1, 0, 0, 1, 1)]
    d = M.box_surface_distance([[1.5, 0.5, 0.5]], U, P, 1.0)[0]
    out.append(case('groove_not_filled', abs(d - 0.5) < 1e-9, {'d': float(d)}))

    # 5 通道：中间贯通，通道两侧的表面距离对称
    # 两道墙夹出一条通道：墙在 j=0 与 j=2 的 cell，通道在 j=1
    ch = [(0, 0, 0, 0, 0, 0), (0, 0, 2, 2, 0, 0)]
    d = M.box_surface_distance([[0.5, 1.5, 0.5]], ch, P, 1.0)[0]
    out.append(case('channel_open', abs(d - 0.5) < 1e-9, {'d': float(d)}))

    # 6 刚体平移：整体平移 t，距离不变
    t = np.array([3.0, -2.0, 1.0])          # 必须是整格平移（与 cell 索引一致）
    shifted = [(i0 + 3, i1 + 3, j0 - 2, j1 - 2, k0 + 1, k1 + 1)
               for (i0, i1, j0, j1, k0, k1) in boxes]
    d = M.box_surface_distance([[1.0, 0.5, 0.5] + t], shifted, P, 1.0)[0]
    out.append(case('translation_invariant', abs(d - 0.5) < 1e-9, {'d': float(d)}))

    # 7 等比缩放：尺度 k 倍，距离同倍
    k = 1.7
    scaled = [(0, 0, 0, 0, 0, 0), (1, 1, 0, 0, 0, 0)]
    d = M.box_surface_distance([[k, 0.5 * k, 0.5 * k]], scaled, P, float(k))[0]
    out.append(case('scale_linear', abs(d - 0.5 * k) < 1e-9, {'d': float(d), 'expect': 0.5 * k}))

    # 8 分块等价性：采样点逐块求距离与一次性求距离必须完全一致
    rng = np.random.default_rng(0)
    pts = rng.uniform(-0.5, 2.5, size=(5000, 3))
    full = M.box_surface_distance(pts, boxes, P, 1.0)
    parts = np.concatenate([M.box_surface_distance(pts[i:i + 777], boxes, P, 1.0)
                            for i in range(0, len(pts), 777)])
    out.append(case('block_equivalence', bool(np.array_equal(full, parts)),
                    {'maxdiff': float(np.max(np.abs(full - parts)))}))

    rep = {'schema': 'collision-known-answers/v7-r1',
           'n': len(out), 'n_pass': sum(1 for c in out if c['pass']), 'cases': out,
           'verdict': 'PASS' if all(c['pass'] for c in out) else 'FAIL'}
    p = ROOT / a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'verdict': rep['verdict'], 'n_pass': rep['n_pass'], 'n': rep['n'],
                      'fails': [c['case'] for c in out if not c['pass']]}, ensure_ascii=False))
    return 0 if rep['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
