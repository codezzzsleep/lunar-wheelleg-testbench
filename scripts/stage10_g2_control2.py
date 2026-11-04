"""G2 公平正对照：真值网格放入任意局部系（0.37 尺度 + -11° yaw），走同一入口恢复世界位姿。"""
import json, pathlib, sys
import numpy as np, trimesh
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_register

def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    out = ROOT / 'runs/v3/stage010/g2_control2'; out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    W = trimesh.load(str(truth / 'truth/body_world.stl'), force='mesh', process=False)
    P = np.asarray(W.vertices, float)
    S = 0.37
    a = np.deg2rad(-11.0)
    A = S * np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    b = P.mean(0) - A @ P.mean(0)
    local = (P - b) @ np.linalg.inv(A).T
    cand = trimesh.Trimesh(local, W.faces, process=False)
    lp = out / 'candidate_local.stl'; cand.export(lp)
    M_known = np.eye(4); M_known[:3, :3] = A; M_known[:3, 3] = b
    rec = v3_register.register(str(lp), str(truth / 'observation'), proto, out, top_k=8)
    M = np.asarray(rec['M'], float)
    # 在候选点集上比较已知/恢复变换
    pts = local
    Xk = pts @ M_known[:3, :3].T + M_known[:3, 3]
    Xr = pts @ M[:3, :3].T + M[:3, 3]
    err = np.linalg.norm(Xk - Xr, axis=1)
    Rk = M_known[:3, :3] / np.cbrt(np.linalg.det(M_known[:3, :3]))
    Rr = M[:3, :3] / np.cbrt(np.linalg.det(M[:3, :3]))
    ang = float(np.degrees(np.arccos(np.clip((np.trace(Rk.T @ Rr) - 1) / 2, -1, 1))))
    sk = np.cbrt(np.linalg.det(M_known[:3, :3])); sr = np.cbrt(np.linalg.det(M[:3, :3]))
    rep = {'schema': 'g2-positive-control2/v1',
           'setup': {'local_scale': S, 'local_yaw_deg': -11.0},
           'known_M': M_known.tolist(), 'recovered_M': M.tolist(),
           'rotation_error_deg': round(ang, 3),
           'scale_recovered': round(float(sr), 6), 'scale_known': round(float(sk), 6),
           'scale_error_pct': round(float(100 * abs(sr - sk) / sk), 3),
           'translation_error_m': round(float(np.linalg.norm(Xk.mean(0) - Xr.mean(0))), 5),
           'surface_error_median_mm': round(float(np.median(err)) * 1000, 3),
           'surface_error_p95_mm': round(float(np.percentile(err, 95)) * 1000, 3),
           'diagnostics': rec['best']['diagnostics'],
           'pass': bool(ang <= 3.0 and abs(sr - sk) / sk <= 0.02
                        and np.linalg.norm(Xk.mean(0) - Xr.mean(0)) <= 0.02)}
    (out / 'control2.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    sys.exit(main())
