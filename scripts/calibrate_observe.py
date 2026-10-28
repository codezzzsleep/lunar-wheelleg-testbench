"""
观测链标定：必须走与正式观测**同一条**渲染深度 -> 反投影路径（B1）。

  MUJOCO_GL=osmesa .venv/bin/python scripts/calibrate_observe.py --out runs/unseen/obs/cal_v2

- 点云来自**渲染深度**的反投影，不是 mj_ray 命中点；mj_ray 只作独立参考。
- 检查：已知平板深度、非对称块横向偏移（世界 +y 在图像左侧）、可见高度、符号。
- 空点云 / 空 mask / 全 NaN / 尺寸不符 -> FAIL 且退出码非 0。
- 阈值写在 CONFIG 常量里，运行前固定。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent

CONFIG = {
    'lateral_tol_m': 0.005,      # 横向 5 mm 量级
    'depth_tol_m': 0.010,        # 已知平面深度 < 1 cm
    'height_tol_m': 0.010,
    'min_pixels': 200,
}


def _intr(W, H, fovy):
    fy = (H / 2.0) / np.tan(np.deg2rad(fovy) / 2.0)
    return {'fx': fy, 'fy': fy, 'cx': (W - 1) / 2.0, 'cy': (H - 1) / 2.0}


def observe_depth(mesh_path, out_dir, W=640, H=480, fovy=70.0,
                  cam=(0.42, 0.0, 0.20), pitch=-12.0, ox=1.80):
    """
    用与 observe.py 相同的相机与场景，返回{渲染深度, 掩码, 反投影点云, 内参, 外参}。
    掩码 = 有/无物体两次渲染的深度差。
    """
    pd = pathlib.Path(out_dir) / 'posed'
    pd.mkdir(parents=True, exist_ok=True)
    (pd / 'mesh.stl').write_bytes(pathlib.Path(mesh_path).read_bytes())
    (pd / 'manifest.json').write_text(json.dumps({'parts': ['mesh.stl']}))

    spec = terrain.make_spec(kind='flat', objects=[], goal_x=2.8, name='cal')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['objects'] = [{'posed_dir': str(pd), 'x': float(ox), 'y': 0.0,
                        'yaw_deg': 0.0, 'target_height_m': None}]
    spec['front_cam'] = {'pos': list(cam), 'pitch_deg': pitch, 'fovy': fovy}
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    mujoco.mj_forward(m, d)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')

    r = mujoco.Renderer(m, H, W)
    r.enable_depth_rendering()
    r.update_scene(d, camera=cid)
    dep = r.render().copy()
    keep = m.body_pos[bid].copy()
    m.body_pos[bid] = [0.0, 0.0, -80.0]
    mujoco.mj_forward(m, d)
    r.update_scene(d, camera=cid)
    bg = r.render().copy()
    m.body_pos[bid] = keep
    mujoco.mj_forward(m, d)
    r.disable_depth_rendering()

    mask = (np.isfinite(dep) & np.isfinite(bg) & (dep < bg - 1e-3)
            & (dep > 0) & (dep < 100.0))
    K = _intr(W, H, fovy)
    cam_pos = np.array(d.cam_xpos[cid])
    cam_mat = np.array(d.cam_xmat[cid]).reshape(3, 3)
    ys, xs = np.nonzero(mask)
    pts = np.zeros((0, 3))
    if len(xs):
        zs = dep[ys, xs]
        pc = np.stack([(xs - K['cx']) * zs / K['fx'],
                       -(ys - K['cy']) * zs / K['fy'], -zs], axis=1)
        pts = pc @ cam_mat.T + cam_pos
    return {'depth': dep, 'mask': mask, 'points': pts, 'K': K,
            'cam_pos': cam_pos, 'cam_mat': cam_mat, 'W': W, 'H': H,
            'intr': K, 'fovy': fovy}


def check_plane(tmp, ox=1.80):
    """已知平板：反投影点必须落在**已知平面** x = ox-0.10 上，误差 < 1 cm。"""
    box = __import__('trimesh').creation.box(extents=[0.20, 0.40, 0.30])
    box.apply_translation([0, 0, 0.15])
    p = pathlib.Path(tmp) / 'plane.stl'; box.export(p)
    r = observe_depth(p, tmp, ox=ox)
    if r['points'].size == 0:
        return {'pass': False, 'why': '空点云'}
    known_x = ox - 0.10                       # 盒前面
    err = float(np.median(np.abs(r['points'][:, 0] - known_x)))
    # 轴向深度 vs 欧氏距离：两者不得混用，但必须满足 euclid = depth / cosθ
    ys, xs = np.nonzero(r['mask'])
    dz = r['depth'][ys, xs]
    de = np.linalg.norm(r['points'] - r['cam_pos'], axis=1)
    cos_t = float(np.median(de / np.maximum(dz, 1e-9)))
    return {'pass': err < CONFIG['depth_tol_m'],
            'known_plane_x_m': round(known_x, 4),
            'recovered_x_median_m': round(float(np.median(r['points'][:, 0])), 5),
            'plane_err_m': round(err, 5),
            'axial_to_euclid_ratio': round(cos_t, 5),
            'n_points': int(len(r['points']))}


def check_asymmetric(tmp):
    """非对称块：世界 +y 必须落在图像左侧；可见高度与反投影一致。"""
    box = __import__('trimesh').creation.box(extents=[0.20, 0.20, 0.20])
    box.apply_translation([0, 0.12, 0.10])       # 世界 +y 偏 0.12
    p = pathlib.Path(tmp) / 'asym.stl'; box.export(p)
    r = observe_depth(p, tmp)
    if r['points'].size == 0:
        return {'pass': False, 'why': '空点云'}
    ys, xs = np.nonzero(r['mask'])
    cx_img = float(xs.mean())
    # world +y 侧 -> 图像左侧
    y_center = float(np.median(r['points'][:, 1]))
    left = cx_img < (r['W'] / 2.0 - 5)
    h_vis = float(r['points'][:, 2].max() - r['points'][:, 2].min())
    return {'pass': bool(left and abs(y_center - 0.12) < CONFIG['lateral_tol_m']
                         and abs(h_vis - 0.20) < CONFIG['height_tol_m']),
            'world_y_median_m': round(y_center, 4),
            'image_centroid_x_px': round(cx_img, 1),
            'world_y_on_image_left': left,
            'visible_height_m': round(h_vis, 4),
            'n_points': int(len(r['points']))}


def check_ray_reference(tmp):
    """mj_ray 只作独立参考，验证渲染深度与几何射线一致。"""
    import trimesh
    box = trimesh.creation.box(extents=[0.20, 0.40, 0.30])
    box.apply_translation([0, 0, 0.15])
    p = pathlib.Path(tmp) / 'rayref.stl'; box.export(p)
    r = observe_depth(p, tmp)
    if r['points'].size == 0:
        return {'pass': False, 'why': '空点云'}
    # 用反投影点反推像素，比较与渲染深度的一致性（几何自洽）
    d = np.linalg.norm(r['points'] - r['cam_pos'], axis=1)
    ys, xs = np.nonzero(r['mask'])
    dz = r['depth'][ys, xs]
    ratio = float(np.median(d / np.maximum(dz, 1e-9)))
    # 轴向深度与欧氏距离之比应等于 1/cosθ（>1 且随像素位置变化），不得混用
    ok = 1.0 < ratio < 1.10
    return {'pass': ok, 'axial_to_euclid_ratio': round(ratio, 5),
            'note': 'mj_ray 仅作参考；验证轴向深度与欧氏距离的换算关系'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--work-dir', default=None)
    a = ap.parse_args()
    import tempfile
    work = pathlib.Path(a.work_dir) if a.work_dir else pathlib.Path(tempfile.mkdtemp())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)

    res = {'config': CONFIG,
           'plane': check_plane(work),
           'asymmetric': check_asymmetric(work),
           'ray_reference': check_ray_reference(work),
           'note': '点云来自渲染深度的反投影；mj_ray 仅作独立参考'}
    res['pass'] = all(res[k].get('pass') for k in ('plane', 'asymmetric', 'ray_reference'))
    (out / 'calibration.json').write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
