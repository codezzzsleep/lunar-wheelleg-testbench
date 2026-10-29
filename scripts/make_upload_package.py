"""
实际上传包：高分辨率渲染 -> 按可见掩码裁剪 -> 目标占画面 70–85% -> 哈希与参数。

  MUJOCO_GL=osmesa .venv/bin/python scripts/make_upload_package.py \
      --case cases/unseen_v1/planA.json --out runs/unseen/recovery_r3/upload_pkg/P1 \
      --cam-height 0.32 --texture assets/textures/rock_v1.png

与旧 preview 的区别（E4 任务 E）：
  · 先渲真正的 raw 场景图（2560×1920），再从 mask 定裁剪框；
  · 只做裁剪 + 等比缩放 + 补边，不横纵分别拉伸；
  · 记录裁剪坐标、缩放、原图与最终字节 SHA、相机外参/内参/qpos；
  · 目标最长边占裁剪后画面 70–85%，轮廓完整，底部留余量。
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import terrain
import wheelleg_env
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
W, H = 2560, 1920
TARGET_FRAC = (0.70, 0.85)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def render(case, cam_h, tex_path, out_dir, azimuth_deg=0.0):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[],
                             goal_x=float(case.get('goal_x', 2.8)), name='up')
    spec['channel'] = {'center_y': 0.0, 'half_width': float(case.get('channel_half', 1.2))}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    if tex_path:
        spec['object_material'] = {'name': 'rock', 'texture': str(tex_path)}
        spec['visual'] = {'light': {'pos': [-1.2, -0.7, 1.5], 'dir': [0.6, 0.35, -0.72]},
                          'headlight': {'ambient': '0.40 0.40 0.40',
                                        'diffuse': '0.55 0.55 0.55'}}
    # 有纹理时必须用带 UV 的 OBJ，否则 2D 贴图会退化成条带（已用球/立方体验证）
    mesh_for_render = ROOT / case['mesh']
    if tex_path:
        import subprocess
        uv_dir = out_dir / 'uv'
        uv_dir.mkdir(parents=True, exist_ok=True)
        uv_obj = uv_dir / 'body_uv.obj'
        subprocess.run([sys.executable, str(ROOT / 'scripts/make_uv_mesh.py'),
                        '--mesh', str((ROOT / case['mesh']).resolve()),
                        '--out', str(uv_obj), '--scale', '6'],
                       capture_output=True, text=True, cwd=str(ROOT))
        if uv_obj.exists():
            mesh_for_render = uv_obj
    spec['objects'] = [{'mesh_file': str(mesh_for_render),
                        'x': case['obstacle_x'], 'y': 0.0, 'yaw_deg': float(azimuth_deg),
                        'target_height_m': case['H']}]
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    bid = m.cam_bodyid[cid]
    B = np.asarray(d.xmat[bid]).reshape(3, 3)
    b = np.asarray(d.xpos[bid])
    m.cam_pos[cid][2] = (cam_h - b[2] - B[2, 0] * 0.42) / B[2, 2]
    mujoco.mj_forward(m, d)

    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    r = mujoco.Renderer(m, H, W)
    r.update_scene(d, camera=cid)
    rgb = r.render()
    r.enable_depth_rendering(); r.update_scene(d, camera=cid)
    dep = r.render().copy()
    obid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    keep = m.body_pos[obid].copy()
    m.body_pos[obid] = [0, 0, -80]; mujoco.mj_forward(m, d)
    r.update_scene(d, camera=cid); bg = r.render().copy()
    m.body_pos[obid] = keep; mujoco.mj_forward(m, d)
    r.disable_depth_rendering()
    mask = np.isfinite(dep) & np.isfinite(bg) & (dep < bg - 1e-3) & (dep > 0) & (dep < 100)

    out_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(out_dir / 'raw_scene.png')
    Image.fromarray((mask * 255).astype(np.uint8)).save(out_dir / 'mask.png')
    cam = {'world_pos': [float(x) for x in d.cam_xpos[cid]],
           'R_world_from_camera': [[float(v) for v in row]
                                   for row in np.asarray(d.cam_xmat[cid]).reshape(3, 3)],
           'fovy_deg': float(m.cam_fovy[cid]),
           'local_pos': [float(x) for x in m.cam_pos[cid]],
           'cam_body': mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, int(bid)),
           'robot_qpos': [float(x) for x in d.qpos],
           'robot_qvel': [float(x) for x in d.qvel],
           'cam_world_height_m': round(float(d.cam_xpos[cid][2]), 5)}
    return rgb, mask, cam


def isolate_white(rgb, mask, feather=0.0):
    """按 mask 合成白底隔离版本：背景纯白，主体保留纹理与明暗。"""
    m = mask.astype(np.float32)
    if feather > 0:
        from scipy import ndimage  # 不可用时退回硬边
    out = rgb.astype(np.float32).copy()
    out[~mask] = 255.0
    return out.astype(np.uint8)


def crop_to_fraction(rgb, mask, out_png, target=(0.70, 0.85)):
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        raise SystemExit('目标像素过少，无法裁剪')
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    obj_w, obj_h = x1 - x0, y1 - y0
    long_side = max(obj_w, obj_h)
    want = 0.78                      # 目标最长边占比（区间中点）
    side = int(round(long_side / want))
    # 以目标质心为中心，保持正方形；不足处补边
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    half = side // 2
    left, top = cx - half, cy - half
    canvas = np.full((side, side, 3), 255, dtype=np.uint8)
    sx0, sy0 = max(0, left), max(0, top)
    sx1, sy1 = min(rgb.shape[1], left + side), min(rgb.shape[0], top + side)
    dx0, dy0 = sx0 - left, sy0 - top
    canvas[dy0:dy0 + (sy1 - sy0), dx0:dx0 + (sx1 - sx0)] = rgb[sy0:sy1, sx0:sx1]
    img = Image.fromarray(canvas)
    if side < 1024:                  # 只等比放大，不拉伸
        img = img.resize((1024, 1024), Image.LANCZOS)
    img.save(out_png)
    frac = long_side / side
    return {'crop_box_px': [int(left), int(top), int(side), int(side)],
            'object_bbox_px': [int(x0), int(y0), int(obj_w), int(obj_h)],
            'longest_side_fraction': round(float(frac), 4),
            'resized_to': list(img.size),
            'pad_px': int((side - (sx1 - sx0)) * side / max(side, 1)) if side else 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cam-height', type=float, default=0.32)
    ap.add_argument('--texture', default='assets/textures/rock_v1.png')
    ap.add_argument('--azimuth', type=float, default=0.0,
                    help='石头相对相机的偏航（度）。只改可见面，机位与取景不变；'
                         '用于"一次只改一个因素"的对照输入')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    case = json.loads(pathlib.Path(a.case).read_text())
    tex = (ROOT / a.texture) if a.texture else None

    rgb, mask, cam = render(case, a.cam_height, tex, out, a.azimuth)
    # 白底隔离版本：避免高度场渲染噪点进入上传图
    iso = isolate_white(rgb, mask)
    Image.fromarray(iso).save(out / 'isolated_white.png')
    crop_meta = crop_to_fraction(iso, mask, out / 'upload_1024.png')
    # 另存含接地信息的整场景裁剪版，仅供对照，不作为上传字节
    crop_to_fraction(rgb, mask, out / 'upload_with_ground_1024.png')

    # 目标亮度（mask 内）
    luma = np.array(Image.open(out / 'upload_1024.png').convert('L'), dtype=float)
    nonwhite = luma < 250
    bright = float(luma[nonwhite].mean()) if nonwhite.any() else 0.0
    frac = crop_meta['longest_side_fraction']

    rec = {
        'package_version': 'upload-pkg/v1',
        'case': case['case_id'],
        'source_mesh': case['mesh'],
        'texture': {'path': a.texture, 'sha256': sha(tex) if tex and tex.exists() else None,
                    'seed': 7, 'note': '只改视觉不改碰撞'},
        'camera': cam,
        'camera_requested_height_m': a.cam_height,
        'camera_feasible_note': ('相机挂在 base_link 上，local x=0.42；'
                                 '0.32 m 低于 base_link 中心 0.384 m，属低置前置安装，'
                                 '不是人体动作，也不是瞬移相机'),
        **crop_meta,
        'target_fraction_window': list(TARGET_FRAC),
        'target_mean_luma': round(bright, 2),
        'files': {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size}
                  for p in (out / 'raw_scene.png', out / 'mask.png',
                            out / 'isolated_white.png', out / 'upload_1024.png',
                            out / 'upload_with_ground_1024.png')},
        'upload_file': str(out / 'upload_1024.png'),
    }
    ok = TARGET_FRAC[0] <= frac <= TARGET_FRAC[1] and bright > 60
    rec['checks'] = {'longest_side_in_window': TARGET_FRAC[0] <= frac <= TARGET_FRAC[1],
                     'brightness_gt_60': bright > 60,
                     'all_pass': bool(ok)}
    (out / 'upload_manifest.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps({'case': case['case_id'], 'fraction': frac,
                      'luma': round(bright, 1), 'checks': rec['checks'],
                      'sha': rec['files']['upload_1024.png']['sha256'][:16]},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
