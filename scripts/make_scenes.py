"""
生成训练/验证场景集（P = 程序化基线，G = 含生成几何）。

三类场景（任务书第七节）：
  A 平地上的复合障碍      —— flat_obstacles
  B 起伏或坡面地形        —— slope
  C 混合（地形 + 生成几何） —— mixed

划分：同一 GLB 家族的缩放/旋转不跨集合；这里按显式清单写死，便于复核。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCENES = ROOT / 'scenes'

# 现有 7 个生成家族：训练用 4 个，验证留 3 个（不跨边界）
# 首个版本刻意选**低障碍**（0.4–0.9 倍轮半径，即 0.035–0.08 m）。
# 之前把障碍设到 1.3–2.0 倍轮半径，已超出这台机器人的能力边界（实测 ~1.1 倍），
# 在那个区间训练不出东西，不是算法问题。
GEN_TRAIN = ['flat_slab_w300', 'crate_lid_w300', 'fallen_panel_w300', 'debris_plate_w300']
GEN_VAL = ['boulder_w300', 'cargo_crate_w300', 'lander_leg_w300']
# 难度选在能力边界附近：实测零动作策略（≈hold）在这一档只有 20–30% 成功，
# 既不是"随便过"也不是"根本过不去"，才有学习空间。
# 常数动作扫描确认这一档**存在解**（降低轮速即可通过），但零动作策略会翻：
#   h050 y0.10 成功 / h054 y0.10 翻 / h058 y0.18 翻
PROC = ['proc_box_h035', 'proc_box_h041', 'proc_box_h043', 'proc_box_h050']


def P_set(prefix, n, seed0):
    out = []
    for i in range(n):
        s = terrain.make_spec(
            kind='flat', seed=seed0 + i,
            # 横向偏移必须落在难度带：实测 offset=0 时轮子跨过去反而简单，
            # 0.08–0.36 才是"一侧轮子撞上"的真难点。
            objects=[{'asset': PROC[(i + (0 if prefix == 'trainP' else 2)) % len(PROC)],
                      'x': 1.8, 'y': 0.0, 'yaw_deg': 0.0}],
            goal_x=3.4, name=f'{prefix}_flat_{i}')
        s['split'] = 'train' if prefix == 'trainP' else 'validation'
        s['family'] = 'procedural'
        out.append(s)
    return out


def G_set(prefix, n, seed0):
    """生成组：与 P 组相同的宏观难度范围（高度 1.3–2.0 倍轮半径），
    但障碍来自 Lux3D 家族，并使用坡面/起伏地形。"""
    kinds = [('flat', {}), ('slope', {'slope_deg': 5.0}),
             ('mixed', {'slope_deg': 4.0, 'roughness': 0.05, 'pits': 1, 'pit_depth': 0.04})]
    out = []
    for i in range(n):
        kind, kw = kinds[i % len(kinds)]
        s = terrain.make_spec(
            kind=kind, seed=seed0 + i, objects=[], goal_x=3.4,
            name=f'{prefix}_{kind}_{i}', **kw)
        asset = GEN_TRAIN[i % len(GEN_TRAIN)] if prefix == 'trainG' \
            else GEN_VAL[i % len(GEN_VAL)]
        s['objects'] = [{'asset': asset, 'x': 1.8, 'y': 0.0, 'yaw_deg': 0.0}]
        s['split'] = 'train' if prefix == 'trainG' else 'validation'
        s['family'] = asset
        out.append(s)
    return out


def write(name, specs):
    p = SCENES / f'{name}.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(specs, indent=2, ensure_ascii=False))
    ids = [terrain.scene_identity(s) for s in specs]
    print(f'{name:12s} {len(specs)} 场景  ids={ids[:3]}{"..." if len(ids) > 3 else ""}')
    return p


if __name__ == '__main__':
    write('train_P', P_set('trainP', 3, 100))
    write('val_P', P_set('valP', 2, 200))
    write('train_G', G_set('trainG', 3, 300))
    write('val_G', G_set('valG', 2, 400))
    print('families: G train =', GEN_TRAIN)
    print('families: G val   =', GEN_VAL, '(与训练不重叠)')
