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
import hashlib
import json
import pathlib
import sys

import numpy as np
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import camera_io
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
    ap.add_argument('--crop-pad', type=float, default=0.35)
    ap.add_argument('--mask-step', type=int, default=2, help='掩码射线采样步长')
    ap.add_argument('--cam-height', type=float, default=None,
                    help='相机离地高度（米）。低于障碍顶部时背面不可见，P3 才可能成立')
    ap.add_argument('--pitch', type=float, default=None, help='俯角（负=向下）')
    ap.add_argument('--cam-lateral', type=float, default=0.0,
                    help='相机横向偏移（米，机体坐标系 y）。等价于机器人站到侧面再看一次，'
                         '不是把物体旋转——用于真实第二观察')
    ap.add_argument('--azimuth', type=float, default=None,
                    help='石头相对相机的偏航（度）；缺省读 case.yaw_deg，再缺省 0')
    ap.add_argument('--state-json', default=None,
                    help='从 drive_observe.json 恢复行驶后的真实状态（qpos/qvel）再取景；'
                         '这是"机器人实际移动后停稳"的第二观察，不是相机平移')
    ap.add_argument('--state-seed', type=int, default=0, help='--state-json 里取哪一条 seed 的状态')
    ap.add_argument('--observation-id', default=None,
                    help='独立 observation_id；缺省 case_id 或 case_id_azNN')
    a = ap.parse_args()

    case = json.loads(pathlib.Path(a.case).read_text())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    yaw_deg = (float(a.azimuth) if a.azimuth is not None
               else float(case.get('yaw_deg', 0.0)))
    obs_id = a.observation_id or (case['case_id'] +
                                  ('' if abs(yaw_deg) < 1e-9 else f'_az{int(round(yaw_deg))}'))

    spec = terrain.make_spec(kind='flat', seed=case.get('seed', 0), objects=[],
                             goal_x=case.get('goal_x', 3.0), name=case['case_id'])
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['objects'] = [{'mesh_file': case['mesh'], 'x': case['obstacle_x'],
                        'y': 0.0, 'yaw_deg': yaw_deg, 'target_height_m': case['H']}]
    # 相机必须装在机体轮廓之外，否则每根射线先生命中机器人自身几何（实测 2 cm 处）
    # 相机挂在 base_link 上，local z 由"目标离地高度 - 实际 base_link 离地高度"算出，
    # 后者在 reset 之后从 MuJoCo 实测，不写死。
    spec['front_cam'] = {'pos': [0.42, float(a.cam_lateral), 0.0],
                         'pitch_deg': a.pitch if a.pitch is not None else 0.0,
                         'fovy': a.fovy}

    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    if a.state_json:
        _dj = json.loads(pathlib.Path(a.state_json).read_text())
        _runs = _dj.get('runs') or []
        _rec = next((r for r in _runs if int(r.get('seed', -1)) == int(a.state_seed)), None)
        if _rec is None:
            raise SystemExit(f'--state-json 里没有 seed {a.state_seed} 的记录')
        _snap = _rec['state_snapshot']
        env.data.qpos[:] = np.asarray(_snap['qpos'], dtype=float)
        env.data.qvel[:] = np.asarray(_snap['qvel'], dtype=float)
        env.model.opt.timestep = env.model.opt.timestep
        mujoco.mj_forward(env.model, env.data)
        print(json.dumps({'restored_state_seed': a.state_seed,
                          'qpos_n': len(_snap['qpos'])}, ensure_ascii=False))
    capture_observation(env, out, width=a.width, height=a.height,
                        fovy=a.fovy, cam_height=a.cam_height,
                        cam_lateral=a.cam_lateral, obs_id=obs_id)


def capture_observation(env, out, *, width=1280, height=960, fovy=70.0,
                       cam_height=None, cam_lateral=0.0, obs_id=None,
                       case_id=None, extra=None):
    """从**已有环境**采集一份观测：不 reset、不推进物理、不重建障碍。

    这是任务书 §四.1 要求的分离：驾驶/停稳与采集共用同一个真值环境实例，
    采集后再从这个实例继续执行，就不存在"重建场景导致签名不符"。
    """
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    a = type("A", (), {})()
    a.width = width; a.height = height; a.fovy = fovy
    a.cam_height = cam_height; a.cam_lateral = cam_lateral
    a.observation_id = obs_id
    a.crop_pad = 0.35          # 与 observe 命令行默认值一致
    a.mask_step = 2
    a.azimuth = None

    cam_id = cam_id_of(env)
    m0, d0 = env.model, env.data
    mujoco.mj_forward(m0, d0)
    base_bid = mujoco.mj_name2id(m0, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    base_link_z = float(d0.xpos[base_bid][2])
    if a.cam_height is not None:
        # 按**世界离地高度**反解 local z（含机身俯仰投影），不是硬编码
        camera_io.install_local_z_for_world_height(
            m0, d0, cam_id, a.cam_height, local_x=0.42, local_y=float(a.cam_lateral))
    snap = camera_io.capture(m0, d0, cam_id, a.width, a.height)
    m, d = env.model, env.data
    m.vis.global_.offwidth = a.width
    m.vis.global_.offheight = a.height
    mujoco.mj_forward(m, d)

    r = mujoco.Renderer(m, a.height, a.width)
    r.update_scene(d, camera=cam_id)
    # 关闭阴影：低角度方向光在 heightfield 上会产生锯齿状阴影瑕疵
    r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0
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
    # 掩码与深度全部来自**渲染**：把障碍移走再渲一次，两次深度不同的像素就是障碍。
    # 射线采样在轮廓边缘有约 ±10 mm 的偏差（网格对齐），改用渲染深度后与 align 同一口径。
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    keep = m.body_pos[bid].copy()
    m.body_pos[bid] = [0.0, 0.0, -80.0]
    mujoco.mj_forward(m, d)
    r.enable_depth_rendering()
    r.update_scene(d, camera=cam_id)
    depth_bg = r.render().copy()
    r.disable_depth_rendering()
    m.body_pos[bid] = keep
    mujoco.mj_forward(m, d)

    mask = depth < depth_bg - 1e-3
    seg = np.zeros((a.height, a.width, 2), dtype=np.int32)
    seg[mask, 0] = 1

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
    # 台账像素之外一律涂白：掩码膨胀 2px 再羽化 2px，避免边界出现灰边
    m_ = mask.copy()
    for _ in range(2):
        m_ = (m_ | np.roll(m_, 1, 0) | np.roll(m_, -1, 0)
              | np.roll(m_, 1, 1) | np.roll(m_, -1, 1))
    alpha = m_.astype(np.float32)
    for _ in range(2):                       # 简单盒式羽化
        alpha = (alpha + np.roll(alpha, 1, 0) + np.roll(alpha, -1, 0)
                 + np.roll(alpha, 1, 1) + np.roll(alpha, -1, 1)) / 5.0
    a3 = alpha[:, :, None]
    obj_only = (rgb.astype(np.float32) * a3 + 255.0 * (1 - a3)).astype(np.uint8)
    Image.fromarray(obj_only).save(out / 'masked_only.png')

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
        canvas.paste(Image.fromarray(obj_only[py0:py1, px0:px1]), (px0 - sx0, py0 - sy0))
    crop1024 = canvas.resize((1024, 1024), Image.LANCZOS)
    crop1024.save(out / 'crop_white.png')
    canvas.save(out / 'crop_white_src.png')

    info = {
        'case_id': (case_id or obs_id),
        'observation_id': obs_id,
        'observation_protocol': 'observation-v5/direction',
        'object_pose': {'yaw_deg': float(extra.get('yaw_deg', 0.0)) if extra else 0.0,
                        'mesh': (extra or {}).get('mesh'),
                        'obstacle_x': float((extra or {}).get('obstacle_x', 0.0)),
                        'H': float((extra or {}).get('H', 0.0)),
                        'W': float((extra or {}).get('W', 0.0)),
                        'D': float((extra or {}).get('D', 0.0))},
        'camera_schema': camera_io.SCHEMA,
        'camera': {**snap,
                   'id': int(cam_id),
                   'base_link_z_m': round(base_link_z, 5),
                   'cam_height_m': round(float(snap['world_pos'][2]), 5),
                   # 兼容旧字段：必须来自 model.cam_pos，不再来自未同步的 spec
                   'pos_body': [float(x) for x in snap['local_pos']],
                   'pitch_deg': float((extra or {}).get('pitch_deg', 0.0))},
        'image': {'W': a.width, 'H': a.height},
        'intrinsics': snap['intrinsics'],
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

    # ---- 独立 observation_id / observation_sha 与出生状态（V5 P0.2）----
    birth = {'schema': 'birth-state/v1', 'observation_id': obs_id,
             'case_id': (case_id or obs_id), 'object_pose': info['object_pose'],
             'qpos': [float(x) for x in d.qpos],
             'qvel': [float(x) for x in d.qvel],
             'data_time': float(d.time), 'env_t': float(env.t),
             'camera': snap}
    (out / 'birth_state.json').write_text(json.dumps(birth, indent=2, ensure_ascii=False))
    file_names = ['rgb.png', 'depth.npy', 'mask.png', 'visible_points.npy',
                  'crop_white.png', 'crop_raw.png', 'masked_only.png',
                  'observation.json', 'birth_state.json']
    file_sha = {n: hashlib.sha256((out / n).read_bytes()).hexdigest()
                for n in file_names if (out / n).exists()}
    canonical = {'observation_id': obs_id, 'case_id': (case_id or obs_id),
                 'camera': info['camera'], 'intrinsics': info['intrinsics'],
                 'visible': info['visible'], 'object_pose': info['object_pose'],
                 'files': file_sha}
    obs_sha = hashlib.sha256(json.dumps(canonical, sort_keys=True,
                                       ensure_ascii=False).encode()).hexdigest()
    (out / 'observation_manifest.json').write_text(json.dumps({
        'schema': 'observation-manifest/v1', 'observation_id': obs_id,
        'observation_sha': obs_sha, 'files': file_sha,
        'canonical': canonical}, indent=2, ensure_ascii=False))
    print(json.dumps({'case': (case_id or obs_id), 'observation_id': obs_id,
                      'observation_sha': obs_sha[:16], 'mask_px': int(mask.sum()),
                      'x_front': round(x_front, 4) if x_front else None,
                      'W_vis': round(W_vis, 4) if W_vis else None,
                      'H_vis': round(H_vis, 4) if H_vis else None}, ensure_ascii=False))
    print('->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
