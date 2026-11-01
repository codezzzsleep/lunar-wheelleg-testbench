"""程序化岩石真值池：免费构造新几何，不依赖付费生成，也不需要 scipy。

每块石头用**确定性种子**生成，且**水密**（从球面拓扑出发，不做布尔运算）：

  1. 细分球面（面数可控）；
  2. 低频径向噪声 → 不规则整体形状；
  3. 随机平面“削面”：把越过平面的顶点投影到平面上 → 平整断口与尖棱（非凸）；
  4. 高频小幅噪声 → 风化粗糙面；
  5. 逐面颜色 = 程序化纹理（并另存 texture.png），几何只用于碰撞。

输出 `assets/procedural_rocks/<id>/{body.stl, meta.json, texture.png}` 与 `index.json`。
"""
import argparse
import hashlib
import json
import pathlib

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_FACES = 200_000


def smooth_noise(v, rng, k=6, scale=0.35):
    """低频噪声：若干随机方向的余弦叠加（只依赖 numpy）。"""
    dirs = rng.normal(size=(k, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    amps = rng.uniform(0.5, 1.0, size=k)
    return (np.cos(v @ dirs.T * np.pi) * amps).sum(axis=1) * scale


def make_rock(seed, target_h, footprint=0.36, subdiv=4):
    rng = np.random.default_rng(seed)
    m = trimesh.creation.icosphere(subdivisions=subdiv, radius=1.0)
    v = m.vertices.copy()
    n = v / np.linalg.norm(v, axis=1, keepdims=True)

    # 1 低频起伏
    disp = smooth_noise(n, rng, k=int(rng.integers(5, 9)), scale=float(rng.uniform(0.12, 0.22)))
    r = 1.0 + disp
    v = n * r[:, None]

    # 2 削面：产生断口与尖棱
    for _ in range(int(rng.integers(3, 7))):
        nrm = rng.normal(size=3); nrm /= np.linalg.norm(nrm)
        off = float(rng.uniform(-0.80, -0.35))       # 更深的削面，产生明显断口与棱
        d = v @ nrm
        mask = d > -off
        v[mask] = v[mask] - np.outer(d[mask] + off, nrm)

    # 3 高频风化噪声
    v = v * (1.0 + rng.normal(scale=float(rng.uniform(0.004, 0.010)), size=(len(v), 1)))

    m = trimesh.Trimesh(vertices=v, faces=m.faces, process=True)
    m.fix_normals()

    # 4 各向异性缩放 + 落地：高度严格等于目标高度，避免被压成薄片
    ex, ey = rng.uniform(0.75, 1.05, size=2)
    z0 = float(m.bounds[0][2]); z1 = float(m.bounds[1][2])
    sx = footprint / 2.0 * ex
    sy = footprint / 2.0 * ey
    sz = target_h / max(1e-6, (z1 - z0))
    m.apply_scale([sx, sy, sz])
    m.apply_translation(-m.bounds.mean(axis=0))
    m.apply_translation([0, 0, -m.bounds[0][2] - 0.002])
    return m


def procedural_texture(m, rng, size=256):
    """程序化纹理：低频斑块 + 高频颗粒。返回 (H,W,3) uint8。"""
    yy, xx = np.mgrid[0:size, 0:size] / size
    base = 0.42 + 0.16 * np.sin(6.283 * (xx * rng.uniform(2, 5) + yy * rng.uniform(2, 5)))
    grain = rng.normal(scale=0.06, size=(size, size))
    patch = rng.normal(scale=0.10, size=(8, 8))
    patch = np.kron(patch, np.ones((size // 8, size // 8)))
    v = np.clip(base + grain + patch, 0.15, 0.9)
    tint = rng.uniform([0.75, 0.7, 0.65], [1.0, 0.95, 0.9], size=3)
    img = np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1)
    return (img * 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=24)
    ap.add_argument('--seed0', type=int, default=9001)
    ap.add_argument('--out', default='assets/procedural_rocks')
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed0)
    index = {'schema': 'procedural-rock-pool/v1', 'generator': 'scripts/v7_rock_pool.py',
             'seed0': a.seed0, 'rocks': [],
             'note': '程序化生成，非扫描件，可与 R01–R04 独立计数；几何水密，纹理另存'}
    for i in range(a.n):
        seed = int(a.seed0 + i * 17)
        h = float(rng.uniform(0.10, 0.30))
        m = make_rock(seed, h)
        if len(m.faces) > MAX_FACES:
            m = m.simplify_quadric_decimation(MAX_FACES - 10)
        d = out / f'P{i + 1:02d}'
        d.mkdir(parents=True, exist_ok=True)
        p = d / 'body.stl'
        m.export(p)
        tex = procedural_texture(m, np.random.default_rng(seed + 1))
        tp = d / 'texture.png'
        trimesh.util.image.export_image(tex, tp) if hasattr(trimesh.util, 'image') else None
        if not tp.is_file():
            import PIL.Image
            PIL.Image.fromarray(tex).save(tp)
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        ext = (m.bounds[1] - m.bounds[0]).round(4).tolist()
        rec = {'id': d.name, 'seed': seed, 'target_h_m': round(h, 4),
               'body': str(p.relative_to(ROOT)), 'sha256': sha,
               'texture': str(tp.relative_to(ROOT)),
               'texture_sha256': hashlib.sha256(tp.read_bytes()).hexdigest(),
               'n_faces': int(len(m.faces)), 'n_vertices': int(len(m.vertices)),
               'watertight': bool(m.is_watertight), 'volume_m3': round(float(m.volume), 8),
               'bbox_m': ext, 'z_min_m': round(float(m.bounds[0][2]), 5),
               'height_m': round(float(ext[2]), 4)}
        (d / 'meta.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        index['rocks'].append(rec)
        print(json.dumps({'id': rec['id'], 'h': rec['height_m'], 'faces': rec['n_faces'],
                          'watertight': rec['watertight']}, ensure_ascii=False), flush=True)
    index['count'] = len(index['rocks'])
    (out / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2))
    print(json.dumps({'n': index['count']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
