"""
双胞胎障碍 v2：高度场棱柱，保证闭合流形。

上一版失败原因（b1e1488）：
  · 放样/拼接留下重合端点与内部面，非流形边 27–48 条；
  · `process_asset` 遇到非闭合网格会回退到凸包（near_convex_hull_substituted），
    背面台阶/横槽被整块填平，双胞胎的物理差异消失。

本版构造：把障碍做成"高度场棱柱"——
  对每个 (x, y) 网格点给出高度 h(x,y)，上表面三角化，下表面 z=0，
  四周用侧壁把上下边界缝起来。标准闭合棱柱，拓扑上必然流形。

  正面（x<0）：h = H·s(x)·g(y)，s 为椭球截面，g 为横向圆滑收口；
  背面（x≥0）：drop / ramp_s / ramp_l / ledge / cleft 给出不同型面。
  横向边缘保留 2% 最小高度，避免退化零面积面。

用法：
  .venv/bin/python scripts/twins.py --out runs/unseen/gate_p/<run_id>
"""
import argparse
import json
import pathlib
import sys
from collections import Counter

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
WHEEL_R = 0.08595
BACK_TYPES = ('drop', 'ramp_s', 'ramp_l', 'ledge', 'cleft')
MIN_EDGE_FRAC = 0.02


def back_length(kind, H):
    return {'drop': 0.16, 'ramp_s': H / np.tan(np.deg2rad(25)),
            'ramp_l': H / np.tan(np.deg2rad(12)),
            'ledge': 0.36, 'cleft': H / np.tan(np.deg2rad(12))}[kind]


def height_1d(kind, x, H, D):
    """脊线高度（米）。x<0 为正面，x>=0 为背面。"""
    if x < 0:
        return H * np.sqrt(max(0.0, 1.0 - (x / D) ** 2))
    if kind == 'drop':
        return H * np.exp(-x / 0.06)
    if kind == 'ramp_s':
        return max(0.0, H * (1 - x / (H / np.tan(np.deg2rad(25)))))
    if kind == 'ramp_l':
        return max(0.0, H * (1 - x / (H / np.tan(np.deg2rad(12)))))
    if kind == 'ledge':
        if x <= 0.25:
            return H
        return max(0.0, H * 0.45 * (1 - (x - 0.25) / 0.08))
    if kind == 'cleft':
        h = max(0.0, H * (1 - x / (H / np.tan(np.deg2rad(12)))))
        if 0.15 <= x <= 0.27 and h > H - 0.10:
            h = H - 0.10
        return h
    raise ValueError(kind)


def twin_solid(kind, H, W, D, seed=0, nx=72, ny=40):
    rng = np.random.default_rng(seed)
    Lback = back_length(kind, H)
    xs = np.linspace(-D, Lback, nx)
    half_w = W / 2.0
    ys = np.linspace(-half_w, half_w, ny)

    # 高度设一个下限：否则上表面会落到 z=0 与下表面重合，
    # 合并顶点后上下表面共享边，拓扑非流形。
    Hx = np.maximum(np.array([height_1d(kind, float(x), H, D) for x in xs]), 1e-3)
    if seed:
        noise = 1.0 + rng.standard_normal(nx) * (0.08 * min(H, W, 2 * D) / 2) / max(D, 1e-6)
        Hx = np.where(xs < 0, Hx * noise, Hx)

    top = np.zeros((nx, ny, 3))
    for i, x in enumerate(xs):
        g = np.sqrt(np.clip(1.0 - (ys / half_w) ** 2, MIN_EDGE_FRAC, 1.0))
        top[i, :, 0] = x
        top[i, :, 1] = ys
        top[i, :, 2] = Hx[i] * g

    n = nx * ny
    V = np.vstack([top.reshape(-1, 3), top.reshape(-1, 3) * np.array([1, 1, 0])])
    idx_top = np.arange(n).reshape(nx, ny)
    idx_bot = (np.arange(n) + n).reshape(nx, ny)

    faces = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            a, b = idx_top[i, j], idx_top[i + 1, j]
            c, d = idx_top[i + 1, j + 1], idx_top[i, j + 1]
            faces += [[a, b, c], [a, c, d]]
            a2, b2 = idx_bot[i, j], idx_bot[i + 1, j]
            c2, d2 = idx_bot[i + 1, j + 1], idx_bot[i, j + 1]
            faces += [[a2, c2, b2], [a2, d2, c2]]
    for i in range(nx - 1):
        for j, flip in ((0, False), (ny - 1, True)):
            t0, t1 = idx_top[i, j], idx_top[i + 1, j]
            b0, b1 = idx_bot[i, j], idx_bot[i + 1, j]
            quad = [t0, t1, b1, b0] if not flip else [t0, b0, b1, t1]
            faces += [[quad[0], quad[1], quad[2]], [quad[0], quad[2], quad[3]]]
    for j in range(ny - 1):
        for i, flip in ((0, True), (nx - 1, False)):
            t0, t1 = idx_top[i, j], idx_top[i, j + 1]
            b0, b1 = idx_bot[i, j], idx_bot[i, j + 1]
            quad = [t0, t1, b1, b0] if not flip else [t0, b0, b1, t1]
            faces += [[quad[0], quad[1], quad[2]], [quad[0], quad[2], quad[3]]]

    # process=False：保持我们算好的拓扑，不让 trimesh 合并顶点
    m = trimesh.Trimesh(V, np.array(faces, dtype=np.int64), process=False)
    if float(m.volume) < 0:
        m.invert()
    return m, Lback


def non_manifold_edges(m):
    e = Counter()
    for f in m.faces:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            e[tuple(sorted((int(a), int(b))))] += 1
    return sum(1 for v in e.values() if v != 2)


def descriptors(m, H):
    vs = np.asarray(m.vertices)
    back = vs[vs[:, 0] >= -1e-9]
    if len(back) == 0:
        return {}
    crest = float(back[:, 0].min())
    Lb = float(back[:, 0].max() - crest)
    zs = back[:, 2]
    return {'crest_x': round(crest, 4), 'L_back': round(Lb, 4),
            'H_max': round(float(zs.max()), 4),
            'max_step_down': round(float(H - zs.min()), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--heights', default='1.4,2.1,2.8')
    ap.add_argument('--widths', default='0.24,0.55')
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    (out / 'mesh').mkdir(parents=True, exist_ok=True)

    metas, bad = [], 0
    for seed in [int(x) for x in a.seeds.split(',')]:
        for hr in [float(x) for x in a.heights.split(',')]:
            H = hr * WHEEL_R
            for W in [float(x) for x in a.widths.split(',')]:
                D = 0.12 + 0.02 * ((seed + int(hr * 10)) % 4)
                for kind in BACK_TYPES:
                    m, Lb = twin_solid(kind, H, W, D, seed=seed)
                    nm = non_manifold_edges(m)
                    bad += (nm > 0)
                    cid = f's{seed}_h{int(hr*10)}_w{int(W*100)}_{kind}'
                    m.export(out / 'mesh' / f'{cid}.stl')
                    d = descriptors(m, H)
                    d.update({'type': kind, 'case_id': cid, 'front_seed': seed,
                              'H': round(H, 4), 'W': round(W, 4),
                              'D_front': round(D, 4), 'L_back_target': round(Lb, 4),
                              'watertight': bool(m.is_watertight),
                              'non_manifold_edges': nm,
                              'volume_m3': round(float(abs(m.volume)), 6),
                              'n_faces': int(len(m.faces))})
                    metas.append(d)
    (out / 'twins_meta.json').write_text(json.dumps(metas, indent=2, ensure_ascii=False))
    print(f'生成 {len(metas)} 个双胞胎 -> {out/"mesh"}；非流形 {bad} 个')
    for m in metas[:5]:
        print(f"  {m['case_id']:26s} 水密={m['watertight']} 非流形={m['non_manifold_edges']} "
              f"背深={m['L_back']:.3f} 体积={m['volume_m3']:.5f}")
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
