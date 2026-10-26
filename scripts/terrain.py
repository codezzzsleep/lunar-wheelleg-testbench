"""
地形生成：把条件参数编译成**真实米制**的 heightfield。

上一版的错误（7347599）：
  · 每张高度图先减去最小值再按自身峰值归一化，然后统一用固定的 0.35 m 高度范围。
  · 结果 1° 与 10° 坡度编译出**完全相同**的物理地面（已用 hfield_data 与 PNG 哈希证实）。

本版约定：
  · 所有高度函数的输入输出都是**米**：坡度用 tan(deg)，roughness 是振幅（米），
    pit_depth 是深度（米）。
  · PNG 只是编码载体：value = h / zmax * 255，而 hfield 的 size[2] 就取 zmax。
    因此物理高度 = value/255 * zmax = h，误差只有 8 位量化。
  · zmax 由实际高度决定并记录在 scene_spec 里，不同参数 -> 不同物理表面。
"""
import hashlib
import json
import pathlib

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
HF_DIR = ROOT / 'runs/_hfield'
N = 65                      # hfield 网格边长
SPAN = 4.0                  # 半边长（米）-> 覆盖 [-4,4] x [-4,4]
PNG_LEVELS = 255


# ------------------------------------------------------------------ 高度函数（米）

def grid_xy(n=N):
    """
    返回 (X, Y) 世界坐标网格，形状 (n, n)。

    索引约定（由 tests 的射线实测标定，不是猜的）：
      · 第 0 维是 **行**，对应 y，且 row 0 -> y=+SPAN（翻转）
      · 第 1 维是 **列**，对应 x，col 0 -> x=-SPAN
    """
    xs = np.linspace(-SPAN, SPAN, n)        # 列 = x
    ys = np.linspace(SPAN, -SPAN, n)        # 行 = y（翻转）
    return np.meshgrid(xs, ys, indexing='xy')


def slope_height(n, deg, axis='x'):
    """沿 axis 的均匀坡度，返回米。总落差 = tan(deg) * 2*SPAN。"""
    X, Y = grid_xy(n)
    along = X if axis == 'x' else -Y         # 沿 +x 或 +y 升高
    return np.tan(np.deg2rad(deg)) * (along + SPAN)


def bump_height(n, amp, wavelength=2.4):
    """正弦起伏，amp 是**米**（峰谷总幅度的半值）。"""
    X, Y = grid_xy(n)
    k = 2 * np.pi / wavelength
    return amp * (np.sin(X * k) * np.cos(Y * k * 1.3)
                  + 0.5 * np.sin(X * k * 2.1 + 0.7) * np.cos(Y * k * 0.9))


def pit_height(n, depth, count, rng, radius=0.45):
    """高斯浅坑，depth 是**米**（正数），返回负高度。"""
    X, Y = grid_xy(n)
    h = np.zeros((n, n))
    for _ in range(count):
        cx, cy = rng.uniform(-0.7, 0.7, 2) * SPAN
        d2 = (X - cx) ** 2 + (Y - cy) ** 2
        h -= depth * np.exp(-d2 / (2 * radius ** 2))
    return h


def build_heightfield(spec):
    """返回 (h_meters, meta)。h 是米；meta 记录 zmax 与各分量实际幅度。"""
    t = spec.get('terrain', {})
    kind = t.get('kind', 'flat')
    rng = np.random.default_rng(int(spec.get('seed', 0)))

    # 由**参数**驱动，而不是由 kind 标签驱动：
    # 旧实现按 kind 分支，导致 kind='slope' 时 roughness / pits 被静默丢弃，
    # 条件写了数字但物理地面没变 —— 这正是任务书禁止的静默映射。
    h = np.zeros((N, N))
    parts = {}
    deg = float(t.get('slope_deg', 0.0))
    if deg != 0.0:
        h += slope_height(N, deg)
        parts['slope_deg'] = deg
        parts['slope_rise_m'] = round(float(np.tan(np.deg2rad(deg)) * 2 * SPAN), 4)
    amp = float(t.get('roughness', 0.0))
    if amp != 0.0:
        h += bump_height(N, amp)
        parts['bump_amp_m'] = amp
    if int(t.get('pits', 0)):
        h += pit_height(N, float(t.get('pit_depth', 0.0)), int(t['pits']), rng)
        parts['pit_depth_m'] = float(t.get('pit_depth', 0.0))
        parts['pits'] = int(t['pits'])

    h = h - h.min()                     # 最低点归零（不改变形状与幅度）
    zmax = float(h.max())
    if zmax <= 1e-9:
        zmax = 1e-3                     # 纯平地也要有正的 size[2]
    return h, {'zmax': round(zmax, 6), 'actual_max_m': round(float(h.max()), 4),
               'actual_min_m': 0.0, 'components': parts, 'kind_label': kind,
               'grid': N, 'span_m': SPAN}


def write_heightfield_png(h, path, zmax=None):
    """PNG 只做编码：value = h/zmax*255。物理尺度在 hfield 的 size[2] 里。"""
    zmax = float(zmax if zmax is not None else (h.max() or 1e-3))
    img = np.clip(np.round(h / zmax * PNG_LEVELS), 0, PNG_LEVELS).astype(np.uint8)
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img, mode='L').save(path)
    return path


def heightfield_xml(spec, png_path, zmax):
    # size = 半径x 半径y 最大高度 基底；第 4 个值必须为正
    return (f'<hfield name="terrain" nrow="{N}" ncol="{N}" '
            f'size="{SPAN} {SPAN} {zmax} 0.01" file="{png_path}"/>')


def terrain_geom_xml(pos='0 0 0', rgba='.32 .32 .36 1', friction='0.9 0.02 0.001'):
    # pos 必须是 0：hfield 以 geom 位置为中心、半径 SPAN。
    return (f'<geom name="terrain" type="hfield" hfield="terrain" pos="{pos}" '
            f'rgba="{rgba}" friction="{friction}" contype="1" conaffinity="1"/>')


def ground_height_at(h, x, y):
    """
    在 (x,y) 处按双线性插值取地表高度（米）。
    行沿 y 且 row0 对应 y=+SPAN，列沿 x 且 col0 对应 x=-SPAN —— 由射线实测标定。
    """
    u = (x + SPAN) / (2 * SPAN)      # -> 列（x）
    v = (SPAN - y) / (2 * SPAN)      # -> 行（y 翻转，见 grid_xy）
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return 0.0
    col, row = u * (N - 1), v * (N - 1)
    c0, r0 = int(np.floor(col)), int(np.floor(row))
    c1, r1 = min(c0 + 1, N - 1), min(r0 + 1, N - 1)
    fc, fr = col - c0, row - r0
    return float(h[r0, c0] * (1 - fc) * (1 - fr) + h[r0, c1] * fc * (1 - fr)
                 + h[r1, c0] * (1 - fc) * fr + h[r1, c1] * fc * fr)


def scene_identity(spec):
    """场景身份 = 影响仿真的 spec 内容的规范化哈希。"""
    keys = ('terrain', 'objects', 'goal_x', 'seed', 'start', 'layout')
    payload = {k: spec.get(k) for k in keys}
    blob = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ scene_spec

def make_spec(kind='flat', seed=0, slope_deg=0.0, roughness=0.0, pits=0,
              pit_depth=0.0, objects=None, goal_x=3.0, name='scene', **extra):
    spec = {
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
                       'units': 'meters',
                       'note': '地形高度为真实米制；物体静态刚性'},
    }
    spec.update(extra)
    return spec


def ground_height_many(h, xs, ys):
    """向量化版本的 ground_height_at，用于物体逐顶点落地。"""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    u = (xs + SPAN) / (2 * SPAN)
    v = (SPAN - ys) / (2 * SPAN)
    inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    col = np.clip(u, 0, 1) * (N - 1)
    row = np.clip(v, 0, 1) * (N - 1)
    c0 = np.floor(col).astype(int); r0 = np.floor(row).astype(int)
    c1 = np.minimum(c0 + 1, N - 1);  r1 = np.minimum(r0 + 1, N - 1)
    fc = col - c0; fr = row - r0
    val = (h[r0, c0] * (1 - fc) * (1 - fr) + h[r0, c1] * fc * (1 - fr)
           + h[r1, c0] * (1 - fc) * fr + h[r1, c1] * fc * fr)
    return np.where(inside, val, 0.0)


def place_on_terrain(h, verts_world_xy_z):
    """
    给定物体的世界坐标顶点（已含旋转），返回 (body_z, meta)。

    做法：对每个顶点求"若该顶点贴地，机身需要的高度" = ground(x,y) - v_z，
    取所有顶点的最大值 —— 这样最低点刚好落在其正下方地面上，任何顶点都不会
    低于地形（不埋），且至少有一个顶点接触（不悬空）。
    """
    xs = np.asarray(verts_world_xy_z[:, 0], dtype=np.float64)
    ys = np.asarray(verts_world_xy_z[:, 1], dtype=np.float64)
    vs = np.asarray(verts_world_xy_z[:, 2], dtype=np.float64)
    gz = ground_height_many(h, xs, ys)
    need = gz - vs
    k = int(np.argmax(need))
    return float(need[k]), {
        'body_z': round(float(need[k]), 5),
        'touching_vertex_xy': [round(float(xs[k]), 4), round(float(ys[k]), 4)],
        'ground_under_touch_m': round(float(gz[k]), 4),
        'min_clearance_m': round(float(np.min(need[k] - need)), 6),   # >=0 表示无埋入
        'ground_span_under_object_m': [round(float(gz.min()), 4), round(float(gz.max()), 4)],
    }
