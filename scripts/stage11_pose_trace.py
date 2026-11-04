"""记录两个粗候选在 M0/ICP/polish 三步的位姿与观测指标（同一三角光栅）。"""
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
    rng=np.random.default_rng(0); out={'schema':'pose-trace/v1','starts':[]}
    for i in (0,2):
        p=picks[i]; rec={'coarse_rank':i,'M0':np.asarray(p['M']).tolist(),
                         'M0_metrics':R.evaluate_matrix(mesh,obs,p['M'])}
        M,hist=R.refine_icp(mesh,obs,p['M'],proto['registration'],rng)
        rec['M_icp']=M.tolist(); rec['M_icp_metrics']=R.evaluate_matrix(mesh,obs,M)
        M2,pol=R.local_polish(mesh,obs,M,proto['registration'])
        rec['M_polish']=M2.tolist(); rec['M_polish_metrics']=R.evaluate_matrix(mesh,obs,M2)
        rec['polish_summary']=pol
        out['starts'].append(rec)
        print(i, rec['M0_metrics']['mask_iou'], rec['M0_metrics']['depth_median_mm'], '->',
              rec['M_icp_metrics']['mask_iou'], rec['M_icp_metrics']['depth_median_mm'], '->',
              rec['M_polish_metrics']['mask_iou'], rec['M_polish_metrics']['depth_median_mm'], flush=True)
    (ROOT/'runs/v3/stage11/registration/pose_trace.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': sys.exit(main())
