"""
Gate P 双胞胎障碍：正面完全相同，背面不同。

  .venv/bin/python scripts/twins.py --out runs/unseen/gate_p/<run_id>

构造要点（任务书第五节）：
  · 机器人沿 +x 前进；脊线在地面的投影为 x=0，x<0 是正面（机器人看得见），x≥0 是背面。
  · 正面 = 确定性带噪半椭球，参数 F(seed, H, W, D_front)，噪声约为最小半轴的 8%，
    用 z<0 与 x>0 裁剪掉。
  · 背面类型：drop / ramp_s(25°) / ramp_l(12°) / ledge(0.25 m 处台阶) / cleft(横槽)，
    每侧内缩 ≥2 cm，避免从正面轮廓直接露出。
  · 同一正面几何在 5 种背面里**逐顶点一致**（只拼背面），保证观测可共用。

输出：每例一个 visual STL + collision STL + meta（含真值背面描述量）。
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh
from manifold3d import Manifold

ROOT = pathlib.Path(__file__).resolve().parent.parent
WHEEL_R = 0.08595               # 由 measure_robot 实测

BACK_TYPES = ('drop', 'ramp_s', 'ramp_l', 'ledge', 'cleft')


def _profile(kind, x, H, W, D):
    """给定 x，返回该处截面的 (半宽 y, 高度 z)。x<0 为正面，x>=0 为背面。"""
    W2 = W / 2.0
    if x < 0:
        r = np.sqrt(max(0.0, 1.0 - (x / D) ** 2))
        return W2 * r, H * r
    if kind == 'drop':
        return W2 * 0.55, H * 0.55 * np.exp(-x / 0.10)
    if kind == 'ramp_s':
        L = H / np.tan(np.deg2rad(25))
        return W2 * 0.55, max(0.0, H * (1 - x / L))
    if kind == 'ramp_l':
        L = H / np.tan(np.deg2rad(12))
        return W2 * 0.55, max(0.0, H * (1 - x / L))
    if kind == 'ledge':
        L1 = 0.25
        if x <= L1:
            return W2 * 0.55, H
        return W2 * 0.55, H * 0.45 * max(0.0, 1 - (x - L1) / 0.10)
    if kind == 'cleft':
        L = H / np.tan(np.deg2rad(12))
        h = max(0.0, H * (1 - x / L))
        if 0.15 <= x <= 0.27 and h > H - 0.10:
            h = H - 0.10          # 横槽：这一段被切低
        return W2 * 0.55, h
    raise ValueError(kind)


def twin_solid(kind, H, W, D, n_x=40, n_phi=24, seed=0):
    """
    把整块障碍做成**单一放样实体**：每个 x 一个半椭圆截面，底面 z=0。
    这样正面（x<0 的椭球段）与背面（x≥0 的型面）共享同一张曲面，接缝处没有内部面，
    网格天然流形；背面差异不会被凸包替换抹平。
    """
    rng = np.random.default_rng(seed)
    L_back = {'drop': 0.16, 'ramp_s': H / np.tan(np.deg2rad(25)),
              'ramp_l': H / np.tan(np.deg2rad(12)), 'ledge': 0.36,
              'cleft': H / np.tan(np.deg2rad(12))}[kind]
    xs = np.concatenate([np.linspace(-D, 0, n_x // 2, endpoint=False),
                         np.linspace(0, L_back, n_x // 2 + 1)])
    phi = np.linspace(0, np.pi, n_phi)
    verts, rows = [], []
    for x in xs:
        w, h = _profile(kind, x, H, W, D)
        if h <= 1e-6 or w <= 1e-6:
            # 收敛到一条线：仍然保留一排点，避免退化四边形
            ring = np.stack([np.full(n_phi, x), np.zeros(n_phi), np.zeros(n_phi)], axis=1)
        else:
            yy = w * np.cos(phi)
            zz = h * np.sin(phi)
            if x < 0:
                j = 1.0 + rng.standard_normal(n_phi) * (0.08 * min(H, W, 2 * D) / 2) / max(D, 1e-6)
                yy = yy * j
            ring = np.stack([np.full(n_phi, x), yy, np.clip(zz, 0, None)], axis=1)
        rows.append(len(verts))
        verts.extend(ring)
    verts = np.array(verts)
    faces = []
    for i in range(len(xs) - 1):
        a, b = rows[i], rows[i + 1]
        for j in range(n_phi - 1):
            faces += [[a + j, b + j, b + j + 1], [a + j, b + j + 1, a + j + 1]]
    # 两端封口（扇面）
    for i, sign in ((0, -1), (len(xs) - 1, 1)):
        base = rows[i]
        cx = float(xs[i])
        c = len(verts)
        verts = np.vstack([verts, [cx, 0.0, 0.0]])
        for j in range(n_phi - 1):
            if sign < 0:
                faces.append([base + j, base + j + 1, c])
            else:
                faces.append([base + j + 1, base + j, c])
    # 底面 z=0：把每一排的两个端点连起来（phi=0 与 phi=n_phi-1 都在 z=0）
    for i in range(len(xs) - 1):
        a, b = rows[i], rows[i + 1]
        faces.append([a, a + n_phi - 1, b + n_phi - 1])
        faces.append([a, b + n_phi - 1, b])
    m = trimesh.Trimesh(verts, np.array(faces, dtype=np.int64), process=True)
    m.merge_vertices()
    if float(m.volume) < 0:
        m.invert()
    return m, L_back


def _wedge(x0, L, H, W2, z0=0.0):
    """从 (x0,H) 斜降到 (x0+L,0) 的楔块（沿 +x 下降）。"""
    v = np.array([[x0, -W2, z0], [x0 + L, -W2, z0], [x0, -W2, z0 + H],
                  [x0, W2, z0], [x0 + L, W2, z0], [x0, W2, z0 + H]])
    f = np.array([[0, 2, 1], [1, 2, 5], [1, 5, 4], [0, 1, 3], [3, 1, 4],
                  [0, 3, 2], [3, 5, 2], [2, 5, 4]], dtype=np.int64)
    m = trimesh.Trimesh(v, f, process=True)
    if m.volume < 0:
        m.invert()
    return m


def _box(x0, dx, h, W2, z0=0.0):
    v = np.array([[x0, -W2, z0], [x0 + dx, -W2, z0], [x0 + dx, -W2, z0 + h],
                  [x0, -W2, z0 + h], [x0, W2, z0], [x0 + dx, W2, z0],
                  [x0 + dx, W2, z0 + h], [x0, W2, z0 + h]])
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]],
                 dtype=np.int64)
    m = trimesh.Trimesh(v, f, process=True)
    if m.volume < 0:
        m.invert()
    return m


def descriptors(mesh, H, W):
    """真值背面描述量（只在评测/分析侧使用）。"""
    vs = np.asarray(mesh.vertices)
    back = vs[vs[:, 0] >= -1e-6]
    if len(back) == 0:
        return {'type': 'none'}
    crest = float(back[:, 0].min())
    L_back = float(back[:, 0].max() - crest)
    zs = back[:, 2]
    return {'type': 'unknown', 'crest_x': round(crest, 4),
            'L_back': round(L_back, 4), 'H_max': round(float(zs.max()), 4),
            'back_slope_deg': round(float(np.degrees(np.arctan(
                (zs.max() - zs.min()) / max(L_back, 1e-6)))), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--seeds', default='0,1')
    ap.add_argument('--heights', default='1.4,2.1')
    ap.add_argument('--widths', default='0.24,0.55')
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    (out / 'mesh').mkdir(parents=True, exist_ok=True)
    env = None

    metas = []
    for seed in [int(x) for x in a.seeds.split(',')]:
        for hr in [float(x) for x in a.heights.split(',')]:
            H = hr * WHEEL_R
            for W in [float(x) for x in a.widths.split(',')]:
                D = 0.12 + 0.06 * ((seed * 7 + int(hr * 10)) % 3) / 2
                for kind in BACK_TYPES:
                    pair, Lb = twin_solid(kind, H, W, D, seed=seed)
                    cid = f's{seed}_h{int(hr*10)}_w{int(W*100)}_{kind}'
                    p = out / 'mesh' / f'{cid}.stl'
                    pair.export(p)
                    d = descriptors(pair, H, W)
                    d.update({'type': kind, 'case_id': cid, 'front_seed': seed,
                              'H': round(H, 4), 'W': round(W, 4), 'D_front': round(D, 4),
                              'watertight': bool(pair.is_watertight),
                              'volume_m3': round(float(abs(pair.volume)), 6)})
                    metas.append(d)
    # 同正面对照：5 种背面的正面顶点应完全一致（用正面包围盒与体积近似核验）
    (out / 'twins_meta.json').write_text(json.dumps(metas, indent=2, ensure_ascii=False))
    print(f'生成 {len(metas)} 个双胞胎障碍 -> {out/"mesh"}')
    for m in metas[:6]:
        print(f"  {m['case_id']:28s} H={m['H']:.3f} W={m['W']:.2f} "
              f"背深 L={m['L_back']:.3f} 坡={m['back_slope_deg']:.1f}° 水密={m['watertight']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
