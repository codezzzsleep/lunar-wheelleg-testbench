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

CHANNEL_HALF_W = 0.40
OBSTACLE_W = 0.50
GOAL_X = 6.0

# 家族划分（7 个原始生成家族）
TRAIN_FAMILIES = ['flat_slab_w300', 'crate_lid_w300', 'fallen_panel_w300']
VAL_FAMILIES = ['debris_plate_w300', 'boulder_w300']
TEST_FAMILIES = ['cargo_crate_w300', 'lander_leg_w300']

SPLIT = {
    'train': {'families': TRAIN_FAMILIES, 'n': 12, 'seed': 1100},
    'validation': {'families': VAL_FAMILIES, 'n': 6, 'seed': 2100},
    'test': {'families': TEST_FAMILIES, 'n': 8, 'seed': 3100},
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
                'target_width_m': OBSTACLE_W,
            }],
            goal_x=GOAL_X, name=f'skill_{split}_{i}')
        s['split'] = split
        s['family'] = asset
        s['channel'] = {'center_y': 0.0, 'half_width': CHANNEL_HALF_W}
        s['init_perturbation'] = {'lateral_m': 0.20, 'yaw_rad': 0.08}
        s['skill'] = 'channel_single_obstacle'
        scenes.append(s)
    return scenes


def main():
    summary = {}
    for split in ('train', 'validation', 'test'):
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

    tr = set(summary['train']['families'])
    va = set(summary['validation']['families'])
    te = set(summary['test']['families'])
    assert not (tr & va) and not (tr & te) and not (va & te), '家族跨集合重叠'
    print('家族划分无重叠 ✓')
    (SCENES / 'skill_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
