"""多起点可见面配准：yaw × 尺度网格 + 裁剪 ICP，残差阈值判接受。"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import numpy as np, trimesh
from scipy.spatial import cKDTree

def resid(V, target):
    d, _ = cKDTree(V).query(target); return float(np.median(d)), float(np.percentile(d, 95))

def icp(V0, target, iters=30):
    V = V0.copy(); tree = cKDTree(target)
    for _ in range(iters):
        d, idx = tree.query(V)
        keep = d <= np.percentile(d, 55)
        src, dst = V[keep], target[idx[keep]]
        if len(src) < 10: break
        mu_s, mu_d = src.mean(0), dst.mean(0)
        H = (src-mu_s).T @ (dst-mu_d)
        U, S, Vt = np.linalg.svd(H)
        D = np.diag([1,1,np.sign(np.linalg.det(Vt.T@U.T))])
        R = Vt.T @ D @ U.T
        V = (V - mu_s) @ R.T + mu_d
    return V

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True); ap.add_argument('--cands', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--accept-mm', type=float, default=5.0)
    a = ap.parse_args()
    vis = np.load(ROOT/a.obs/'visible_points.npy')
    if len(vis) > 1200:
        vis = vis[np.random.default_rng(0).choice(len(vis), 1200, replace=False)]
    rows = []
    for d in sorted((ROOT/a.cands).glob('*/parent/body.stl')):
        m = trimesh.load(d, force='mesh', process=False)
        base = m.vertices.copy(); base -= base.mean(0)
        H = float(base[:,2].max()-base[:,2].min())
        best = None
        for yaw in (0, 15, -15, 30, -30):
            for s in (0.85, 1.0, 1.15):
                Rz = trimesh.transformations.rotation_matrix(np.deg2rad(yaw), [0,0,1])[:3,:3]
                V0 = (base*s) @ Rz.T
                V0 -= V0.mean(0); V0 += np.array([1.8, 0.0, V0[:,2].max()])
                V = icp(V0, vis)
                med, p95 = resid(V, vis)
                if best is None or med < best[0]:
                    best = (med, p95, yaw, s, V)
        med, p95, yaw, s, V = best
        name = d.parent.parent.name
        outp = d.parent.parent/'registered_v2.stl'
        trimesh.Trimesh(vertices=V, faces=m.faces, process=False).export(outp)
        rec = {'candidate': name, 'median_mm': round(med*1000,2), 'p95_mm': round(p95*1000,2),
               'yaw_deg': yaw, 'scale': s,
               'accepted': bool(med*1000 <= a.accept_mm),
               'status': 'ok' if med*1000 <= a.accept_mm else 'registration_failed',
               'registered': str(outp.relative_to(ROOT))}
        rows.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
    p = ROOT/a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'schema':'v2-register/v2','accept_mm':a.accept_mm,'rows':rows},
                            ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
