"""配准三层定位：不调 ICP 参数。"""
import json, hashlib, pathlib, sys
import numpy as np, trimesh
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_register as R

def sha(p):
    h=hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()

def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    out = ROOT / 'runs/v3/stage11/registration'; out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    obs = R.load_observation(str(truth / 'observation'))
    rep = {'schema':'reg-layers/v1','observation':str(truth/'observation'),
           'observation_sha256': sha(truth/'observation'/'observation.json'),
           'camera': obs.get('camera', {}), 'layers': {}}
    # Layer 1: 真值网格已在世界系，直接 evaluate（无搜索/优化）
    world = trimesh.load(str(truth/'truth/body_world.stl'), force='mesh', process=False)
    M1 = np.eye(4)
    ev1 = R.evaluate_matrix(world, obs, M1)
    rep['layers']['1_direct_eval_identity'] = {'M': M1.tolist(), 'metrics': ev1,
        'input_sha256': sha(truth/'truth/body_world.stl')}
    print('L1', json.dumps(ev1), flush=True)
    # Layer 2: 任意局部系 + coarse=M_known 启动
    P = np.asarray(world.vertices, float); S=0.37; a=np.deg2rad(-11.0)
    A = S*np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1]])
    b = P.mean(0) - A @ P.mean(0)
    localP = (P-b) @ np.linalg.inv(A).T
    lp = out/'candidate_local.stl'; trimesh.Trimesh(localP, world.faces, process=False).export(lp)
    M_known = np.eye(4); M_known[:3,:3]=A; M_known[:3,3]=b
    ev_known = R.evaluate_matrix(trimesh.Trimesh(localP, world.faces, process=False), obs, M_known)
    rec2 = R.register(str(lp), str(truth/'observation'), proto, out/'layer2', coarse=M_known, top_k=1)
    M2 = np.asarray(rec2['M'], float)
    Xk = localP @ M_known[:3,:3].T + M_known[:3,3]
    Xr = localP @ M2[:3,:3].T + M2[:3,3]
    err = np.linalg.norm(Xk-Xr, axis=1)
    rep['layers']['2_known_init'] = {'M_known': M_known.tolist(), 'M_recovered': M2.tolist(),
        'metrics_at_known': ev_known, 'metrics_recovered': rec2['best']['diagnostics'],
        'surface_median_mm': round(float(np.median(err))*1000,3),
        'surface_p95_mm': round(float(np.percentile(err,95))*1000,3),
        'translation_error_m': round(float(np.linalg.norm(Xk.mean(0)-Xr.mean(0))),5)}
    print('L2', json.dumps(rep['layers']['2_known_init'], ensure_ascii=False)[:400], flush=True)
    # Layer 3: 正常粗搜索
    rec3 = R.register(str(lp), str(truth/'observation'), proto, out/'layer3', top_k=8)
    M3 = np.asarray(rec3['M'], float)
    X3 = localP @ M3[:3,:3].T + M3[:3,3]
    err3 = np.linalg.norm(Xk-X3, axis=1)
    rep['layers']['3_normal_coarse'] = {'M_recovered': M3.tolist(),
        'metrics': rec3['best']['diagnostics'], 'n_coarse_evaluated': rec3.get('n_coarse_evaluated'),
        'n_refined': rec3.get('n_refined'),
        'surface_median_mm': round(float(np.median(err3))*1000,3),
        'surface_p95_mm': round(float(np.percentile(err3,95))*1000,3)}
    print('L3', json.dumps(rep['layers']['3_normal_coarse'], ensure_ascii=False)[:400], flush=True)
    (out/'layers.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0

if __name__=='__main__':
    sys.exit(main())
