"""用三角形光栅复核三层：同一正确位姿/恢复位姿/粗搜索位姿。"""
import json, pathlib, sys
import numpy as np, trimesh
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_register as R
from stage11_metric import rasterize

def metrics(mesh_world, obs, M):
    H, W = obs['mask'].shape
    mask, depth = rasterize(mesh_world, obs['camera'], W, H, M)
    iou = float((mask & obs['mask']).sum()) / max(1, int((mask | obs['mask']).sum()))
    both = mask & obs['mask'] & np.isfinite(depth) & np.isfinite(obs['depth'])
    dd = np.abs(depth[both] - obs['depth'][both]) * 1000
    return {'mask_iou': round(iou, 4), 'depth_median_mm': round(float(np.median(dd)), 3),
            'depth_p95_mm': round(float(np.percentile(dd, 95)), 3)}

def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    obs = R.load_observation(str(truth / 'observation'))
    world = trimesh.load(str(truth / 'truth/body_world.stl'), force='mesh', process=False)
    local = trimesh.load(str(ROOT / 'runs/v3/stage11/registration/candidate_local.stl'), force='mesh', process=False)
    lay = json.loads((ROOT / 'runs/v3/stage11/registration/layers.json').read_text())
    out = {'schema': 'reg-layers-metric/v1', 'layers': {}}
    out['layers']['1_identity'] = metrics(world, obs, np.eye(4))
    M2 = np.asarray(lay['layers']['2_known_init']['M_recovered'], float)
    out['layers']['2_known_init'] = metrics(local, obs, M2)
    M3 = np.asarray(lay['layers']['3_normal_coarse']['M_recovered'], float)
    out['layers']['3_normal_coarse'] = metrics(local, obs, M3)
    (ROOT / 'runs/v3/stage11/registration/layers_metric.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    sys.exit(main())
