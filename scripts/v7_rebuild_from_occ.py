"""从占据实体重建显示网格（演示包第一步）。

  python scripts/v7_rebuild_from_occ.py --occ <occ.npz> --out <dir>
"""
import argparse, json, pathlib, sys
import numpy as np, trimesh
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import fuse_observed as FZ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--occ', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    z = np.load(a.occ, allow_pickle=False)
    occ = np.asarray(z['occupied'], dtype=bool)
    grid = {'origin': np.asarray(z['origin'], dtype=float),
            'pitch': float(z['pitch']), 'dims': occ.shape}
    mesh = FZ.marching_tets(occ, grid)
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_normals(mesh)
    out = ROOT / a.out; out.mkdir(parents=True, exist_ok=True)
    mesh.export(out / 'body.stl')
    rep = {'schema': 'rebuild-from-occ/v1', 'occ': a.occ,
           'convention': str(z['convention']), 'algorithm': str(z['algorithm']),
           'content_sha': str(z['content_sha']),
           'n_occupied': int(occ.sum()), 'faces': int(len(mesh.faces)),
           'watertight': bool(mesh.is_watertight),
           'volume_m3': float(abs(mesh.volume)) if mesh.is_watertight else None}
    (out / 'rebuild_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False))


if __name__ == '__main__':
    main()
