"""
条件输入 → 场景计划 → 一批物理场景。

  .venv/bin/python scripts/scene_compiler.py --task tasks/A_sparse.txt --seed 0 \
      --vary 6 --out scenes/A_sparse.json

支持两种输入：
  1. 受限自然语言语法（见下方 GRAMMAR）。解析出结构化参数，**这些参数真正决定
     地形、资产选择、数量、尺度与布局**。
  2. 可选参考包（--reference <dir>）：读取 meta.json 里的条件项覆盖语法默认值。
     若包内有 image 文件，只记录为来源，**不参与几何生成**——本版不读取图像。

明确边界（必须写进产物）：
  · 这不是"看图生成"。图像不参与几何。
  · 坡度/起伏/坑深是**米与度**的真实物理量（见 terrain.py）。
  · 尺寸若来自参考图，没有标尺时是人为设定，不声称恢复真实尺度。
"""
import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain

ROOT = pathlib.Path(__file__).resolve().parent.parent

GRAMMAR = """
每行一个 `key: value`，`#` 开头为注释。支持的条件项：

  scenario   巡检区 | 坡地 | 残骸通行段        —— 场景类别（决定默认地形）
  obstacles  <整数>                           —— 障碍数量（0-3）
  height     低 | 中 | 高                      —— 障碍尺度档（见 HEIGHT_BANDS）
  spread     紧 | 中 | 宽                      —— 障碍沿 x 的分布跨度（米）
  offset     摆正 | 交错                       —— 横向偏移模式
  slope      0..12                             —— 坡度（度）
  roughness  0..0.10                           —— 起伏振幅（米）
  pits       0..3                              —— 浅坑数量
  pit_depth  0..0.10                           —— 坑深（米）
  length     2.0..8.0                          —— 终点距离（米）
  family     任意资产名（可选，逗号分隔）        —— 指定使用的生成资产
"""

# 障碍尺度档 -> 该档实际使用的程序化对照资产（高度按倍轮半径取档内值）
HEIGHT_BANDS = {
    '低': {'rel_h': (0.5, 0.8), 'proc': ['proc_box_h043', 'proc_box_h050', 'proc_box_h058']},
    '中': {'rel_h': (0.8, 1.2), 'proc': ['proc_box_h090', 'proc_box_h100', 'proc_cylinder_h090']},
    '高': {'rel_h': (1.2, 2.0), 'proc': ['proc_box_h130', 'proc_box_h152', 'proc_box_h170']},
}

SCENARIO_DEFAULTS = {
    '巡检区': {'terrain_kind': 'flat', 'slope': 0.0, 'roughness': 0.0, 'pits': 0,
             'obstacles': 2, 'spread': (1.2, 2.6), 'height': '低', 'offset': '交错'},
    '坡地': {'terrain_kind': 'slope', 'slope': 5.0, 'roughness': 0.02, 'pits': 0,
           'obstacles': 1, 'spread': (1.8, 1.8), 'height': '低', 'offset': '摆正'},
    '残骸通行段': {'terrain_kind': 'mixed', 'slope': 3.0, 'roughness': 0.04, 'pits': 1,
              'obstacles': 2, 'spread': (1.4, 2.8), 'height': '中', 'offset': '交错'},
}

SPREAD_SCALE = {'紧': 0.7, '中': 1.0, '宽': 1.4}

# 目标障碍高度阶梯（米）。P/G 两组共用同一阶梯，障碍按各自 manifest 高度
# 等比缩放到该值 —— 尺度因此不是混淆变量，差异只能来自几何来源。
TARGET_HEIGHTS = [0.050, 0.060, 0.070]


def parse_task(text):
    """解析受限语法，返回 (条件 dict, 未识别行列表)。"""
    cond, unknown = {}, []
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        m = re.match(r'^([A-Za-z_]+)\s*:\s*(.+)$', line)
        if not m:
            unknown.append(line)
            continue
        k, v = m.group(1).lower(), m.group(2).strip()
        if k in ('scenario', 'height', 'spread', 'offset', 'family'):
            cond[k] = v
        elif k in ('obstacles', 'pits'):
            cond[k] = int(v)
        elif k in ('slope', 'roughness', 'pit_depth', 'length'):
            cond[k] = float(v)
        else:
            unknown.append(line)
    return cond, unknown


def load_reference_conditions(pack):
    """参考包只提供条件数值；图像不参与几何。"""
    p = pathlib.Path(pack)
    meta = json.loads((p / 'meta.json').read_text()) if (p / 'meta.json').exists() else {}
    cond, notes = {}, []
    t = meta.get('terrain') or {}
    if 'kind' in t:
        cond['scenario'] = {'flat': '巡检区', 'slope': '坡地', 'mixed': '残骸通行段'}.get(
            t['kind'], '巡检区')
    for src, dst in (('slope_deg', 'slope'), ('roughness', 'roughness')):
        if src in t:
            cond[dst] = float(t[src])
    if 'pits' in t:
        cond['pits'] = int(t['pits'])
    if 'pit_depth' in t:
        cond['pit_depth'] = float(t['pit_depth'])
    if meta.get('goal_x'):
        cond['length'] = float(meta['goal_x'])
    if meta.get('objects'):
        cond['obstacles'] = len(meta['objects'])
        fams = [o['asset'] for o in meta['objects'] if o.get('asset')]
        if fams:
            cond['family'] = ','.join(fams)
    imgs = [f.name for f in p.iterdir()
            if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')]
    notes.append({'images_found': imgs, 'images_used_for_geometry': False,
                  'note': '本版不读取图像；图像仅为来源记录'})
    return cond, notes


def resolve(cond):
    """条件 -> 完整参数（缺项用场景默认值补齐）。"""
    scen = cond.get('scenario', '巡检区')
    base = dict(SCENARIO_DEFAULTS.get(scen, SCENARIO_DEFAULTS['巡检区']))
    for k in ('slope', 'roughness', 'pits', 'pit_depth', 'obstacles', 'height', 'offset'):
        if k in cond:
            base[k] = cond[k]
    if 'spread' in cond and cond['spread'] in SPREAD_SCALE:
        s0, s1 = base['spread']
        f = SPREAD_SCALE[cond['spread']]
        base['spread'] = (round(s0 * f, 3), round(s1 * f, 3))
    base['length'] = float(cond.get('length', 6.0))
    fams = cond.get('family')
    base['family'] = [x.strip() for x in fams.split(',')] if fams else None
    base['scenario'] = scen
    return base


def compile_scenes(cond, seed0, n, split='train', family_override=None):
    """生成 n 个场景；同一 (条件, seed) 可重建，改 seed 得到有意义的变体。"""
    p = resolve(cond)
    band = HEIGHT_BANDS.get(p['height'], HEIGHT_BANDS['低'])
    assets_proc = band['proc']
    scenes = []
    for i in range(n):
        seed = seed0 + i
        s0, s1 = p['spread']
        # 障碍沿 x 的位置：由 spread 决定，随 seed 抖动
        import numpy as np
        rng = np.random.default_rng(seed * 7919 + 13)
        n_obj = max(0, min(3, int(p['obstacles'])))
        xs = np.linspace(s0, s1, n_obj) if n_obj > 1 else np.array([(s0 + s1) / 2])
        xs = np.clip(xs + rng.uniform(-0.12, 0.12, n_obj), 0.8, 3.2)
        objs = []
        for k in range(n_obj):
            # 横向偏移不能取 0：实测箱宽 0.30 m 与轮线（y=±0.142）几乎相切，
            # y=0 时箱子正好卡在两条轮线之间，机器人会**直接跨过去、不发生接触**。
            # 因此两种模式都落在轮线上，保证几何真实参与接触。
            if p['offset'] == '交错':
                y = (0.12 if k % 2 == 0 else -0.12) * rng.uniform(0.9, 1.2)
            else:
                y = 0.12 * rng.uniform(0.9, 1.1)
            if family_override:
                # 按 (场景序号 + 障碍序号) 轮换，保证一个集合内所有指定家族都会出现
                asset = family_override[(i + k) % len(family_override)]
            elif p['family']:
                asset = p['family'][k % len(p['family'])]
            else:
                asset = assets_proc[k % len(assets_proc)]
            objs.append({'asset': asset, 'x': round(float(xs[k]), 3),
                         'y': round(float(y), 3),
                         'yaw_deg': round(float(rng.uniform(-15, 15)), 1),
                         'target_height_m': (round(float(rng.choice(TARGET_HEIGHTS)), 4)
                                             if TARGET_HEIGHTS else None)})
        kind = p['terrain_kind']
        # 标签随实际内容走：有起伏/坑就不是单纯的 flat/slope
        has_bump = float(p.get('roughness', 0)) > 0 or int(p.get('pits', 0)) > 0
        if has_bump and kind == 'flat':
            kind = 'bumpy'
        elif has_bump and kind == 'slope':
            kind = 'mixed'
        spec = terrain.make_spec(
            kind=kind, seed=seed, slope_deg=float(p.get('slope', 0.0)),
            roughness=float(p.get('roughness', 0.0)), pits=int(p.get('pits', 0)),
            pit_depth=float(p.get('pit_depth', 0.0)), objects=objs,
            goal_x=p['length'], name=f'{split}_{p["scenario"]}_{seed}')
        spec['split'] = split
        spec['condition'] = {'scenario': p['scenario'], 'height_band': p['height'],
                             'rel_h_range': band['rel_h'], 'spread': p['spread'],
                             'offset_mode': p['offset'], 'seed': seed}
        scenes.append(spec)
    return scenes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', required=True)
    ap.add_argument('--reference', default=None)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--vary', type=int, default=6)
    ap.add_argument('--split', default='train')
    ap.add_argument('--out', required=True)
    ap.add_argument('--family', default=None, help='强制指定生成资产（用于 P/G 对照）')
    a = ap.parse_args()

    text = pathlib.Path(a.task).read_text(encoding='utf-8')
    cond, unknown = parse_task(text)
    ref_notes = []
    if a.reference:
        rc, ref_notes = load_reference_conditions(a.reference)
        for k, v in rc.items():
            cond.setdefault(k, v)

    fam = [x.strip() for x in a.family.split(',')] if a.family else None
    scenes = compile_scenes(cond, a.seed, a.vary, a.split, family_override=fam)

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scenes, indent=2, ensure_ascii=False))

    print(f'条件解析: {json.dumps(cond, ensure_ascii=False)}')
    if unknown:
        print(f'未识别的行（已忽略，不算完成条件）: {unknown}')
    print(f'生成 {len(scenes)} 个场景 -> {out}')
    for s in scenes[:3]:
        hs = [o["asset"] for o in s["objects"]]
        print(f'  {s["name"]:24s} 地形 {s["terrain"]["kind"]:5s} '
              f'坡 {s["terrain"]["slope_deg"]:.1f}° 障碍 {hs}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
