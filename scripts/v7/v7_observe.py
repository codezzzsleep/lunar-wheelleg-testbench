"""V7 观测：在仿真当前状态下拍一张机器人相机 RGB-D，写成 v3 格式的观测目录（局部坐标系）。

局部坐标系 = 机器人停车位姿（x0, y0, yaw0）为原点，与 v3 状态的约定一致，
这样后面的栅格、配准、准入、预演可以原样使用已验证的 v3/v5 模块。

产出目录：
  rgb.png  rgb_hi.png（2× 分辨率，仅用于 Lux3D 裁剪）  depth.npy  mask.png（目标岩石，实心）
  visible_points.npy  observation.json  camera_world.json  state.json  crops/{raw,white,masked}/rep{0,1}.png
"""
import hashlib
import json
import pathlib
import sys

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import camera_io  # noqa: E402
import v3_obs  # noqa: E402  Lux3D 输入变体沿用 v3 的 A/B/C 规则
import v7_shadow as SH  # noqa: E402  用深度区分石头与影子


def _sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def planar_pose(qpos):
    w, x, y, z = qpos[3:7]
    yaw = float(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
    return float(qpos[0]), float(qpos[1]), yaw


def world_to_local(x0, y0, yaw):
    c, s = np.cos(-yaw), np.sin(-yaw)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
    t = -R @ np.array([x0, y0, 0.0])
    return R, t


def crop_variants(img, mask, pad=1.15, size=512):
    """与 WP3 相同的裁剪规则（scripts/v4_wp3_tasks.py::crop），三种变体。"""
    ys, xs = np.where(mask > 0)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    side = int(max(y1 - y0, x1 - x0) * pad); half = side // 2
    a, b = max(0, cy - half), min(img.shape[0], cy + half)
    c, d = max(0, cx - half), min(img.shape[1], cx + half)
    sub, m = img[a:b, c:d], mask[a:b, c:d] > 0
    out = Image.new('RGB', (side, side), (255, 255, 255))
    mo = Image.new('L', (side, side), 0)
    ox, oy = (side - sub.shape[1]) // 2, (side - sub.shape[0]) // 2
    out.paste(Image.fromarray(sub), (ox, oy)); mo.paste(Image.fromarray(m.astype(np.uint8) * 255), (ox, oy))
    native = side
    crop = np.asarray(out.resize((size, size), Image.LANCZOS))
    mm = np.asarray(mo.resize((size, size), Image.NEAREST)) > 0
    return {'raw': crop,
            'white': np.where(mm[..., None], crop, np.uint8(255)),
            'masked': np.where(mm[..., None], crop, np.uint8(112))}, native


def capture(env, vm, rock_body, out_dir, cam='front_cam', label='look1'):
    """env: 仿真环境（当前状态即拍摄时刻）；vm: v7_visual.VisualModel；rock_body: 目标岩石 body 名。"""
    import mujoco
    out = pathlib.Path(out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    rgb, depth, seg = vm.render_camera(env.data, cam)
    target = set(vm.rock_geoms.get(rock_body, []))
    if not target:
        raise RuntimeError(f'no rock geoms for {rock_body}')
    truth_mask = np.isin(seg, list(target))           # 渲染器分割：只用于核对，不进入流程
    hi, depth_hi, seg_hi = vm.render_camera(env.data, cam, depth=True, seg=True, size=(4040, 3030))
    truth_hi = np.isin(seg_hi, list(target))
    cid = mujoco.mj_name2id(vm.m, mujoco.mjtObj.mjOBJ_CAMERA, cam)
    snap_w = camera_io.capture(vm.m, vm.d, cid, vm.W, vm.H)
    x0, y0, yaw0 = planar_pose(env.data.qpos)
    R, t = world_to_local(x0, y0, yaw0)
    snap_l = dict(snap_w)
    snap_l['world_pos'] = [float(v) for v in (R @ np.asarray(snap_w['world_pos']) + t)]
    snap_l['R_world_from_camera'] = (R @ np.asarray(snap_w['R_world_from_camera'])).tolist()
    snap_l['frame'] = 'local'
    snap_l['local_frame'] = {'x0': x0, 'y0': y0, 'yaw0': yaw0}

    # 石头掩码：用深度判定"高出地面"的像素（影子贴地，天然被排除），不看亮度、不用渲染器分割
    lf = snap_l['local_frame']
    mask, hmap, ginfo = SH.rock_mask_depth(depth, snap_l)
    if mask.sum() < 2000:
        raise RuntimeError(f'target rock too small in view: {int(mask.sum())} px')
    K_hi = SH.hi_intrinsics(snap_l, 4040, 3030)
    mask_hi, _, _ = SH.rock_mask_depth(depth_hi, snap_l, K=K_hi, plane=ginfo['plane'])   # 复用低分辨率拟合的地面
    shadow, ground_med = SH.shadow_mask(rgb, hmap)
    check = {'iou_depth_mask_vs_render_seg': round(SH.mask_iou(mask, truth_mask), 4),
             'iou_depth_mask_vs_render_seg_hi': round(SH.mask_iou(mask_hi, truth_hi), 4),
             'shadow_px': int(shadow.sum()), 'ground_fit': ginfo}
    if check['iou_depth_mask_vs_render_seg'] < 0.9:
        raise RuntimeError(f'depth rock mask disagrees with the rendered rock: IoU {check["iou_depth_mask_vs_render_seg"]}')
    Image.fromarray(rgb).save(out / 'rgb.png')
    Image.fromarray(mask.astype(np.uint8) * 255).save(out / 'mask.png')
    Image.fromarray(shadow.astype(np.uint8) * 255).save(out / 'shadow_mask.png')
    np.save(out / 'depth.npy', depth.astype(np.float32))
    dm = np.where(mask, depth, np.nan).astype(np.float64)
    pts, _, _ = camera_io.unproject_depth(dm, snap_l)
    np.save(out / 'visible_points.npy', pts)
    vis = {'x_front': float(pts[:, 0].min()), 'y_center': float((pts[:, 1].min() + pts[:, 1].max()) / 2),
           'W_vis': float(pts[:, 1].max() - pts[:, 1].min()), 'H_vis': float(pts[:, 2].max() - pts[:, 2].min()),
           'source': 'visible_points (local frame, target-rock mask)'}
    (out / 'observation.json').write_text(json.dumps({'schema': 'observation/v7', 'label': label, 'camera': snap_l,
                                                     'intrinsics': snap_l['intrinsics'], 'image': 'rgb.png',
                                                     'rock_body': rock_body, 'mask_px': int(mask.sum()),
                                                     'mask_source': 'depth: height above RANSAC ground plane > 1.5 cm', 'mask_check': check}, indent=2))
    (out / 'camera_world.json').write_text(json.dumps(snap_w, indent=2))
    proto = json.loads((HERE.parents[1] / 'plans/v3_protocol.json').read_text())
    box = v3_obs._pixel_box(mask_hi)
    native = box[3] - box[1] + 1
    Image.fromarray(hi).save(out / 'rgb_gen.png')
    rec = v3_obs._variants(hi, mask_hi, box, out / 'gen', native, proto)
    crops = rec['variants']
    st = {'schema': 'v7-encounter-state/v1', 'visible': vis, 'local_frame': {'x0': x0, 'y0': y0, 'yaw0': yaw0},
          'robot_qpos_world': [float(v) for v in env.data.qpos], 'robot_qvel_world': [float(v) for v in env.data.qvel],
          't_sim': float(env.t), 'crop_native_px': int(native), 'native_ok': bool(rec.get('native_ok')), 'crops': crops,
          'mask_check': check,
          'observation_sha256': {k: _sha(out / k) for k in ('rgb.png', 'depth.npy', 'mask.png')}}
    (out / 'state.json').write_text(json.dumps(st, indent=2))
    return st
