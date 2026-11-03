"""v3 观测阶段：冻结首视角，采集公共观测与高分辨率生成输入。

每个状态（岩石 × 尺度档 × 首视角）产出：

  <state>/scene_spec.json        场景 spec（不含任何隐藏真值字段）
  <state>/state_snapshot.json    env-state/v1 完整快照（S0）
  <state>/observation/           规划相机观测（公共观测 O 的唯一来源）
      rgb_plan.png  depth_plan.npy  mask_plan.png  visible_points.npy  observation.json
  <state>/observation/gen/       生成相机（同一光心/朝向，只改视场与分辨率）
      rgb_gen.png  mask_gen.png  gen_camera.json  variants/{A1,A2,B1,B2,C1,C2}.png
  <state>/truth/                 真值世界网格（只给筛选/评估/揭晓用）
      body_world.stl  manifest.json

  /opt/lunar/bin/python scripts/v3_obs.py --protocol plans/v3_protocol.json \
      --states moon_rock_02:L1:V0 --out runs/v3

关键口径（写进协议，改动即新版本）：
  · 机器人停在固定观察位后**不再移动**，S0 就是观测时刻的状态；观测不推进物理时钟；
  · 规划相机 fovy=70°，生成相机保持同一 world_pos/R，只收窄 fovy 并提高分辨率；
  · 深度按测量噪声 σ=2 mm 注入一次并固化为 depth.npy，后续 V/配准都用同一份；
  · 生成相机视场按可见包围盒自适应，保证原生目标高度 ≥512 px（目标 640 px）。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mujoco
import camera_io
import observe
import terrain
import v7_soil
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 'v3-observation/v1'


def sha256_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def sha256_json(obj):
    import hashlib
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False)
                          .encode()).hexdigest()[:32]


def load_rock_level(proto, rock_id, level_idx):
    meta_p = ROOT / proto['assets']['rock_root'] / rock_id / f'h{level_idx}' / 'meta.json'
    meta = json.loads(meta_p.read_text())
    return meta, meta_p


def build_scene_spec(proto, rock_id, level_idx, view_idx):
    """纯公开信息 + 资产元数据；不读任何隐藏真值。"""
    meta, meta_p = load_rock_level(proto, rock_id, level_idx)
    view = proto['views'][view_idx]
    sc = proto['scene']
    spec = terrain.make_spec(kind='flat', seed=int(sc['terrain_seed']), objects=[],
                             goal_x=float(sc['goal_x']),
                             name=f'v3_{rock_id}_h{level_idx}_v{view_idx}')
    spec['channel'] = {'center_y': 0.0, 'half_width': float(sc['channel_half_m'])}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False,
                         'settle_seconds': float(sc['settle_seconds'])}
    cam = proto['cameras']['planning']
    spec['front_cam'] = {'pos': [float(x) for x in cam['local_pos']],
                         'pitch_deg': float(cam['pitch_deg']),
                         'fovy': float(cam['fovy_deg'])}
    spec['start'] = [float(sc['robot_start_x']), float(view['robot_lateral_m'])]
    spec['obstacle_y'] = float(view.get('obstacle_y_m', 0.0))
    lvl_dir = ROOT / proto['assets']['rock_root'] / rock_id / f'h{level_idx}'
    vis_obj = lvl_dir / 'body_vis.obj'
    use_obj = vis_obj.is_file() and meta.get('obj_has_uv', False)
    if use_obj and meta.get('texture'):
        spec['object_material'] = {'name': f'rock_{rock_id}_{level_idx}',
                                   'texture': str((ROOT / meta['texture']).resolve())}
    spec['objects'] = [{
        'mesh_file': str(vis_obj.resolve() if use_obj else (lvl_dir / 'body.stl').resolve()),
        'x': float(sc['obstacle_x']), 'y': float(view.get('obstacle_y_m', 0.0)),
        'yaw_deg': float(view['rock_yaw_deg']),
        'target_height_m': float(meta['height_m']),   # 资产已按目标高度导出，这里只是记录
    }]
    soil = v7_soil.resolve(sc['soil'])
    spec['soil'] = {'mode': soil['mode'], 'label': soil['label'], 'params': soil['params']}
    spec['v3'] = {'rock_id': rock_id, 'level': level_idx, 'view': view_idx,
                  'asset_meta': str(meta_p.relative_to(ROOT)),
                  'asset_meta_sha256': sha256_file(meta_p),
                  'height_m': meta['height_m'], 'extents_m': meta['extents_m'],
                  'texture': meta.get('texture'),
                  'texture_sha256': meta.get('texture_sha256')}
    return spec, meta


def make_env(proto, spec):
    sc = proto['scene']
    return wheelleg_env.WheelLegEnv(spec, control_hz=float(sc['control_hz']),
                                    max_seconds=float(sc['budget_s']),
                                    v_ref=1.0, tip_deg=float(sc['tip_deg']))


def _render(model, data, cam_id, W, H):
    model.vis.global_.offwidth = max(int(W), int(model.vis.global_.offwidth))
    model.vis.global_.offheight = max(int(H), int(model.vis.global_.offheight))
    mujoco.mj_forward(model, data)
    r = mujoco.Renderer(model, int(H), int(W))
    r.update_scene(data, camera=cam_id)
    r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0
    rgb = r.render()
    r.enable_depth_rendering()
    r.update_scene(data, camera=cam_id)
    depth = r.render()
    r.disable_depth_rendering()
    r.close()
    return rgb, np.asarray(depth, dtype=np.float32)


def _mask_by_segmentation(model, data, cam_id, W, H, body_name='obstacle0'):
    """按障碍 body 的 geom id 取分割掩码；只反映"这一帧看得见哪些像素"。"""
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    if bid < 0:
        raise RuntimeError(f'找不到 {body_name}')
    geoms = [g for g in range(model.ngeom) if int(model.geom_bodyid[g]) == bid]
    if not geoms:
        raise RuntimeError(f'{body_name} 没有 geom')
    model.vis.global_.offwidth = max(int(W), int(model.vis.global_.offwidth))
    model.vis.global_.offheight = max(int(H), int(model.vis.global_.offheight))
    mujoco.mj_forward(model, data)
    r = mujoco.Renderer(model, int(H), int(W))
    r.enable_segmentation_rendering()
    r.update_scene(data, camera=cam_id)
    seg = r.render()
    r.disable_segmentation_rendering()
    r.close()
    return np.isin(np.asarray(seg)[:, :, 0], geoms)


def _unproject_masked(depth, mask, snap):
    """只反投影掩码内的像素（掩码外是地面/天空，不属于目标可见量）。"""
    ys, xs = np.nonzero(mask)
    z = np.asarray(depth, dtype=np.float64)[ys, xs]
    ok = np.isfinite(z) & (z > 0) & (z < 100.0)
    ys, xs, z = ys[ok], xs[ok], z[ok]
    K = snap['intrinsics']
    R = np.asarray(snap['R_world_from_camera'], dtype=np.float64).reshape(3, 3)
    t = np.asarray(snap['world_pos'], dtype=np.float64)
    pc = np.stack([(xs - K['cx']) * z / K['fx'], -(ys - K['cy']) * z / K['fy'], -z], axis=1)
    return pc @ R.T + t


def _pixel_box(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def _square_crop(box, pad_frac, W, H, min_side):
    x0, y0, x1, y1 = box
    w, h = x1 - x0 + 1, y1 - y0 + 1
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    side = max(w, h) * (1.0 + 2.0 * pad_frac)
    side = max(side, min_side)
    side = min(side, min(W, H))          # 不越界：越界会引入纯色补边
    half = side / 2.0
    x0c = int(round(cx - half)); y0c = int(round(cy - half))
    x0c = max(0, min(W - int(round(side)), x0c))
    y0c = max(0, min(H - int(round(side)), y0c))
    x1c = x0c + int(round(side)); y1c = y0c + int(round(side))
    return [x0c, y0c, x1c, y1c]


def _crop_image(img, box, out_size):
    from PIL import Image
    x0, y0, x1, y1 = box
    return np.asarray(Image.fromarray(img[y0:y1, x0:x1]).resize(
        (int(out_size), int(out_size)), Image.LANCZOS))


def _masked_variant(img, mask, box, out_size, bg=(232, 232, 232)):
    from PIL import Image
    x0, y0, x1, y1 = box
    H, W = img.shape[:2]
    rgb = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
    rgb[:, :] = bg
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(W, x1), min(H, y1)
    if sx1 > sx0 and sy1 > sy0:
        m = mask[sy0:sy1, sx0:sx1]
        sub = img[sy0:sy1, sx0:sx1].copy()
        rgb[sy0 - y0:sy0 - y0 + sub.shape[0], sx0 - x0:sx0 - x0 + sub.shape[1]][m] = sub[m]
    return np.asarray(Image.fromarray(rgb).resize((int(out_size), int(out_size)),
                                                  Image.LANCZOS))


def _variants(rgb_gen, mask_gen, box, out_dir, native_h_px, proto):
    """A/B/C 三类输入，全部由同一次真实渲染派生；不重绘、不伪造几何。"""
    from PIL import Image
    vdir = out_dir / 'variants'
    vdir.mkdir(parents=True, exist_ok=True)
    size = int(proto['inputs']['upload_px'])
    rec = {'schema': 'v3-inputs/v1', 'upload_px': size,
           'native_object_height_px': native_h_px, 'variants': {}}
    boxes = {
        'tight': _square_crop(box, float(proto['inputs']['tight_pad_frac']),
                              rgb_gen.shape[1], rgb_gen.shape[0], 64),
        'context': _square_crop(box, float(proto['inputs']['context_pad_frac']),
                                rgb_gen.shape[1], rgb_gen.shape[0], 64),
    }
    imgs = {
        'A': _crop_image(rgb_gen, boxes['tight'], size),
        'B': _masked_variant(rgb_gen, mask_gen, boxes['tight'], size),
        'C': _crop_image(rgb_gen, boxes['context'], size),
    }
    for cls, arr in imgs.items():
        for rep in (1, 2):
            name = f'{cls}{rep}.png'
            Image.fromarray(arr).save(vdir / name)
            # 上传后目标像素高度：按裁剪框内目标高度线性换算
            crop_h = boxes['tight' if cls in 'AB' else 'context'][3] - \
                boxes['tight' if cls in 'AB' else 'context'][1]
            up_h = native_h_px * (size / max(1, crop_h))
            rec['variants'][f'{cls}{rep}'] = {
                'path': str((vdir / name).relative_to(ROOT)),
                'sha256': sha256_file(vdir / name),
                'class': cls, 'repeat_idx': rep - 1,
                'crop_box': boxes['tight' if cls in 'AB' else 'context'],
                'uploaded_object_height_px': round(float(up_h), 1),
            }
    rec['native_ok'] = bool(native_h_px >= float(proto['inputs']['min_native_px']))
    rec['upload_ok'] = bool(all(v['uploaded_object_height_px'] >= proto['inputs']['min_native_px']
                                for v in rec['variants'].values()))
    (vdir / 'variants.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def capture_state(proto, rock_id, level_idx, view_idx, out_root):
    sid = f'{rock_id}_h{level_idx}v{view_idx}'
    d = out_root / 'states' / sid
    d.mkdir(parents=True, exist_ok=True)
    meta, _ = load_rock_level(proto, rock_id, level_idx)
    spec, meta = build_scene_spec(proto, rock_id, level_idx, view_idx)
    (d / 'scene_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    env = make_env(proto, spec)
    env.reset(seed=int(proto['scene']['reset_seed']))
    # 停稳：短暂制动保持，不改位置（机器人就在固定观察位出生）
    for _ in range(30):
        env.brake_step()
    snap = env.save_state()
    (d / 'state_snapshot.json').write_text(json.dumps(
        {k: v for k, v in snap.items() if k != 'mjstate'} |
        {'mjstate': snap['mjstate']}, ensure_ascii=False))
    model, data = env.model, env.data
    cam_id = observe.cam_id_of(env)
    obs_d = d / 'observation'
    obs_d.mkdir(parents=True, exist_ok=True)
    gen_d = obs_d / 'gen'
    gen_d.mkdir(parents=True, exist_ok=True)

    # ---- 规划相机（公共观测 O） ----
    plan = proto['cameras']['planning']
    Wp, Hp = int(plan['width']), int(plan['height'])
    model.cam_fovy[cam_id] = float(plan['fovy_deg'])
    mujoco.mj_forward(model, data)
    rgb_p, depth_p = _render(model, data, cam_id, Wp, Hp)
    mask_p = _mask_by_segmentation(model, data, cam_id, Wp, Hp)
    if mask_p.sum() < int(proto['visibility']['min_mask_px']):
        raise SystemExit(f'{sid}: 掩码像素过少 {int(mask_p.sum())}，观测不可用')
    snap_cam = camera_io.capture(model, data, cam_id, Wp, Hp)
    rng = np.random.default_rng(int(proto['visibility']['depth_noise_seed']))
    sigma = float(proto['visibility']['depth_noise_sigma_m'])
    depth_meas = np.asarray(depth_p, dtype=np.float32).copy()
    valid = np.isfinite(depth_meas) & (depth_meas > 0) & (depth_meas < 100.0)
    depth_meas[valid] = np.maximum(
        depth_meas[valid] + rng.normal(0.0, sigma, size=int(valid.sum())).astype(np.float32),
        1e-4)
    np.save(obs_d / 'depth.npy', depth_meas)
    np.save(obs_d / 'depth_clean.npy', np.asarray(depth_p, dtype=np.float32))
    from PIL import Image
    Image.fromarray(rgb_p).save(obs_d / 'rgb.png')
    Image.fromarray((mask_p * 255).astype(np.uint8)).save(obs_d / 'mask.png')
    pts = _unproject_masked(depth_meas, mask_p, snap_cam)
    np.save(obs_d / 'visible_points.npy', np.asarray(pts, dtype=np.float64))
    vis = {'n_pixels': int(len(pts)),
           'x_front': float(pts[:, 0].min()), 'y_center': float((pts[:, 1].min() + pts[:, 1].max()) / 2.0),
           'W_vis': float(pts[:, 1].max() - pts[:, 1].min()),
           'H_vis': float(pts[:, 2].max() - pts[:, 2].min())}
    obs_json = {
        'schema': 'v3-observation/v1', 'observation_id': sid, 'case_id': sid,
        'observation_protocol': VERSION,
        'rock': {'rock_id': rock_id, 'level': level_idx, 'view': view_idx,
                 'asset_meta': spec['v3']['asset_meta'],
                 'asset_meta_sha256': spec['v3']['asset_meta_sha256']},
        'camera_schema': camera_io.SCHEMA, 'camera': snap_cam,
        'image': {'W': Wp, 'H': Hp}, 'intrinsics': snap_cam['intrinsics'],
        'visible': vis,
        'mask_box': _pixel_box(mask_p),
        'depth_noise_sigma_m': sigma,
        'truth_hidden_read': False,
        'note': '只记录机器人自己能看到的量；隐藏真值不写入本文件',
    }
    (obs_d / 'observation.json').write_text(json.dumps(obs_json, ensure_ascii=False, indent=2))

    # ---- 生成相机（同一光心/朝向/视场，只提高分辨率；再裁切上传） ----
    gcfg = proto['cameras']['generation']
    dist = max(float(vis['x_front'] - snap_cam['world_pos'][0]), 0.15)
    ang_h = 2.0 * np.arctan(vis['H_vis'] / (2.0 * dist))
    ang_w = 2.0 * np.arctan(vis['W_vis'] / (2.0 * dist))
    aspect = float(gcfg['aspect'])
    fovy_gen = float(plan['fovy_deg'])          # 不换视场，避免目标被裁断
    fovy_rad = np.deg2rad(fovy_gen)
    target_px = float(gcfg['target_object_px'])
    need_h = target_px * fovy_rad / max(ang_h, 1e-3)
    need_w = target_px * fovy_rad / max(ang_w, 1e-3) * aspect
    H_gen = int(np.clip(np.ceil(max(need_h, need_w)),
                        int(gcfg['min_height_px']), int(gcfg['max_height_px'])))
    model.cam_fovy[cam_id] = fovy_gen
    # 渲染后实测目标像素高度；不足就按比例提高分辨率再渲（最多 3 次），
    # 不做任何上采样——原生像素必须真的够。
    best = None
    for _attempt in range(3):
        W_gen = int(round(H_gen * aspect))
        mujoco.mj_forward(model, data)
        rgb_g, depth_g = _render(model, data, cam_id, W_gen, H_gen)
        mask_g = _mask_by_segmentation(model, data, cam_id, W_gen, H_gen)
        box_g = _pixel_box(mask_g)
        if box_g is None:
            raise SystemExit(f'{sid}: 生成相机里看不到目标')
        native_h_px = float(box_g[3] - box_g[1] + 1)
        best = (rgb_g, depth_g, mask_g, box_g, native_h_px, W_gen, H_gen)
        if native_h_px >= target_px * 0.98:
            break
        H_gen = int(min(max(int(gcfg['max_height_px']), 6144),
                        np.ceil(H_gen * target_px / max(native_h_px, 1.0) * 1.02)))
    rgb_g, depth_g, mask_g, box_g, native_h_px, W_gen, H_gen = best
    snap_gen = camera_io.capture(model, data, cam_id, W_gen, H_gen)
    Image.fromarray(rgb_g).save(gen_d / 'rgb_gen.png')
    Image.fromarray((mask_g * 255).astype(np.uint8)).save(gen_d / 'mask_gen.png')
    np.save(gen_d / 'depth_gen.npy', np.asarray(depth_g, dtype=np.float32))
    touches = (box_g[0] <= 1 or box_g[1] <= 1
               or box_g[2] >= W_gen - 2 or box_g[3] >= H_gen - 2)
    (gen_d / 'gen_camera.json').write_text(json.dumps({
        'schema': 'v3-gen-camera/v1', 'camera': snap_gen,
        'fovy_deg': fovy_gen, 'width': W_gen, 'height': H_gen,
        'same_optical_center_and_orientation': True,
        'same_fovy_as_planning': True,
        'derived_from': 'planning camera pose/fovy (unchanged); only resolution increased',
        'planning_fovy_deg': float(plan['fovy_deg']),
        'mask_box': box_g, 'native_object_height_px': native_h_px,
        'object_angular_height_rad': float(ang_h),
        'object_angular_width_rad': float(ang_w),
        'truncated_at_frame_border': bool(touches),
        'resolution_attempts': _attempt + 1,
    }, ensure_ascii=False, indent=2))
    if touches:
        raise SystemExit(f'{sid}: 目标在生成图上触边（裁断），拒绝该观测')
    vin = _variants(rgb_g, mask_g, box_g, gen_d, native_h_px, proto)

    # ---- 真值世界网格（只给筛选/评估/揭晓） ----
    truth = d / 'truth'
    truth.mkdir(parents=True, exist_ok=True)
    stl = ROOT / spec['objects'][0]['mesh_file']
    import trimesh
    tm = trimesh.load(stl, force='mesh', process=False)
    yaw = np.deg2rad(float(spec['objects'][0]['yaw_deg']))
    Rz = np.array([[np.cos(yaw), -np.sin(yaw), 0.0],
                   [np.sin(yaw), np.cos(yaw), 0.0], [0.0, 0.0, 1.0]])
    Vw = np.asarray(tm.vertices, dtype=np.float64) @ Rz.T
    Vw[:, 2] -= Vw[:, 2].min()                       # env: body_z = -min z（平地）
    Vw[:, 0] += float(spec['objects'][0]['x'])
    Vw[:, 1] += float(spec['objects'][0]['y'])
    tw = trimesh.Trimesh(vertices=Vw, faces=np.asarray(tm.faces), process=False)
    tw.export(truth / 'body_world.stl')
    (truth / 'manifest.json').write_text(json.dumps({
        'schema': 'v3-truth/v1', 'source': str(stl.relative_to(ROOT)),
        'source_sha256': sha256_file(stl),
        'placement': {'x': float(spec['objects'][0]['x']),
                      'y': float(spec['objects'][0]['y']),
                      'yaw_deg': float(spec['objects'][0]['yaw_deg'])},
        'height_m': float(meta['height_m']),
        'body_world_sha256': sha256_file(truth / 'body_world.stl'),
        'visible_to_pipeline': False,
    }, ensure_ascii=False, indent=2))

    summary = {
        'schema': 'v3-state/v1', 'state_id': sid, 'rock_id': rock_id,
        'level': level_idx, 'view': view_idx, 'height_m': meta['height_m'],
        'hr_ratio': meta['hr_ratio'], 'extents_m': meta['extents_m'],
        'state_hash': snap.get('state_hash'), 'scene_signature': snap.get('scene_signature'),
        'env_t': snap.get('env_t'), 'visible': vis,
        'camera_world_pos': snap_cam['world_pos'],
        'camera_R': snap_cam['R_world_from_camera'], 'planning_fovy_deg': plan['fovy_deg'],
        'gen': {'fovy_deg': fovy_gen, 'width': W_gen, 'height': H_gen,
                'native_object_height_px': native_h_px},
        'inputs': vin, 'truth': {'body_world': 'truth/body_world.stl',
                                 'manifest': 'truth/manifest.json'},
        'scene_spec_sha256': sha256_file(d / 'scene_spec.json'),
        'observation_sha256': sha256_file(obs_d / 'observation.json'),
        'created': __import__('time').strftime('%Y-%m-%dT%H:%M:%S%z'),
    }
    (d / 'state.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({'state': sid, 'H': meta['height_m'], 'vis': vis,
                      'native_px': round(native_h_px, 1), 'gen': [W_gen, H_gen, round(fovy_gen, 1)],
                      'native_ok': vin['native_ok'], 'upload_ok': vin['upload_ok'],
                      'mask_px': int(mask_p.sum())}, ensure_ascii=False), flush=True)
    return summary


def view_yaw(spec):
    return float((spec.get('objects') or [{}])[0].get('yaw_deg', 0.0))


def parse_states(proto, tokens):
    """moon_rock_02:L1:V0 或 all（按协议网格展开）。"""
    out = []
    for t in tokens:
        if t == 'all':
            for rock in proto['grid']['rocks']:
                for lv in proto['grid']['levels']:
                    for v in proto['grid']['views']:
                        out.append((rock, int(lv), int(v)))
            continue
        parts = t.split(':')
        rock = parts[0]
        lv = int(parts[1].lstrip('LlhH')) if len(parts) > 1 else 1
        vv = int(parts[2].lstrip('Vv')) if len(parts) > 2 else 0
        out.append((rock, lv, vv))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--states', nargs='+', default=['all'])
    ap.add_argument('--out', default='runs/v3')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    out_root = ROOT / a.out
    out_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for rock, lv, vv in parse_states(proto, a.states):
        try:
            rows.append(capture_state(proto, rock, lv, vv, out_root))
        except SystemExit as e:
            rows.append({'rock_id': rock, 'level': lv, 'view': vv, 'error': str(e)})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001
            rows.append({'rock_id': rock, 'level': lv, 'view': vv,
                         'error': f'{type(e).__name__}: {e}'})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    idx = {'schema': 'v3-states-index/v1', 'protocol': a.protocol,
           'protocol_sha256': sha256_file(ROOT / a.protocol),
           'n': len(rows), 'states': rows}
    (out_root / 'states_index.json').write_text(json.dumps(idx, ensure_ascii=False, indent=2))
    print(json.dumps({'n': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
