"""各向异性相似配准：逐轴尺度 + yaw + 平移，最小化可见面残差。"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import numpy as np, trimesh
from scipy.spatial import cKDTree

def fit(cand_v, vis, yaw_deg):
    R = trimesh.transformations.rotation_matrix(np.deg2rad(yaw_deg), [0,0,1])[:3,:3]
    V = cand_v @ R.T
    lo, hi = V.min(0), V.max(0); vlo, vhi = vis.min(0), vis.max(0)
    s = np.where((hi-lo) > 1e-6, (vhi-vlo)/np.maximum(hi-lo, 1e-6), 1.0)
    s = np.clip(s, 0.4, 2.5)
    V = V * s
    V = V - V.mean(0) + vis.mean(0)
    d, _ = cKDTree(V).query(vis)
    return float(np.median(d)), float(np.percentile(d,95)), s, R

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True); ap.add_argument('--cands', required=True)
    ap.add_argument('--out', required=True); ap.add_argument('--accept-mm', type=float, default=5.0)
    a = ap.parse_args()
    vis = np.load(ROOT/a.obs/'visible_points.npy')
    if len(vis) > 1500:
        vis = vis[np.random.default_rng(0).choice(len(vis), 1500, replace=False)]
    rows = []
    for d in sorted((ROOT/a.cands).glob('*/parent/body.stl')):
        m = trimesh.load(d, force='mesh', process=False)
        V0 = m.vertices - m.vertices.mean(0)
        best = None
        for yaw in range(-180, 180, 15):
            med, p95, s, R = fit(V0, vis, yaw)
            if best is None or med < best[0]:
                best = (med, p95, yaw, s, R)
        med, p95, yaw, s, R = best
        name = d.parent.parent.name
        rec = {'candidate': name, 'median_mm': round(med*1000,2), 'p95_mm': round(p95*1000,2),
               'yaw_deg': yaw, 'scale': np.round(s,3).tolist(),
               'accepted': bool(med*1000 <= a.accept_mm),
               'status': 'ok' if med*1000 <= a.accept_mm else 'registration_failed'}
        rows.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
    p = ROOT/a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'schema':'v2-register/v3','rows':rows}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
