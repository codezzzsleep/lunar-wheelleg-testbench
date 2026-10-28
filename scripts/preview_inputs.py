"""
新输入预览包：三个相机高度 × 有/无岩石纹理，纯离线、不触发生成。

  MUJOCO_GL=osmesa .venv/bin/python scripts/preview_inputs.py \
      --case cases/unseen_v1/planA.json --out runs/unseen/recovery_r3/input_preview
"""
import argparse, json, pathlib, sys
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco, terrain, wheelleg_env
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
HEIGHTS = (0.16, 0.24, 0.32)


def render(case, cam_h, textured, out_png, W=1280, H=960):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.8, name='prev')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    if textured:
        spec['object_material'] = {'name': 'rock',
                                   'texture': str((ROOT / 'assets/textures/rock_v1.png').resolve())}
    spec['objects'] = [{'mesh_file': str(pathlib.Path(case['mesh']).resolve()),
                        'x': case['obstacle_x'], 'y': 0.0, 'yaw_deg': 0.0,
                        'target_height_m': case['H']}]
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    bid = m.cam_bodyid[cid]
    B = np.asarray(d.xmat[bid]).reshape(3, 3); b = np.asarray(d.xpos[bid])
    m.cam_pos[cid][2] = (cam_h - b[2] - B[2, 0] * 0.42) / B[2, 2]
    mujoco.mj_forward(m, d)
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    r = mujoco.Renderer(m, H, W)
    r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0
    r.update_scene(d, camera=cid)
    img = r.render()
    r.enable_depth_rendering(); r.update_scene(d, camera=cid)
    dep = r.render().copy()
    r.disable_depth_rendering()
    m.body_pos[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')] = [0, 0, -80]
    mujoco.mj_forward(m, d)
    r.enable_depth_rendering(); r.update_scene(d, camera=cid); bg = r.render().copy()
    r.disable_depth_rendering()
    mask = np.isfinite(dep) & np.isfinite(bg) & (dep < bg - 1e-3) & (dep > 0) & (dep < 100)
    Image.fromarray(img).save(out_png)
    return {'cam_world_z': round(float(d.cam_xpos[cid][2]), 4),
            'mask_px': int(mask.sum()),
            'target_mean_luma': round(float(np.array(Image.fromarray(img).convert('L'))[mask].mean()), 1) if mask.any() else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    case = json.loads(pathlib.Path(a.case).read_text())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for h in HEIGHTS:
        for tex in (False, True):
            tag = f'cam{h:.2f}_{"tex" if tex else "plain"}'
            p = out / f'{tag}.png'
            info = render(case, h, tex, p)
            rows.append({'tag': tag, 'cam_height_requested': h, **info, 'path': str(p)})
    (out / 'preview_manifest.json').write_text(json.dumps(
        {'case': str(a.case), 'heights_m': list(HEIGHTS),
         'texture': 'assets/textures/rock_v1.png (seed 7, 只改视觉不改碰撞)',
         'note': '预览用，未提交生成；需用户确认后才执行试点',
         'rows': rows}, indent=2, ensure_ascii=False))
    for r in rows:
        print(r['tag'], 'cam_z', r['cam_world_z'], 'luma', r['target_mean_luma'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
