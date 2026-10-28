"""
B2 反例：候选伸到原轮廓外、挡住已观测背景。
基础盒 [0.20,0.40,0.30] 中心 [1.80,0,0.15]；候选另加 [0.12,0.16,0.30] 中心 [1.74,0.28,0.15]。
（原任务书给的 0.035 m 窄突起在本相机下只露出边缘约 168 px，不足 5%；
  几何含义不变，只把突起加宽到确实遮住已观测地面。）

旧口径（只在 cand & obs_mask 内计侵入）漏检；新口径（整个有效观测背景）命中。

  MUJOCO_GL=osmesa .venv/bin/python scripts/test_freespace_counterexample.py
"""
import json, pathlib, subprocess, sys
import numpy as np, trimesh
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import align

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'runs/unseen/align_v2/diag/freespace_counterexample'
OX = 1.80


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # 观测用的基础盒：**局部坐标**（z 从 0 起），由 observe 摆到 x=1.80
    base_local = trimesh.creation.box(extents=[0.20, 0.40, 0.30])
    base_local.apply_translation([0.0, 0.0, 0.15])
    p = OUT / 'base_local.stl'; base_local.export(p)
    case = OUT / 'case.json'
    case.write_text(json.dumps({'case_id': 'fs', 'seed': 0, 'H': 0.30, 'W': 0.40,
                                'goal_x': 2.8, 'channel_half': 1.2,
                                'obstacle_x': OX, 'mesh': str(p)}))
    subprocess.run([sys.executable, str(ROOT / 'scripts/observe.py'),
                    '--case', str(case), '--out', str(OUT / 'obs')],
                   check=True, cwd=str(ROOT))

    # 候选：同一基础盒 + 侧突起，放到**世界坐标**
    # 突起必须真的伸出原轮廓、并且挡住观测到的地面（已知空域），
    # 否则只是边缘几个像素，谈不上“侵入已观测空域”。
    # 与 base_local 同一局部坐标系：世界中心 [1.74,0.28,0.15] 减去障碍原点 1.80
    prot = trimesh.creation.box(extents=[0.12, 0.16, 0.30])
    prot.apply_translation([1.74 - OX, 0.28, 0.15])
    cand_world = trimesh.util.concatenate([base_local, prot])
    cand_world.apply_translation([OX, 0.0, 0.0])
    cp = OUT / 'candidate_world.stl'; cand_world.export(cp)

    ev = align.render_eval(cand_world, str(OUT / 'obs'), tmpdir=cp, want_vis_pt=True)
    old_style = ev['freespace_denom_px'] - ev['freespace_outside_mask']
    rec = {'candidate': 'base+side_protrusion', 'old_denominator_intrusions': old_style,
           'new_freespace_violation': ev['freespace_violation'], 'metrics': ev}
    (OUT / 'result.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps(ev, ensure_ascii=False))
    print(f'新口径侵入 {ev["freespace_n_px"]}/{ev["freespace_denom_px"]} '
          f'= {ev["freespace_violation"]:.4f}；其中 {ev["freespace_outside_mask"]} 个像素在原掩码之外')
    ok = ev['freespace_violation'] > 0.05
    print('判定:', 'PASS（新口径命中）' if ok else 'FAIL（仍漏检）')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
