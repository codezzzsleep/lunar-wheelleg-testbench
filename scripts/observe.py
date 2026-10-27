"""
S0 观测包：机器人正面视角的 RGB / 深度 / 掩码 / 可见点云。

  MUJOCO_GL=osmesa .venv/bin/python scripts/observe.py \
      --case cases/unseen_v1/<case>.json --out runs/unseen/obs/<run_id>

关键点（任务书 4.4）：
  · 用真实 MuJoCo 相机渲染，深度是**相机坐标下的真实深度**，不是真值网格投影；
  · 可见点云只来自该视角真正可见的障碍像素（用分割掩码筛），
    不能拿完整真值网格的"正面点"顶替；
  · 相机内参由 fovy 与分辨率算出，投影/反投影用它；裁剪另存变换，不混用内参；
  · 明确记录 MuJoCo 相机轴约定：相机朝向 -z，图像 x 向右、y 向下。
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def cam_id_of(env):
    cid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    if cid < 0:
        raise SystemExit('模型里没有 front_cam：请在 spec 里设置 front_cam')
    return cid


def _unused_add_camera(env, fovy=70.0, pos=(0.30, 0.0, 0.06), pitch_deg=-12.0):
    """
    往模型里加一个机头前上方的相机。
    MuJoCo 相机默认朝自身 -z 看，因此"向下俯 12°"= 绕 y 轴转 +12°（俯角）。
    这里通过修改 model.cam_pos/cam_quat 实现，不改 XML。
    """
    m = env.model
    m.ncam = 1 if m.ncam == 0 else m.ncam
    cam_id = 0
    # 相机挂在 base_link 的坐标系下；用 body 局部位置
    base = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    if base >= 0:
        m.cam_bodyid[cam_id] = base
    m.cam_pos[cam_id] = np.array(pos, dtype=np.float64)
    ang = np.deg2rad(-pitch_deg)
    q = np.array([np.cos(ang / 2), 0.0, np.sin(ang / 2), 0.0])   # 绕 y 轴
    m.cam_quat[cam_id] = q
    m.cam_fovy[cam_id] = fovy
    m.cam_mode[cam_id] = mujoco.mjtCamLight.mjCAMLIGHT_FIXED
    return cam_id


def intrinsics(W, H, fovy):
    fy = (H / 2.0) / np.tan(np.deg2rad(fovy) / 2.0)
    fx = fy
    return {'fx': float(fx), 'fy': float(fy), 'cx': (W - 1) / 2.0, 'cy': (H - 1) / 2.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--height', type=int, default=960)
    ap.add_argument('--fovy', type=float, default=70.0)
    ap.add_argument('--crop-pad', type=float, default=0.15)
    a = ap.parse_args()

    case = json.loads(pathlib.Path(a.case).read_text())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)

    spec = terrain.make_spec(kind='flat', seed=case.get('seed', 0), objects=[],
                             goal_x=case.get('goal_x', 3.0), name=case['case_id'])
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['objects'] = [{'mesh_file': case['mesh'], 'x': case['obstacle_x'],
                        'y': 0.0, 'yaw_deg': 0.0, 'target_height_m': case['H']}]
    # 相机必须装在机体轮廓之外，否则每根射线先生命中机器人自身几何（实测 2 cm 处）
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.20], 'pitch_deg': -12.0, 'fovy': a.fovy}

    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    cam_id = cam_id_of(env)
    m, d = env.model, env.data
    m.vis.global_.offwidth = a.width
    m.vis.global_.offheight = a.height
    mujoco.mj_forward(m, d)

    r = mujoco.Renderer(m, a.height, a.width)
    r.update_scene(d, camera=cam_id)
    rgb = r.render()
    r.enable_depth_rendering()
    r.update_scene(d, camera=cam_id)
    depth = r.render()
    r.disable_depth_rendering()

    K = intrinsics(a.width, a.height, a.fovy)
    # 掩码用**逐像素射线**判定：比依赖渲染后端的 segmentation 编码可靠，
    # 且严格等价于"这个像素真的先打到障碍物"。
    obs_bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    obs_geoms = {g for g in range(m.ngeom) if m.geom_bodyid[g] == obs_bid}
    cam_pos = np.array(d.cam_xpos[cam_id], dtype=np.float64)
    cam_mat = np.array(d.cam_xmat[cam_id], dtype=np.float64).reshape(3, 3)
    step = 2                                   # 1/2 分辨率射线，再上采样
    hs = np.arange(0, a.height, step)
    ws = np.arange(0, a.width, step)
    mask_small = np.zeros((len(hs), len(ws)), dtype=bool)
    hit_id = np.full((len(hs), len(ws)), -1, dtype=np.int32)
    for iy, yy in enumerate(hs):
        for ix, xx in enumerate(ws):
            # 图像 y 向下增大，而 MuJoCo 相机 +Y 向上 -> y 分量取负。
            # 这一点用非对称标定物验证（见 scripts/calibrate_observe.py）。
            pc = np.array([(xx - K['cx']) / K['fx'],
                           -(yy - K['cy']) / K['fy'], -1.0])
            vd = cam_mat @ pc
            gid = np.array([-1], dtype=np.int32)
            dist = mujoco.mj_ray(m, d, cam_pos, vd, None, 1, -1, gid)
            if dist > 0 and int(gid[0]) in obs_geoms:
                mask_small[iy, ix] = True
                hit_id[iy, ix] = int(gid[0])
    mask = np.repeat(np.repeat(mask_small, step, axis=0), step, axis=1)[:a.height, :a.width]
    seg = np.zeros((a.height, a.width, 2), dtype=np.int32)
    seg[:mask.shape[0], :mask.shape[1], 0] = np.repeat(
        np.repeat(hit_id, step, 0), step, 1)[:a.height, :a.width] + 1

    K = intrinsics(a.width, a.height, a.fovy)
    # 反投影：相机坐标系 -> 世界
    cam_pos = np.array(d.cam_xpos[cam_id])
    cam_mat = np.array(d.cam_xmat[cam_id]).reshape(3, 3)
    ys, xs = np.nonzero(mask)
    zs = depth[ys, xs]
    if len(xs):
        pc = np.stack([(xs - K['cx']) * zs / K['fx'],
                       -(ys - K['cy']) * zs / K['fy'],   # 相机 +Y 向上
                       -zs], axis=1)            # MuJoCo 相机朝 -z
        pw = pc @ cam_mat.T + cam_pos
    else:
        pw = np.zeros((0, 3))

    # 可见特征：只从观测算
    x_front = float(pw[:, 0].min()) if len(pw) else None
    y_center = float((pw[:, 1].min() + pw[:, 1].max()) / 2) if len(pw) else None
    W_vis = float(pw[:, 1].max() - pw[:, 1].min()) if len(pw) else None
    H_vis = float(pw[:, 2].max() - pw[:, 2].min()) if len(pw) else None

    # 裁剪：围绕掩码外扩 15%，补成正方形 -> 1024²
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    pad_x = int((x1 - x0) * a.crop_pad) + 1
    pad_y = int((y1 - y0) * a.crop_pad) + 1
    cx0, cx1 = max(0, x0 - pad_x), min(a.width - 1, x1 + pad_x)
    cy0, cy1 = max(0, y0 - pad_y), min(a.height - 1, y1 + pad_y)
    side = max(cx1 - cx0, cy1 - cy0)
    ccx, ccy = (cx0 + cx1) // 2, (cy0 + cy1) // 2
    sq = [ccx - side // 2, ccy - side // 2, ccx + side // 2, ccy + side // 2]

    from PIL import Image
    Image.fromarray(rgb).save(out / 'rgb.png')
    Image.fromarray((mask * 255).astype(np.uint8)).save(out / 'mask.png')
    np.save(out / 'depth.npy', depth)
    np.save(out / 'visible_points.npy', pw)
    Image.fromarray(rgb[cy0:cy1, cx0:cx1]).save(out / 'crop_raw.png')

    # 真实补成正方形并输出 1024²：以掩码中心为心，边长 = max(宽,高)*(1+2*pad)
    side_src = int(max(x1 - x0, y1 - y0) * (1 + 2 * a.crop_pad))
    ccx = (x0 + x1) // 2
    ccy = (y0 + y1) // 2
    half = side_src // 2
    sx0, sy0 = ccx - half, ccy - half
    sx1, sy1 = sx0 + side_src, sy0 + side_src
    # 越界部分用白色填充（背景色，避免把场景外内容当成物体）
    canvas = Image.new('RGB', (side_src, side_src), (255, 255, 255))
    px0, py0 = max(0, sx0), max(0, sy0)
    px1, py1 = min(a.width, sx1), min(a.height, sy1)
    if px1 > px0 and py1 > py0:
        canvas.paste(Image.fromarray(rgb[py0:py1, px0:px1]), (px0 - sx0, py0 - sy0))
    crop1024 = canvas.resize((1024, 1024), Image.LANCZOS)
    crop1024.save(out / 'crop_white.png')
    canvas.save(out / 'crop_white_src.png')

    info = {
        'case_id': case['case_id'],
        'camera': {'id': cam_id, 'fovy': a.fovy, 'pos_body': [0.42, 0.0, 0.20],
                   'pitch_deg': -12.0,
                   'convention': 'MuJoCo 相机朝 -z；图像 x 向右、y 向下；深度为正距离'},
        'image': {'W': a.width, 'H': a.height},
        'intrinsics': K,
        'crop': {'box': [cx0, cy0, cx1, cy1],
                 'square_box': [sx0, sy0, sx1, sy1], 'square_side_px': side_src,
                 'out_size': [1024, 1024], 'pad_frac': a.crop_pad,
                 'note': '真正补成正方形并缩放到 1024²；该变换单独保存，前向投影仍用原内参'},
        'visible': {'n_pixels': int(mask.sum()),
                    'x_front': x_front, 'y_center': y_center,
                    'W_vis': W_vis, 'H_vis': H_vis},
        'obstacle_truth_hidden': True,
        'note': '只保存观测；真值背面不写入本文件',
    }
    (out / 'observation.json').write_text(json.dumps(info, indent=2, ensure_ascii=False))
    print(json.dumps({'case': case['case_id'], 'mask_px': int(mask.sum()),
                      'x_front': round(x_front, 4) if x_front else None,
                      'W_vis': round(W_vis, 4) if W_vis else None,
                      'H_vis': round(H_vis, 4) if H_vis else None}, ensure_ascii=False))
    print('->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
