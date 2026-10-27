"""
生成用于"朝向来源"判定的不对称标定物。

设计要求（任务书 4.2d）：
  · 最大的平面**不在底部**：底面窄（0.12 m），最大面是倾斜的侧面；
  · 正面（朝机器人 +x 的一侧）有一个明显缺口，可据此判定哪一面是正面；
  · 底面做成**窄边**而不是大平面，避免"按形状摆正"时把大平面压到底部。

  .venv/bin/python scripts/make_calibration_object.py --out cases/unseen_v1/calibration_asym.stl
"""
import argparse
import pathlib
import sys
import numpy as np
import trimesh


def prism(h_fn, x0, x1, y0, y1, nx=60, ny=40, zmin=1e-3):
    """高度场棱柱：上表面 h(x,y)、下表面 z=0、四周封壁。闭合流形。"""
    xs = np.linspace(x0, x1, nx)
    ys = np.linspace(y0, y1, ny)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    Z = np.maximum(h_fn(X, Y), zmin)
    top = np.stack([X, Y, Z], axis=-1)
    n = nx * ny
    V = np.vstack([top.reshape(-1, 3), top.reshape(-1, 3) * np.array([1, 1, 0])])
    it = np.arange(n).reshape(nx, ny)
    ib = (np.arange(n) + n).reshape(nx, ny)
    F = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            a, b, c, d = it[i, j], it[i+1, j], it[i+1, j+1], it[i, j+1]
            F += [[a, b, c], [a, c, d]]
            a2, b2, c2, d2 = ib[i, j], ib[i+1, j], ib[i+1, j+1], ib[i, j+1]
            F += [[a2, c2, b2], [a2, d2, c2]]
    for i in range(nx - 1):
        for j, flip in ((0, False), (ny - 1, True)):
            t0, t1 = it[i, j], it[i+1, j]
            b0, b1 = ib[i, j], ib[i+1, j]
            q = [t0, t1, b1, b0] if not flip else [t0, b0, b1, t1]
            F += [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]
    for j in range(ny - 1):
        for i, flip in ((0, True), (nx - 1, False)):
            t0, t1 = it[i, j], it[i, j+1]
            b0, b1 = ib[i, j], ib[i, j+1]
            q = [t0, t1, b1, b0] if not flip else [t0, b0, b1, t1]
            F += [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]
    m = trimesh.Trimesh(V, np.array(F, dtype=np.int64), process=False)
    if float(m.volume) < 0:
        m.invert()
    return m


def height(X, Y):
    """沿 +y 抬升的斜面（最大面），正面 (−x) 一侧挖一个缺口。"""
    h = 0.02 + 0.14 * (Y - Y.min()) / (Y.max() - Y.min())
    # 正面特征：靠 -x 的一端、靠 +y 的一个方形缺口
    notch = (X < X.min() + 0.06) & (Y > Y.max() - 0.05)
    h = np.where(notch, 0.06, h)
    # 底部收窄：让底面比斜面小
    taper = 1.0 - 0.55 * np.clip((np.abs(X - X.mean()) - 0.06) / 0.04, 0, 1)
    return h * taper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    m = prism(height, -0.10, 0.10, -0.06, 0.06)
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
    m.export(p)
    print(f'外接尺寸 {np.round(m.extents,3)} 体积 {abs(m.volume):.6f} '
          f'水密 {m.is_watertight} 面数 {len(m.faces)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
