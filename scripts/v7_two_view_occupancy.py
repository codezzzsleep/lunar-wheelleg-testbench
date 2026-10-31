"""两视角更新直接约束**同一份世界占据**（任务书 §三）。

    O = (P ∪ S1 ∪ S2) \\ (F1 ∪ F2)

- P：父候选占据（parent_solid，与融合一致）
- S_i：第 i 个视角在测量邻域内的表面壳（有上下界）
- F_i：第 i 个视角明确观测到的自由空间
- 两个视角都未知的区域保持 P（父先验），不会被填实也不会被删掉

与旧版（各自融合→取体素交）的区别：这里只有一个网格、一次占据化，
没有"网格→读回→再占据化"的往返。旧版产物保留，不覆盖。

冲突诊断：S1 ∩ F2 与 S2 ∩ F1 的体素数会在报告里单独列出，不做阈值掩盖。

  /opt/lunar/bin/python scripts/v7_two_view_occupancy.py \
      --obs1 <obs1> --obs2 <obs2> --parent <align> --parent-id V7_R03_s1 \
      --pitch 0.0025 --out <dir>
"""
import argparse, hashlib, json, pathlib, sys
import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import fuse_observed as FZ


def sha_dir(d):
    return FZ._sha_dir(pathlib.Path(d))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs1', required=True)
    ap.add_argument('--obs2', required=True)
    ap.add_argument('--parent', required=True)
    ap.add_argument('--parent-id', required=True)
    ap.add_argument('--pitch', type=float, default=None)
    ap.add_argument('--config', default='configs/unseen_v7_r1_fusion_offset1.json')
    ap.add_argument('--edge-thr', type=float, default=0.02,
                    help='深度不连续阈值；0 表示不做不连续剔除（自由空间用精确深度，更激进地挖）')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    cfg = json.loads((ROOT / a.config).read_text())
    pitch = float(a.pitch or cfg['pitch_m'])
    free_eps = float(cfg.get('free_eps_m', 0.001))
    band = float(cfg.get('band_m', 0.0075))

    parent = FZ._load_mesh(ROOT / a.parent / 'body.stl')
    vis1 = np.load(ROOT / a.obs1 / 'visible_points.npy')
    vis2 = np.load(ROOT / a.obs2 / 'visible_points.npy')
    vis = np.vstack([vis1, vis2])
    grid = FZ.make_grid(parent, vis, pitch, int(cfg.get('margin_cells', 3)))

    P, pstats = FZ.parent_solid(parent, grid, 1)
    off = float(cfg.get('shell_offset_voxels', 0.5)) * pitch
    ethr = None if float(a.edge_thr) <= 0 else float(a.edge_thr)
    space1, st1 = FZ.classify_space(ROOT / a.obs1, grid, free_eps, band, edge_thr=ethr, offset_m=off)
    space2, st2 = FZ.classify_space(ROOT / a.obs2, grid, free_eps, band, edge_thr=ethr, offset_m=off)
    S1, F1 = (space1 == 1), (space1 == 2)
    S2, F2 = (space2 == 1), (space2 == 2)

    occ = (P | S1 | S2) & ~(F1 | F2)
    occ, ncomp = FZ.largest_component(occ)

    conflict = {'shell1_into_free2': int((S1 & F2).sum()),
                'shell2_into_free1': int((S2 & F1).sum()),
                'free1_free2_agree': int((F1 & F2).sum()),
                'unknown_both': int(((space1 == 0) & (space2 == 0)).sum()),
                'parent_kept_where_unknown': int((P & (space1 == 0) & (space2 == 0)).sum()),
                'carved_by_free1': int((P & F1).sum()), 'carved_by_free2': int((P & F2).sum())}

    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    content_sha = hashlib.sha256(np.ascontiguousarray(occ).tobytes()).hexdigest()
    tmp = out / 'occ.npz.tmp.npz'
    np.savez_compressed(
        tmp, occupied=occ.astype(bool),
        origin=np.asarray(grid['origin'], dtype=float),
        pitch=np.float64(pitch), dims=np.asarray(occ.shape, dtype=int),
        convention=np.array('voxel_center = origin + (index + 0.5) * pitch'),
        algorithm=np.array('two-view-occupancy/v1  O=(P|S1|S2)&~(F1|F2)'),
        parent_id=np.array(str(a.parent_id)),
        obs1_sha=np.array(sha_dir(ROOT / a.obs1)),
        obs2_sha=np.array(sha_dir(ROOT / a.obs2)),
        config_sha=np.array(hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()),
        content_sha=np.array(content_sha))
    tmp.replace(out / 'occ.npz')

    mesh = FZ.marching_tets(occ, grid)
    if len(mesh.faces) == 0:
        raise SystemExit('两视角占据没有面')
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_normals(mesh)
    mesh.export(out / 'body.stl')

    rep = {'schema': 'two-view-occupancy/v1', 'parent_id': a.parent_id,
           'obs1': a.obs1, 'obs2': a.obs2, 'pitch_m': pitch,
           'occupancy': {'n_voxels': int(occ.size), 'n_occupied': int(occ.sum()),
                         'content_sha': content_sha,
                         'parent_voxels': int(P.sum()),
                         'shell1': int(S1.sum()), 'shell2': int(S2.sum()),
                         'free1': int(F1.sum()), 'free2': int(F2.sum())},
           'conflict': conflict,
           'space_stats': {'obs1': st1, 'obs2': st2},
           'parent_stats': pstats,
           'mesh': {'faces': int(len(mesh.faces)), 'watertight': bool(mesh.is_watertight),
                    'volume_m3': float(abs(mesh.volume)) if mesh.is_watertight else None},
           'formula': 'O = (P | S1 | S2) & ~(F1 | F2)', 'shell_offset_m': off, 'edge_thr': a.edge_thr}
    (out / 'two_view_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'answer': {'occupancy': rep['occupancy']['n_occupied'],
                                 'conflict': conflict,
                                 'faces': rep['mesh']['faces'],
                                 'watertight': rep['mesh']['watertight']}},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
