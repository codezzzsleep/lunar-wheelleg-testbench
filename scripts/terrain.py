"""
地形与场景生成：把结构化 scene_spec 编译成可加载的 MuJoCo 场景。

设计要点（对应任务书第七节）：
  · 地面用 **heightfield**，不是单个格子 mesh —— mesh 在 MuJoCo 里按凸包碰撞，
    起伏会被填平。hfield 才能表达坡面、起伏、浅坑。
  · Lux3D 物体放在机器人实际会接触的路径上，不是远处装饰。
  · 所有随机性来自 spec 里的 seed，可重建。
  · 明确标注场景类别（平地/坡面/混合）与难度参数，便于分层报告。
"""
import hashlib
import json
import pathlib

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
HF_DIR = ROOT / 'runs/_hfield'
N = 65                      # hfield 网格边长
SPAN = 4.0                  # 半边长（米）
ZMAX = 0.35                 # 高度上限


def _slope(n, deg, axis='x'):
    t = np.linspace(-SPAN, SPAN, n)
    h = np.tan(np.deg2rad(deg)) * (t + SPAN) / (2 * SPAN)     # 从 0 升到 tan(deg)
    g = h[:, None] * np.ones((1, n)) if axis == 'x' else np.ones((n, 1)) * h[None, :]
    return g


def _bumps(n, amp, freq, rng):
    x = np.linspace(0, freq * 2 * np.pi, n)
    X, Y = np.meshgrid(x, x, indexing='ij')
    return amp * (np.sin(X) * np.cos(Y * 1.3) + 0.5 * np.sin(X * 2.1 + 0.7) * np.cos(Y * 0.9))


def _pits(n, depth, count, rng):
    h = np.zeros((n, n))
    xs = np.linspace(0, 1, n)
    X, Y = np.meshgrid(xs, xs, indexing='ij')
    for _ in range(count):
        cx, cy = rng.uniform(0.15, 0.85, 2)
        r = rng.uniform(0.05, 0.12)
        d = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
        h -= depth * np.exp(-(d ** 2) / (2 * r ** 2))
    return h


def build_heightfield(spec):
    """
    spec['terrain'] = {
        'kind': 'flat' | 'slope' | 'bumpy' | 'mixed',
        'slope_deg': float, 'roughness': float, 'pits': int, 'pit_depth': float
    }
    返回 (数组, 归一化后用于写盘的值域信息)
    """
    t = spec.get('terrain', {})
    kind = t.get('kind', 'flat')
    seed = int(spec.get('seed', 0))
    rng = np.random.default_rng(seed)

    h = np.zeros((N, N))
    if kind in ('slope', 'mixed'):
        h += _slope(N, float(t.get('slope_deg', 0.0)))
    if kind in ('bumpy', 'mixed'):
        h += _bumps(N, float(t.get('roughness', 0.0)), 2.5, rng)
    if kind in ('bumpy', 'mixed') and t.get('pits', 0):
        h += _pits(N, float(t.get('pit_depth', 0.0)), int(t['pits']), rng)

    h -= h.min()                      # 最低点归零
    peak = float(h.max()) or 1e-9
    return h, {'raw_min': 0.0, 'raw_max': peak}


def write_heightfield_png(h, path):
    """MuJoCo 的 hfield 读 8 位灰度 PNG；高度按 ZMAX 归一化。"""
    peak = float(h.max()) or 1e-9
    img = (h / peak * 255.0).astype(np.uint8)
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img, mode='L').save(path)
    return path


def heightfield_xml(spec, png_path):
    return (f'<hfield name="terrain" nrow="{N}" ncol="{N}" '
            f'size="{SPAN} {SPAN} {ZMAX} 0.01" file="{png_path}"/>')


def terrain_geom_xml(pos='0 0 0', rgba='.32 .32 .36 1', friction='0.9 0.02 0.001'):
    # pos 必须是 0：hfield 以 geom 位置为中心、半径 SPAN。
    # 旧值 '-2 -2 0' 让地面只覆盖 [-6,2]x[-6,2]，机器人跑到 x>2 就没地面了。
    return (f'<geom name="terrain" type="hfield" hfield="terrain" pos="{pos}" '
            f'rgba="{rgba}" friction="{friction}" contype="1" conaffinity="1"/>')


def scene_identity(spec):
    """场景身份 = 影响仿真的 spec 内容的规范化哈希。"""
    keys = ('terrain', 'objects', 'goal_x', 'seed', 'start')
    payload = {k: spec.get(k) for k in keys}
    blob = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ scene_spec

def make_spec(kind='flat', seed=0, slope_deg=0.0, roughness=0.0, pits=0,
              pit_depth=0.0, objects=None, goal_x=3.0, name='scene'):
    """
    objects: [{'asset': 'boulder_w300', 'x': 2.0, 'y': 0.0, 'yaw_deg': 0.0}]
    场景类别：
      flat_obstacles  平地上的复合障碍
      slope           坡面地形
      mixed           起伏/坡面 + 生成几何
    """
    return {
        'name': name,
        'seed': int(seed),
        'split': 'train',
        'start': [0.0, 0.0],
        'goal_x': float(goal_x),
        'terrain': {'kind': kind, 'slope_deg': float(slope_deg),
                    'roughness': float(roughness), 'pits': int(pits),
                    'pit_depth': float(pit_depth)},
        'objects': objects or [],
        'provenance': {'generator': 'scripts/terrain.py',
                       'terrain_representation': 'heightfield',
                       'note': '所有物体为静态刚性体；地形为刚性 heightfield'},
    }
