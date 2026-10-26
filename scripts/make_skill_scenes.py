"""
单技能任务场景集：通道内通过一个低矮的 Lux3D 生成障碍。

技能定义（协议，先冻结再看结果）：
  · 平地 + 宽度受限的通道（半宽 0.40 m），机器人必须留在通道内；
  · 通道正中有 1 个生成几何障碍，横向宽度 0.50 m，两侧各留约 0.15 m，
    机器人（宽约 0.30 m）无法绕过，只能压过去；
  · 成功 = 四轮全部越过**变换后**几何的远端 + 0.10 m 净空，并在通道内
    连续稳定保持 1.0 s（中途退出通道/倾覆/回退都不累计）；
  · 失败分类：tipped（倾覆）、out_of_bounds（出通道）、time_limit（超时）；
    接触与不接触分别记录，接触越障才算本技能证据。

集合划分按 **GLB 家族**，训练/验证/考核互不重叠；同一家族的缩放、旋转、
不同摆放都算同源变体，不当作独立形状。
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCENES = ROOT / 'scenes'

CHANNEL_HALF_W = 0.40      # 兜底值；实际按障碍横向尺寸自适应
OBSTACLE_W = None          # 不再强制横向宽度，改为等比缩放
GOAL_X = 6.0

# 家族划分（7 个原始生成家族）
# R 组（旧开发资产）与 R+N 组（旧资产 + 本轮新生成家族）
OLD_TRAIN = ['flat_slab_w300', 'crate_lid_w300', 'fallen_panel_w300']
NEW_TRAIN = ['T1_device_base', 'T2', 'T3']          # 本轮真实生成
OLD_VAL = ['debris_plate_w300', 'boulder_w300']
NEW_VAL = ['V1']                                     # 本轮真实生成、仅开发验证
# 已见诊断集（既非本轮新生成，也不再充当未见考核）
SEEN_TEST = ['cargo_crate_w300', 'lander_leg_w300']

TRAIN_FAMILIES = OLD_TRAIN
VAL_FAMILIES = OLD_VAL
TEST_FAMILIES = NEW_VAL

SPLIT = {
    # R 组：旧开发资产
    'R_train': {'families': OLD_TRAIN, 'n': 12, 'seed': 1100},
    # R+N 组：旧资产 + 新生成家族（训练场景数与预算相同）
    'RN_train': {'families': OLD_TRAIN + NEW_TRAIN, 'n': 12, 'seed': 1100},
    # 共同开发验证：旧验证家族 + 新验证家族 V1
    'devval': {'families': OLD_VAL + NEW_VAL, 'n': 8, 'seed': 2100},
    # 已见诊断集（旧考核资产，仅作诊断，不充当未见）
    'seen': {'families': SEEN_TEST, 'n': 6, 'seed': 4100},
    # 最终考核：本轮真实新生成的 X1/X2，策略冻结后才生成并建场
    # 2 家族 × 4 布局 = 8 场景，每场景 3 个真实初态
    'final': {'families': ['X1', 'X2'], 'n': 8, 'seed': 5100},
}


def build(split):
    cfg = SPLIT[split]
    rng = np.random.default_rng(cfg['seed'])
    scenes = []
    for i in range(cfg['n']):
        asset = cfg['families'][i % len(cfg['families'])]
        # 难度带由实测确定：h=0.09 且初始横向偏差 0.20 m 时，
        # 零残差 3/15 (20%)、通道跟随控制器 12/15 (80%) —— 有学习空间且可完成。
        h = float(rng.uniform(0.085, 0.095))
        s = terrain.make_spec(
            kind='flat', seed=cfg['seed'] + i, objects=[{
                'asset': asset,
                'x': round(float(rng.uniform(1.6, 2.2)), 3),
                'y': round(float(rng.uniform(-0.05, 0.05)), 3),
                'yaw_deg': round(float(rng.uniform(-12, 12)), 1),
                'target_height_m': round(h, 4),
            }],
            goal_x=GOAL_X, name=f'skill_{split}_{i}')
        s['split'] = split
        s['family'] = asset
        # 通道宽度按**该障碍缩放后的实际横向尺寸**自适应：
        # 两侧各留 0.08 m，机器人（宽约 0.30 m）仍无法绕过。
        import runio
        man = runio.resolve_asset(ROOT / 'assets/processed' / asset)['manifest'] or {}
        h0 = float(man.get('height_m') or 0.09)
        w0 = float(man.get('width_y_m') or 0.3)
        wy = w0 * (h / h0)
        half = max(0.26, wy / 2.0 + 0.08)
        s['channel'] = {'center_y': 0.0, 'half_width': round(half, 3)}
        s['init_perturbation'] = {'lateral_m': 0.20, 'yaw_rad': 0.08}
        s['skill'] = 'channel_single_obstacle'
        s['skill_cfg'] = {'require_contact': True}
        scenes.append(s)
    return scenes


def main():
    summary = {}
    for split in ('R_train', 'RN_train', 'devval', 'seen', 'final'):
        scenes = build(split)
        p = SCENES / f'skill_{split}.json'
        p.write_text(json.dumps(scenes, indent=2, ensure_ascii=False))
        fams = sorted({s['family'] for s in scenes})
        hs = [s['objects'][0]['target_height_m'] for s in scenes]
        summary[split] = {'n': len(scenes), 'families': fams,
                          'height_range': [min(hs), max(hs)],
                          'ids': [terrain.scene_identity(s) for s in scenes]}
        print(f'skill_{split:10s} {len(scenes):2d} 场景  家族={fams}  '
              f'高度 {min(hs):.3f}-{max(hs):.3f} m')

    tr = set(summary['R_train']['families']) | set(summary['RN_train']['families'])
    va = set(summary['devval']['families'])
    fi = set(summary['final']['families'])
    print(f'训练家族 {sorted(tr)}')
    print(f'开发验证家族 {sorted(va)}')
    print(f'最终考核家族 {sorted(fi)}')
    assert not (tr & va), f'训练/验证重叠: {tr & va}'
    assert not (fi & tr) and not (fi & va), f'考核家族必须先于训练出现: {fi & (tr|va)}'
    print('训练/验证/考核家族两两无重叠 ✓')
    (SCENES / 'skill_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
