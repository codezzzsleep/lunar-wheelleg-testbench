"""验证 evaluate 的度量层：用三角形 z-buffer 光栅化替代点云栅格，比较同一正确位姿。"""
import json, pathlib, sys
import numpy as np, trimesh
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_register as R, camera_io

def rasterize(mesh, cam, W, H, M=None):
    V = np.asarray(mesh.vertices, float)
    if M is not None:
        V = V @ M[:3, :3].T + M[:3, 3]
    u, v, z = camera_io.project(V, cam)
    depth = np.full((H, W), np.inf)
    mask = np.zeros((H, W), bool)
    for tri in mesh.faces:
        xs, ys, zs = u[tri], v[tri], z[tri]
        if not (np.all(np.isfinite(xs)) and np.all(np.isfinite(ys))):
            continue
        if np.any(zs <= 0):
            continue
        x0, x1 = int(np.floor(max(0, xs.min()))), int(np.ceil(min(W - 1, xs.max())))
        y0, y1 = int(np.floor(max(0, ys.min()))), int(np.ceil(min(H - 1, ys.max())))
        if x1 < x0 or y1 < y0:
            continue
        xg, yg = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (xs[1] - xs[0]) * (ys[2] - ys[0]) - (xs[2] - xs[0]) * (ys[1] - ys[0])
        if abs(d) < 1e-12:
            continue
        w0 = ((xs[1] - xg) * (ys[2] - yg) - (xs[2] - xg) * (ys[1] - yg)) / d
        w1 = ((xs[2] - xg) * (ys[0] - yg) - (xs[0] - xg) * (ys[2] - yg)) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        zz = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
        ys_i, xs_i = np.nonzero(inside)
        yy = y0 + ys_i; xx = x0 + xs_i
        cur = depth[yy, xx]
        better = zz[inside] < cur
        depth[yy[better], xx[better]] = zz[inside][better]
        mask[yy[better], xx[better]] = True
    return mask, depth

def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    out = ROOT / 'runs/v3/stage11/metric'; out.mkdir(parents=True, exist_ok=True)
    obs = R.load_observation(str(truth / 'observation'))
    world = trimesh.load(str(truth / 'truth/body_world.stl'), force='mesh', process=False)
    H, W = obs['mask'].shape
    mask, depth = rasterize(world, obs['camera'], W, H)
    iou = float((mask & obs['mask']).sum()) / max(1, int((mask | obs['mask']).sum()))
    both = mask & obs['mask'] & np.isfinite(depth) & np.isfinite(obs['depth'])
    dd = np.abs(depth[both] - obs['depth'][both]) * 1000
    rep = {'schema': 'metric-check/v1',
           'pose': 'identity (truth mesh already in world frame)',
           'triangle_raster': {'mask_iou': round(iou, 4),
                               'n_pixels': int(mask.sum()), 'n_mask': int(obs['mask'].sum()),
                               'depth_median_mm': round(float(np.median(dd)), 3),
                               'depth_p95_mm': round(float(np.percentile(dd, 95)), 3)},
           'point_splat_eval': R.evaluate_matrix(world, obs, np.eye(4)),
           'camera': obs['camera'], 'intrinsics': obs['K']}
    (out / 'metric_check.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep['triangle_raster'], ensure_ascii=False))
    return 0

if __name__ == '__main__':
    sys.exit(main())
