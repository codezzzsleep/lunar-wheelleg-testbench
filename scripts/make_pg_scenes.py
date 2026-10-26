"""
按冻结协议生成 P/G 场景集。

P：程序化障碍（方块/圆柱）
G：Lux3D 生成家族

两组共享：地形分布、条件语法、布局规则、随机种子、场景数量。
唯一差异：障碍几何来源。因此差异可归因于几何来源，而不是地形或布局。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scene_compiler as C
import terrain

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCENES = ROOT / 'scenes'

# 按**原始家族**划分，同一个 GLB 家族不跨集合
G_TRAIN_FAMILIES = ['flat_slab_w300', 'crate_lid_w300', 'fallen_panel_w300']
G_VAL_FAMILIES = ['debris_plate_w300', 'boulder_w300']
G_TEST_FAMILIES = ['cargo_crate_w300', 'lander_leg_w300']

P_TRAIN = ['proc_box_h043', 'proc_box_h050', 'proc_cylinder_h043']
P_VAL = ['proc_box_h058', 'proc_cylinder_h090']
P_TEST = ['proc_box_h090', 'proc_box_h100']

CONDITIONS = {
    'A': {'scenario': '巡检区', 'obstacles': 2, 'height': '低', 'spread': '宽',
          'offset': '交错', 'length': 6.0},
    'B': {'scenario': '坡地', 'obstacles': 1, 'height': '低', 'slope': 5.0,
          'roughness': 0.03, 'pits': 1, 'pit_depth': 0.03, 'length': 6.0},
    'C': {'scenario': '残骸通行段', 'obstacles': 2, 'height': '中', 'spread': '中',
          'offset': '交错', 'slope': 3.0, 'roughness': 0.04, 'pits': 1,
          'pit_depth': 0.04, 'length': 6.5},
}

SPLIT_SEEDS = {'train': 1000, 'validation': 2000, 'test': 3000}
SPLIT_COUNT = {'train': 8, 'validation': 4, 'test': 4}
SPLIT_FAMS = {'P': {'train': P_TRAIN, 'validation': P_VAL, 'test': P_TEST},
              'G': {'train': G_TRAIN_FAMILIES, 'validation': G_VAL_FAMILIES,
                    'test': G_TEST_FAMILIES}}


def build(group, split, cond_key):
    fams = SPLIT_FAMS[group][split]
    return C.compile_scenes(CONDITIONS[cond_key], SPLIT_SEEDS[split], SPLIT_COUNT[split],
                            split=split, family_override=fams)


def main():
    summary = {}
    for group in ('P', 'G'):
        for split in ('train', 'validation', 'test'):
            specs = []
            for ck in CONDITIONS:
                for s in build(group, split, ck):
                    s['group'] = group
                    s['condition_key'] = ck
                    specs.append(s)
            p = SCENES / f'{group}_{split}.json'
            p.write_text(json.dumps(specs, indent=2, ensure_ascii=False))
            ids = [terrain.scene_identity(s) for s in specs]
            fams = sorted({o['asset'] for s in specs for o in s['objects']})
            summary[f'{group}_{split}'] = {'n': len(specs), 'ids': ids, 'families': fams}
            print(f'{group}_{split:10s} {len(specs):2d} 场景  家族={fams}')
    # 校验：训练/验证/测试的家族不重叠
    for group in ('P', 'G'):
        tr = set(summary[f'{group}_train']['families'])
        va = set(summary[f'{group}_validation']['families'])
        te = set(summary[f'{group}_test']['families'])
        assert not (tr & va) and not (tr & te) and not (va & te), \
            f'{group} 家族跨集合重叠: {tr & va} {tr & te} {va & te}'
        print(f'{group} 家族划分无重叠 ✓')
    # 校验：P 与 G 的地形参数一致
    for split in ('train', 'validation', 'test'):
        p = [s['terrain'] for s in json.loads((SCENES / f'P_{split}.json').read_text())]
        g = [s['terrain'] for s in json.loads((SCENES / f'G_{split}.json').read_text())]
        assert p == g, f'{split} 的 P/G 地形不一致'
        print(f'{split} P/G 地形参数完全一致 ✓ ({len(p)} 个场景)')
    (SCENES / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
