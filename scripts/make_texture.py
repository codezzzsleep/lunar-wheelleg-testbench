"""
确定性岩石纹理（盒投影 UV + 噪声），只改视觉不改碰撞。

  .venv/bin/python scripts/make_texture.py --out assets/textures/rock_v1.png --seed 7
"""
import argparse
import pathlib
import numpy as np
from PIL import Image

def fractal_noise(n=1024, seed=7, octaves=6):
    rng = np.random.default_rng(seed)
    acc = np.zeros((n, n), dtype=np.float64)
    amp = 1.0
    for o in range(octaves):
        s = max(2, n >> (octaves - o))
        base = rng.random((s, s))
        img = np.array(Image.fromarray((base * 255).astype(np.uint8))
                       .resize((n, n), Image.BICUBIC), dtype=np.float64) / 255.0
        acc += amp * img
        amp *= 0.5
    acc -= acc.min(); acc /= max(acc.max(), 1e-9)
    return acc

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--size', type=int, default=1024)
    a = ap.parse_args()
    n = a.size
    h = fractal_noise(n, a.seed)
    # 月球岩石：中性灰褐 + 细节对比
    base = np.array([0.72, 0.60, 0.46])
    shade = 0.55 + 0.65 * h
    rgb = np.clip(base[None, None, :] * shade[:, :, None], 0, 1)
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((rgb * 255).astype(np.uint8)).save(p)
    print(f'{p} {n}x{n} seed={a.seed} mean={rgb.mean():.3f}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
