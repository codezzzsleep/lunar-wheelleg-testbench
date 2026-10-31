"""两视角更新：第一、第二观测都必须约束更新后的候选。

做法：分别用两个观测做观测约束融合，然后取**交集**（trimesh boolean）。
交集只可能让表面后退，不会新增侵入 —— 因此**不能为了拟合第二视角破坏第一视角的一致性**。

  .venv/bin/python scripts/v7_update_two_views.py \
      --obs1 runs/unseen/recovery_r3/obs_R03 \
      --obs2 runs/.../obs_R03_at_driven \
      --parent runs/unseen/delivery_v7/v7_20261030/candidates/V7_R03_s1/world/align \
      --parent-id V7_R03_s1 --out runs/.../fusion_diagnostics/tv_R03_s1

输出：<out>/body.stl（更新后）、update_report.json（两视角指标 + 交集统计）。
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import fuse_observed as FZ
import align


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs1', required=True)
    ap.add_argument('--obs2', required=True)
    ap.add_argument('--parent', required=True)
    ap.add_argument('--parent-id', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--config', default='configs/unseen_v6_1_fusion.json')
    ap.add_argument('--pitch', type=float, default=None)
    ap.add_argument('--reuse', action='store_true',
                    help='若 view1_fusion/view2_fusion 已存在则复用，不重复融合')
    a = ap.parse_args()
    cfg = json.loads((ROOT / a.config).read_text())
    if a.pitch:
        cfg['pitch_m'] = a.pitch
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    tmp1 = out / 'view1_fusion'
    tmp2 = out / 'view2_fusion'
    if not (a.reuse and (tmp1 / 'body.stl').exists()):
        FZ.fuse(str(ROOT / a.obs1), str(ROOT / a.parent), a.parent_id, str(tmp1), cfg)
    if not (a.reuse and (tmp2 / 'body.stl').exists()):
        FZ.fuse(str(ROOT / a.obs2), str(ROOT / a.parent), a.parent_id, str(tmp2), cfg)
    m1 = trimesh.load(str(tmp1 / 'body.stl'), force='mesh', process=False)
    m2 = trimesh.load(str(tmp2 / 'body.stl'), force='mesh', process=False)
    # 布尔引擎要求水密体积，而 marching cubes 出来的融合体不一定水密。
    # 改用**体素求交**：两个融合体各自占据化，取交集再 marching cubes。
    import collision_occupancy_metrics as M
    lo = np.minimum(m1.bounds[0], m2.bounds[0]) - 2 * cfg['pitch_m']
    hi = np.maximum(m1.bounds[1], m2.bounds[1]) + 2 * cfg['pitch_m']
    dims = np.ceil((hi - lo) / cfg['pitch_m']).astype(int) + 1
    xs = lo[0] + (np.arange(dims[0]) + 0.5) * cfg['pitch_m']
    ys = lo[1] + (np.arange(dims[1]) + 0.5) * cfg['pitch_m']
    zs = lo[2] + (np.arange(dims[2]) + 0.5) * cfg['pitch_m']
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    o1 = M.ray_parity(m1, pts).reshape(dims)
    o2 = M.ray_parity(m2, pts).reshape(dims)
    both = o1 & o2
    if int(both.sum()) < 100:
        raise SystemExit(f'两视角交集过小（{int(both.sum())} 体素），拒绝产出空候选')
    inter = trimesh.voxel.ops.matrix_to_marching_cubes(both, pitch=cfg['pitch_m'])
    inter.apply_translation(lo + cfg['pitch_m'] / 2.0)
    if len(inter.faces) == 0:
        raise SystemExit('两视角交集为空（marching cubes 无面）')
    inter.export(out / 'body.stl')
    print(json.dumps({'voxels_view1': int(o1.sum()), 'voxels_view2': int(o2.sum()),
                      'voxels_both': int(both.sum()),
                      'only_view1': int((o1 & ~o2).sum()),
                      'only_view2': int((o2 & ~o1).sum())}, ensure_ascii=False))
    # 两视角验收：交集必须是 m1 的子集，v1 的侵入不应增加
    rep = {'schema': 'two-view-update/v7-r1', 'parent_id': a.parent_id,
           'obs1': a.obs1, 'obs2': a.obs2, 'pitch_m': cfg['pitch_m'],
           'faces': {'view1': int(len(m1.faces)), 'view2': int(len(m2.faces)),
                     'intersection': int(len(inter.faces))},
           'volume_m3': {'view1': round(float(m1.volume), 9),
                         'view2': round(float(m2.volume), 9),
                         'intersection': round(float(inter.volume), 9)},
           'construction': 'intersection(view1_fusion, view2_fusion)'}
    for tag, obs in (('obs1', a.obs1), ('obs2', a.obs2)):
        try:
            ev = align.render_eval(inter, ROOT / obs, want_vis_pt=True)
            rep[tag] = {k: ev.get(k) for k in ('mask_iou', 'vis_pt_p95_mm',
                                               'freespace_violation')}
        except Exception as e:
            rep[tag] = {'error': f'{type(e).__name__}: {e}'}
    rep['passes_both_views'] = all(
        (rep[t].get('mask_iou') or 0) >= 0.90 and (rep[t].get('vis_pt_p95_mm') or 99) <= 5.0
        and (rep[t].get('freespace_violation') or 99) <= 0.05 for t in ('obs1', 'obs2'))
    (out / 'update_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
