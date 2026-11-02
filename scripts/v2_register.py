"""可见面配准：只用观测点云与候选网格，做刚体 ICP（不缩放）。

初始化沿用当前"按观测高度缩放 + 平移到 obstacle_x"，随后用观测可见点做
点到面/点到点 ICP，只优化 R,t；输出配准前后残差与位姿。
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import numpy as np, trimesh
from scipy.spatial import cKDTree


def icp(mesh, target, init_T=None, iters=40):
    V = mesh.vertices.copy()
    R = np.eye(3); t = np.zeros(3)
    if init_T is not None:
        R, t = init_T
        V = V @ R.T + t
    tree = cKDTree(target)
    for _ in range(iters):
        d, idx = tree.query(V)
        # 只用最近的一批对应点（后表面本来就没有观测，不能参与对齐）
        keep = d <= np.percentile(d, 60)
        src = V[keep]; dst = target[idx[keep]]
        if len(src) < 10:
            break
        mu_s, mu_d = src.mean(0), dst.mean(0)
        H = (src-mu_s).T @ (dst-mu_d)
        U, S, Vt = np.linalg.svd(H)
        D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
        Rr = Vt.T @ D @ U.T
        tr = mu_d - Rr @ mu_s
        V = V @ Rr.T + tr
        R = Rr @ R; t = Rr @ t + tr
        if np.median(d) < 1e-4:
            break
    # 统一口径：观测点到配准后网格最近顶点的距离
    d2, _ = cKDTree(V).query(target)
    return R, t, V, float(np.median(d2)), float(np.percentile(d2, 95))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True); ap.add_argument('--cands', required=True)
    ap.add_argument('--out', required=True); ap.add_argument('--iters', type=int, default=40)
    a = ap.parse_args()
    obs = ROOT/a.obs
    vis = np.load(obs/'visible_points.npy')
    if len(vis) > 1500:
        vis = vis[np.random.default_rng(0).choice(len(vis), 1500, replace=False)]
    rows = []
    for d in sorted((ROOT/a.cands).glob('*/parent/body.stl')):
        m = trimesh.load(d, force='mesh', process=False)
        before = float(np.median(cKDTree(m.vertices).query(vis)[0]))
        R, t, V, med, p95 = icp(m, vis, iters=a.iters)
        m2 = trimesh.Trimesh(vertices=V, faces=m.faces, process=False)
        outp = d.parent.parent/'registered.stl'; m2.export(outp)
        rec = {'candidate': d.parent.parent.name, 'median_before_mm': round(before*1000, 2),
               'median_after_mm': round(med*1000, 2), 'p95_after_mm': round(p95*1000, 2),
               'R': np.asarray(R).round(4).tolist(), 't': np.asarray(t).round(4).tolist(),
               'registered': str(outp.relative_to(ROOT))}
        rows.append(rec); print(json.dumps({k: rec[k] for k in
                     ('candidate','median_before_mm','median_after_mm','p95_after_mm')}, ensure_ascii=False), flush=True)
    p = ROOT/a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'schema':'v2-register/v1','rows':rows}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
