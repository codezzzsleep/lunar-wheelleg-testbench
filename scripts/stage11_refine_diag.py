"""从粗候选近正确位姿单独精化，判断 L3 是排序还是精化问题。"""
import json, pathlib, sys
import numpy as np, trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_register as R
def main():
    truth=ROOT/'runs/v3/stage008/truth_v2'; proto=json.loads((ROOT/'plans/v3_protocol.json').read_text())
    obs=R.load_observation(str(truth/'observation'))
    mesh=trimesh.load(str(ROOT/'runs/v3/stage11/registration/candidate_local.stl'),force='mesh',process=False)
    picks,_=R.coarse_search(mesh,obs,proto['registration'],top_k=4)
    rng=np.random.default_rng(0); out={'schema':'refine-diag/v1','starts':[]}
    for i,p in enumerate(picks):
        M,hist=R.refine_icp(mesh,obs,p['M'],proto['registration'],rng)
        M,scan=R.local_polish(mesh,obs,M,proto['registration'])
        ev=R.evaluate_matrix(mesh,obs,M)
        out['starts'].append({'coarse_rank':i,'coarse_iou':p.get('iou'),'refined':ev})
        print(i, p.get('iou'), '->', ev['mask_iou'], ev['depth_median_mm'], flush=True)
    (ROOT/'runs/v3/stage11/registration/refine_diag.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': sys.exit(main())
