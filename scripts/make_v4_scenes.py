"""
v4 协议场景集：任务 M（安全通行）与任务 K（接触越障）。

冻结要点（训练前写定，之后不按成绩修改）：
  · 通道半宽 **0.42 m 全任务统一**，不按障碍宽度缩放（上一轮那样会混淆难度）。
  · 终点 goal_x 在 heightfield 覆盖范围内（±4 m），不用越界数值。
  · 整体等比缩放，只按高度映射到米制，不拉伸形状。
  · 初态扰动 ±0.20 m 横向、±0.08 rad 朝向，按机器人足迹核对合法。
  · 任务 M：四轮越过终点线 + 通道内稳定保持 1 s；绕行/跨骑/接触都算有效。
  · 任务 K：四轮越过障碍**变换后**远端 + 0.10 m 净空 + 稳定保持 1 s，
    且必须发生接触；无接触记 bypass，不算接触越障。

家族划分：
  训练（6）= 旧 3 + T1/T2/T3      验证（3）= 旧 2 + V1
  诊断（4）= cargo_crate / lander_leg / X1 / X2（已见，不再称未见）
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCENES = ROOT / 'scenes'

CHANNEL_HALF_W = 0.42
GOAL_X = 3.0
SETTLE_S = 1.0
PASS_CLEARANCE = 0.10

TRAIN_FAMILIES = ['flat_slab_w300', 'crate_lid_w300', 'fallen_panel_w300',
                  'T1_device_base', 'T2', 'T3']
VAL_FAMILIES = ['debris_plate_w300', 'boulder_w300', 'V1']
SEEN_FAMILIES = ['cargo_crate_w300', 'lander_leg_w300', 'X1', 'X2']


def _spec(name, asset, task, seed, y, h, yaw):
    cfg = {'task': task, 'require_contact': task == 'K',
           'settle_seconds': SETTLE_S, 'pass_clearance': PASS_CLEARANCE}
    s = terrain.make_spec(kind='flat', seed=seed,
                          objects=[{'asset': asset, 'x': 1.8, 'y': y,
                                    'yaw_deg': yaw,
                                    'target_height_m': h}],
                          goal_x=GOAL_X, name=name)
    s['split'] = 'train'
    s['family'] = asset
    s['channel'] = {'center_y': 0.0, 'half_width': CHANNEL_HALF_W}
    s['init_perturbation'] = {'lateral_m': 0.20, 'yaw_rad': 0.08}
    s['skill_cfg'] = cfg
    return s


def build(families, n, seed0, task, y_rule):
    rng = np.random.default_rng(seed0)
    out = []
    for i in range(n):
        asset = families[i % len(families)]
        h = float(rng.uniform(0.080, 0.090))   # 标定：此档零残差 M 4/6、K 3/6，有学习空间
        y = y_rule(i, rng)
        out.append(_spec(f'{task}_{seed0}_{i}', asset, task, seed0 + i,
                         round(y, 3), round(h, 4), round(float(rng.uniform(-12, 12)), 1)))
    return out


def main():
    # 任务 M：障碍居中，允许绕行/跨骑/接触 —— 主任务
    m_train = build(TRAIN_FAMILIES, 18, 6100, 'M', lambda i, r: 0.0)
    m_val = build(VAL_FAMILIES, 12, 6200, 'M', lambda i, r: 0.0)
    # 任务 K：障碍布置在轮线上（单侧接触题），强制"必须接触"
    k_train = build(TRAIN_FAMILIES, 18, 6300, 'K',
                    lambda i, r: 0.14 * (1 if i % 2 == 0 else -1))
    k_val = build(VAL_FAMILIES, 12, 6400, 'K',
                  lambda i, r: 0.14 * (1 if i % 2 == 0 else -1))
    # 已见诊断（不参与训练与选择）
    diag = build(SEEN_FAMILIES, 16, 6500, 'M', lambda i, r: 0.0)

    summary = {}
    for name, scenes in (('v4_M_train', m_train), ('v4_M_val', m_val),
                         ('v4_K_train', k_train), ('v4_K_val', k_val),
                         ('v4_diag', diag)):
        p = SCENES / f'{name}.json'
        p.write_text(json.dumps(scenes, indent=2, ensure_ascii=False))
        fams = sorted({s['family'] for s in scenes})
        summary[name] = {'n': len(scenes), 'families': fams,
                         'ids': [terrain.scene_identity(s) for s in scenes]}
        print(f'{name:14s} {len(scenes):2d} 场景  家族={fams}')

    tr, va, di = set(summary['v4_M_train']['families']), \
        set(summary['v4_M_val']['families']), set(summary['v4_diag']['families'])
    assert not (tr & va), f'训练/验证重叠 {tr & va}'
    print(f'训练 {len(tr)} 家族 / 验证 {len(va)} 家族 / 诊断 {len(di)} 家族，无重叠 ✓')
    print(f'通道半宽 {CHANNEL_HALF_W} m，终点 x={GOAL_X} m（在 heightfield 覆盖内）')
    (SCENES / 'v4_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
