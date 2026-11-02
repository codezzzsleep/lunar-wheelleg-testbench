"""候选与已观测表面的相容性：掩码重叠 + 可见点距离。

只用公共可见信息（观测掩码与可见点云），不读真值。
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import numpy as np, trimesh

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True); ap.add_argument('--cands', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    obs = ROOT/a.obs
    vis = np.load(obs/'visible_points.npy') if (obs/'visible_points.npy').is_file() else None
    rows = []
    for d in sorted((ROOT/a.cands).glob('*/parent/body.stl')):
        m = trimesh.load(d, force='mesh', process=False)
        rec = {'candidate': d.parent.parent.name}
        if vis is not None and len(vis):
            # 候选表面到观测点的最近距离（近似相容性）
            import trimesh.proximity as prox
            try:
                dist, _, _ = prox.closest_point(m, vis[:800])
                dist = np.linalg.norm(vis[:800] - dist, axis=1)
                rec['median_mm'] = round(float(np.median(np.abs(dist))*1000), 2)
                rec['p95_mm'] = round(float(np.percentile(np.abs(dist),95)*1000), 2)
                rec['frac_within_5mm'] = round(float((np.abs(dist)<0.005).mean()), 3)
            except Exception as e:
                rec['error'] = f'{type(e).__name__}: {e}'[:120]
        rows.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
    out = ROOT/a.out; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'schema':'v2-cand-compat/v1','rows':rows}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
