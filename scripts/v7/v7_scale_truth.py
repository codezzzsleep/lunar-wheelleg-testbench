"""尺寸比的真值检查：把场景里真实石头的网格当作候选，用两种尺寸比打分。

正确的指标应给真实石头打 1.000 左右。v5 原定义在深度掩码下会偏高（E1 1.057，E2 1.113）。

    MUJOCO_GL=egl python3 scripts/v7/v7_scale_truth.py --run runs/v7/route_full_r2
（需要该运行目录里每个遭遇的 decide_look*/fusion/V.npz 与 look*/state.json）
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(HERE))
import v5_core as VC, v5_metrics_ref as R, v7_encounter as VE, v7_route as VRt  # noqa: E402

BODY = {'E1': 'obstacle16', 'E2': 'obstacle17'}


def rock_world(env, body):
    import mujoco
    m, d = env.model, env.data; mujoco.mj_forward(m, d)
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, body); parts = []
    for g in range(m.ngeom):
        if m.geom_bodyid[g] == bid and m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
            mid = m.geom_dataid[g]; va, vn, fa, fn = m.mesh_vertadr[mid], m.mesh_vertnum[mid], m.mesh_faceadr[mid], m.mesh_facenum[mid]
            parts.append(trimesh.Trimesh(m.mesh_vert[va:va + vn] @ d.geom_xmat[g].reshape(3, 3).T + d.geom_xpos[g], m.mesh_face[fa:fa + fn], process=False))
    return trimesh.util.concatenate(parts)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--run', required=True); a = ap.parse_args()
    run = (ROOT / a.run).resolve()
    spec, _ = VRt.route_spec(ROOT / 'runs/v7/_scene_tmp'); env = VRt.make_env(spec)      # 场景与路线相同；不往原运行目录写文件
    out = []
    for enc in ('E1', 'E2'):
        for look in ('look1', 'look2'):
            vp = run / enc / f'decide_{look}' / 'fusion' / 'V.npz'
            if not vp.exists():
                continue
            lf = json.loads((run / enc / look / 'state.json').read_text())['local_frame']
            c, s = np.cos(-lf['yaw0']), np.sin(-lf['yaw0'])
            T = np.eye(4); T[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]; T[:3, 3] = -T[:3, :3] @ np.array([lf['x0'], lf['y0'], 0.0])
            tm = rock_world(env, BODY[enc]); tm.apply_transform(T)
            V = dict(np.load(vp)); g = VC.grid_from_V(V)
            r = {'encounter': enc, 'look': look, 'v5_scale_ratio': VC.admission_metrics(tm, None, V, g, None)['scale_ratio'],
                 'v72_scale_ratio': VE.scale_ratio_ground(R.column_fill_top(tm, g), V, g)}
            out.append(r); print(json.dumps(r))
    (run / 'scale_truth_v72.json').write_text(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
