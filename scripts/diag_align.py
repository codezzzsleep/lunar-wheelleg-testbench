"""
配准残差诊断：在同一模型、同一世界位姿、同一相机位姿、**原生分辨率**下重渲染，
把误差来源逐步隔离。

  MUJOCO_GL=osmesa .venv/bin/python scripts/diag_align.py \
      --obs runs/unseen/obs/planA --mesh runs/unseen/gate_p/planA/mesh/s7_h21_w34_drop.stl \
      --out runs/unseen/align/diag_A

四组对照（每组只改变一个因素）：
  S0 同场景同路径重渲染（mesh_file + target_height_m，与 observe.py 完全一致）
  S1 只换成"导出 STL 再重新加载"（网格往返）
  S2 只换成"手工世界位姿放置"（姿态/放置路径）
  S3 只换成 640×480 分辨率（分辨率）

输出：有符号残差图、中位数、P95、边缘/内部误差、掩码 IoU，逐项对比。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import trimesh
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
EDGE_PX = 3


def build_env(obs_dir, objects, W, H, cam_pose):
    obsd = json.loads((pathlib.Path(obs_dir) / 'observation.json').read_text())
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.8, name='diag')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['objects'] = objects
    spec['front_cam'] = {'pos': cam_pose, 'pitch_deg': obsd['camera']['pitch_deg'],
                         'fovy': obsd['camera']['fovy']}
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    mujoco.mj_forward(m, d)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    return env, m, d, cid, obsd


def render_depth(m, d, cid, W, H):
    r = mujoco.Renderer(m, H, W)
    r.enable_depth_rendering()
    r.update_scene(d, camera=cid)
    dep = r.render().copy()
    r.disable_depth_rendering()
    return dep


def mask_of_candidate(m, d, cid, W, H):
    """把障碍移走再渲一次，深度差异即候选轮廓。"""
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    with_obj = render_depth(m, d, cid, W, H)
    keep = m.body_pos[bid].copy()
    m.body_pos[bid] = [0.0, 0.0, -80.0]
    mujoco.mj_forward(m, d)
    without = render_depth(m, d, cid, W, H)
    m.body_pos[bid] = keep
    mujoco.mj_forward(m, d)
    return with_obj, (with_obj < without - 1e-3), without


def _edge_mask(mask, k=EDGE_PX):
    """不依赖 scipy 的边缘带：掩码 XOR 平移 k 次后的掩码。"""
    m = mask.copy()
    inner = mask.copy()
    for _ in range(k):
        inner = (inner & np.roll(inner, 1, 0) & np.roll(inner, -1, 0)
                 & np.roll(inner, 1, 1) & np.roll(inner, -1, 1))
    return m & ~inner


def stats(resid, mask, name):
    """残差统计：中位、P95、RMS，以及边缘/内部拆分。"""
    if mask.sum() < 20:
        return {'name': name, 'n_px': int(mask.sum()), 'note': '掩码过小'}
    r = resid[mask]
    edge = _edge_mask(mask)
    inner = mask & ~edge
    out = {
        'name': name, 'n_px': int(mask.sum()),
        'n_edge': int(edge.sum()), 'n_inner': int(inner.sum()),
        'median_mm': round(float(np.median(r)) * 1000, 2),
        'p95_mm': round(float(np.percentile(np.abs(r), 95)) * 1000, 2),
        'rms_mm': round(float(np.sqrt(np.mean(r ** 2))) * 1000, 2),
        'signed_mean_mm': round(float(np.mean(r)) * 1000, 2),
        'max_abs_mm': round(float(np.max(np.abs(r))) * 1000, 2),
        'frac_over_10mm': round(float(np.mean(np.abs(r) > 0.010)), 4),
        'frac_over_100mm': round(float(np.mean(np.abs(r) > 0.100)), 4),
    }
    if edge.sum() >= 10:
        out['edge_rms_mm'] = round(float(np.sqrt(np.mean(resid[edge] ** 2))) * 1000, 2)
        out['inner_rms_mm'] = round(float(np.sqrt(np.mean(resid[inner] ** 2))) * 1000, 2) \
            if inner.sum() >= 10 else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True)
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--case', default=None, help='case json，含 obstacle_x / H')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    obs_dir = pathlib.Path(a.obs)
    obsd = json.loads((obs_dir / 'observation.json').read_text())
    W0, H0 = obsd['image']['W'], obsd['image']['H']
    obs_dep = np.load(obs_dir / 'depth.npy')
    from PIL import Image as _I
    obs_mask = np.array(_I.open(obs_dir / 'mask.png').convert('L')) > 127
    cam_pose = obsd['camera']['pos_body']
    vis = obsd['visible']
    case = json.loads(pathlib.Path(a.case).read_text()) if a.case else {}
    ox = float(case.get('obstacle_x', 1.8))
    Hobj = float(case.get('H', vis['H_vis']))

    rows = []
    # ---- S0：同场景同路径（与 observe.py 完全一致）----
    objs = [{'mesh_file': str(pathlib.Path(a.mesh).resolve()), 'x': ox, 'y': 0.0,
             'yaw_deg': 0.0, 'target_height_m': Hobj}]
    env, m, d, cid, _ = build_env(obs_dir, objs, W0, H0, cam_pose)
    dep0, mask0, _ = mask_of_candidate(m, d, cid, W0, H0)
    resid0 = dep0 - obs_dep
    rows.append(stats(resid0, mask0 & obs_mask, 'S0 同场景同路径 @原生 %dx%d' % (W0, H0)))
    iou0 = (mask0 & obs_mask).sum() / max(1, (mask0 | obs_mask).sum())
    rows[-1]['iou'] = round(float(iou0), 4)
    np.save(out / 'resid_S0.npy', resid0.astype(np.float32))

    # ---- S1：网格往返（导出 STL 再加载）----
    mm = trimesh.load(str(pathlib.Path(a.mesh).resolve()), force='mesh')
    rt = out / 'roundtrip.stl'; mm.export(rt)
    objs1 = [{'mesh_file': str(rt), 'x': ox, 'y': 0.0, 'yaw_deg': 0.0,
              'target_height_m': Hobj}]
    env, m, d, cid, _ = build_env(obs_dir, objs1, W0, H0, cam_pose)
    dep1, mask1, _ = mask_of_candidate(m, d, cid, W0, H0)
    rows.append(stats(dep1 - obs_dep, mask1 & obs_mask, 'S1 网格往返 @原生'))
    rows[-1]['iou'] = round(float((mask1 & obs_mask).sum() / max(1, (mask1 | obs_mask).sum())), 4)

    # ---- S2：手工世界位姿放置（posed 路径）----
    b = mm.bounds
    M = np.eye(4)
    M[:3, 3] = [vis['x_front'] - b[0][0], -(b[0][1] + b[1][1]) / 2, -b[0][2]]
    mw = trimesh.Trimesh((M[:3, :3] @ np.asarray(mm.vertices).T).T + M[:3, 3],
                         np.asarray(mm.faces), process=False)
    pd = out / 'posed'; pd.mkdir(exist_ok=True)
    mw.export(pd / 'mesh.stl')
    (pd / 'manifest.json').write_text(json.dumps({'parts': ['mesh.stl']}))
    objs2 = [{'posed_dir': str(pd), 'x': 0.0, 'y': 0.0, 'yaw_deg': 0.0,
              'target_height_m': None}]
    env, m, d, cid, _ = build_env(obs_dir, objs2, W0, H0, cam_pose)
    dep2, mask2, _ = mask_of_candidate(m, d, cid, W0, H0)
    rows.append(stats(dep2 - obs_dep, mask2 & obs_mask, 'S2 手工位姿(posed) @原生'))
    rows[-1]['iou'] = round(float((mask2 & obs_mask).sum() / max(1, (mask2 | obs_mask).sum())), 4)

    # ---- S3：分辨率降到 640×480（其余与 S0 相同）----
    W1, H1 = 640, 480
    env, m, d, cid, _ = build_env(obs_dir, objs, W1, H1, cam_pose)
    dep3, mask3, _ = mask_of_candidate(m, d, cid, W1, H1)
    from PIL import Image as I
    obs_dep_s = np.array(I.fromarray(obs_dep.astype(np.float32), mode='F')
                         .resize((W1, H1), I.NEAREST))
    obs_mask_s = np.array(I.open(obs_dir / 'mask.png').convert('L')
                          .resize((W1, H1), I.NEAREST)) > 127
    rows.append(stats(dep3 - obs_dep_s, mask3 & obs_mask_s, 'S3 降到 640x480'))
    rows[-1]['iou'] = round(float((mask3 & obs_mask_s).sum()
                                  / max(1, (mask3 | obs_mask_s).sum())), 4)

    (out / 'diag.json').write_text(json.dumps(
        {'obs': str(obs_dir), 'mesh': str(a.mesh), 'native': [W0, H0], 'rows': rows},
        indent=2, ensure_ascii=False))
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    print(f'-> {out/"diag.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
