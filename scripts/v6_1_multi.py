"""
V6.1 工作包 D：多父候选（H5_F_multi）与 R03 覆盖。

对 R01 的四个真实 Lux3D 父候选分别融合（同一冻结配置），记录每个候选的
可见面一致性，区分“合格/不合格”；再用**合格**候选的并集先验构建 H5_F_multi。
对 R03 用其唯一父候选做同样的融合，作为第二个案例的覆盖证据。

  .venv/bin/python scripts/v6_1_multi.py --case R01 --out runs/unseen/delivery_v6_1/.../multi
  .venv/bin/python scripts/v6_1_multi.py --case R03 --out ...
  .venv/bin/python scripts/v6_1_multi.py --case both

输出：<out>/<case>/index.json，含每个候选的 manifest 路径、指标、是否合格、以及 multi 资产。
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BATCH = ROOT / 'runs/unseen/delivery_v6_1/v6_1_20261029'

POOL = {
    'R01': {
        'observation': 'runs/unseen/recovery_r3/obs_R01',
        'parents': {
            'C_R01_face12k': 'runs/unseen/delivery_v5/v5_20261029/candidates/C_R01_face12k/world/align',
            'G_R01': 'runs/unseen/recovery_r3/r01_recheck/align/world/G_R01',
            'G_R01_rep2': 'runs/unseen/recovery_r3/r01_recheck/align/world/G_R01_rep2',
            'G_R01_rep3': 'runs/unseen/recovery_r3/r01_recheck/align/world/G_R01_rep3',
        },
    },
    'R03': {
        'observation': 'runs/unseen/recovery_r3/obs_R03',
        'parents': {
            'G_R03': 'runs/unseen/recovery_r3/align_v3/world/G_R03',
        },
    },
}

# 资格门槛（只用可见面，不看真值）：掩码 IoU 与可见点 P95。
QUAL_IOU_MIN = 0.90
QUAL_P95_MM_MAX = 5.0
QUAL_FREESPACE_MAX = 0.05     # 与 strict 门槛一致：freespace 不过就不算合格资产


def run_fuse(observation, parents, parent_id, out):
    cmd = [sys.executable, str(ROOT / 'scripts/fuse_observed.py'),
           '--observation', str(ROOT / observation),
           '--parent-id', parent_id, '--method', 'H5_F', '--out', str(out),
           '--config', str(ROOT / 'configs/unseen_v6_1_fusion.json')]
    for p in parents:
        cmd += ['--parent-world', str(ROOT / p)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT),
                       env={**__import__('os').environ,
                            'LD_LIBRARY_PATH': '/tmp/sysroot/usr/lib/x86_64-linux-gnu:/tmp/sysroot/lib/x86_64-linux-gnu',
                            'MUJOCO_GL': 'osmesa'})
    if r.returncode != 0:
        raise SystemExit(f'融合失败 {parent_id}: {r.stderr[-500:]}')
    return json.loads((out / 'manifest.json').read_text())


def qualifying(man):
    """正式资格：三项全过才算合格。任一不过只能作诊断，不得进入正式规划。"""
    m = man.get('metrics') or {}
    iou = m.get('mask_iou'); p95 = m.get('vis_pt_p95_mm'); free = m.get('freespace_violation')
    if iou is None or p95 is None or free is None:
        return False, '指标缺失'
    why = []
    if iou < QUAL_IOU_MIN:
        why.append(f'IoU {iou} < {QUAL_IOU_MIN}')
    if p95 > QUAL_P95_MM_MAX:
        why.append(f'可见点 P95 {p95} > {QUAL_P95_MM_MAX} mm')
    if free > QUAL_FREESPACE_MAX:
        why.append(f'freespace {free} > {QUAL_FREESPACE_MAX}')
    return (not why), ('；'.join(why) or 'ok')


def do_case(case, out_root, mode='separate'):
    spec = POOL[case]
    cdir = out_root / case
    cdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for pid, world in spec['parents'].items():
        out = cdir / pid
        man = run_fuse(spec['observation'], [world], f'{case}_{pid}', out)
        ok, why = qualifying(man)
        m = man.get('metrics') or {}
        rows.append({'parent': pid, 'world': world,
                     'manifest': str(out / 'manifest.json'),
                     'world_sha': man.get('world_sha'),
                     'mask_iou': m.get('mask_iou'),
                     'vis_p95_mm': m.get('vis_pt_p95_mm'),
                     'freespace': m.get('freespace_violation'),
                     'volume_m3': man.get('volume_m3'),
                     'hidden_kept_ratio': (man.get('retention') or {}).get('kept_ratio'),
                     'solid_method': man['parent_solid'].get('solid_method'),
                     'qualified': ok, 'why': why})
        print(case, pid, 'qualified' if ok else 'NOT', m.get('mask_iou'), m.get('vis_pt_p95_mm'))
    q = [r for r in rows if r['qualified']]
    multi = None
    if mode == 'union' and len(q) >= 2:
        mout = cdir / 'H5_F_union'
        man = run_fuse(spec['observation'], [r['world'] for r in q], f'{case}_H5_F_union', mout)
        mm = man.get('metrics') or {}
        multi = {'manifest': str(mout / 'manifest.json'), 'kind': 'union', 'n_parents': len(q),
                 'parents': [r['parent'] for r in q], 'world_sha': man.get('world_sha'),
                 'mask_iou': mm.get('mask_iou'), 'vis_p95_mm': mm.get('vis_pt_p95_mm'),
                 'freespace': mm.get('freespace_violation'),
                 'volume_m3': man.get('volume_m3'),
                 'hidden_kept_ratio': (man.get('retention') or {}).get('kept_ratio'),
                 'qualified': qualifying(man)[0], 'why': qualifying(man)[1]}
        print(case, 'H5_F_multi', multi['mask_iou'], multi['vis_p95_mm'], multi['qualified'])
    if mode == 'separate':
        multi = {'kind': 'separate_matrix',
                 'hypotheses': [{'id': f"{case}_{r['parent']}", 'world': r['world'],
                                 'manifest': r['manifest'], 'qualified': r['qualified']}
                                for r in rows],
                 'n_hypotheses': len(rows), 'n_qualified': len(q),
                 'note': ('真正的多假设：每个候选各自预演，矩阵为 候选×动作×初态，'
                          '再由 decision.worst-case-risk/v2 统一决策；不合并几何')}
    idx = {'schema': 'multi-parent/v6_1', 'case': case, 'observation': spec['observation'],
           'mode': mode,
           'qualification_rule': {'mask_iou_min': QUAL_IOU_MIN,
                                  'vis_p95_mm_max': QUAL_P95_MM_MAX,
                                  'freespace_max': QUAL_FREESPACE_MAX,
                                  'note': ('三项全过才是规划合格；单项通过只说明该项；'
                                           '不合格候选只作诊断，不进正式 multi 预演')},
           'candidates': rows, 'n_candidates': len(rows), 'n_qualified': len(q),
           'H5_F_multi_definition': multi,
           'not_established': ('multi 只是“多个真实父候选的并集先验”，不等于多个独立观测，'
                               '也不等于更多物体；同源变体不算新样本' if multi else
                               '合格候选不足 2 个，未构建 multi')}
    (cdir / 'index.json').write_text(json.dumps(idx, ensure_ascii=False, indent=2))
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', default='both', choices=['R01', 'R03', 'both'])
    ap.add_argument('--out', default=str(BATCH / 'multi'))
    ap.add_argument('--mode', default='separate', choices=['separate', 'union'],
                    help='separate=每个候选独立资产（真正的多假设矩阵）；union=并集实体（仅作对照）')
    a = ap.parse_args()
    out_root = pathlib.Path(a.out); out_root.mkdir(parents=True, exist_ok=True)
    cases = ['R01', 'R03'] if a.case == 'both' else [a.case]
    for c in cases:
        do_case(c, out_root, a.mode)
    print(json.dumps({'cases': cases, 'out': str(out_root)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
