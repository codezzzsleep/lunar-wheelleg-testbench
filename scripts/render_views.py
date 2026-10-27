"""
为页面渲染三维视图：候选背面侧视、真值揭晓、选定动作回放帧。

  MUJOCO_GL=osmesa .venv/bin/python scripts/render_views.py --case ... --out ...

侧视相机从 +y 方向看，能同时看到正面与背面，用于"揭晓"和候选对比。
"""
import json, pathlib, sys
import numpy as np, mujoco
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain, wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def side_cam_spec(posed_dir, H, x, seed):
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=2.8)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['objects'] = [{'posed_dir': str(posed_dir), 'x': x, 'y': 0.0,
                        'yaw_deg': 0.0, 'target_height_m': H}]
    return spec


def render_side(posed_dir, H, x, out_png, W=720, Hh=420, seed=0):
    """从 +y 侧上方看整个障碍（含背面）。"""
    spec = side_cam_spec(posed_dir, H, x, seed)
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)
    m.vis.global_.offwidth, m.vis.global_.offheight = W, Hh
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = [x + 0.10, 0.0, H * 0.6]
    cam.distance = max(0.9, 4.5 * H + 0.6)
    cam.azimuth = 90.0     # 从 +y 方向看
    cam.elevation = -18.0
    r = mujoco.Renderer(m, Hh, W)
    r.update_scene(d, camera=cam)
    img = r.render()
    from PIL import Image
    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(out_png)
    return out_png


def render_replay(posed_dir, H, x, option, seed, out_dir, n_frames=8, W=640, Hh=400):
    """执行过程回放：按时间均匀取帧，存 png。"""
    import runner, skills
    spec = side_cam_spec(posed_dir, H, x, seed)
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=15.0)
    env.plan_visible = {}
    sk = skills.make_skill(option); sk.reset({})
    obs, _ = env.reset(seed=seed)
    m, d = env.model, env.data
    m.vis.global_.offwidth, m.vis.global_.offheight = W, Hh
    r = mujoco.Renderer(m, Hh, W)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, done, steps = [], False, 0
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.distance = 1.5; cam.azimuth = 90.0; cam.elevation = -16.0
    while not done and steps < 1200:
        rs = env.robot_state()
        a = sk.act(obs, rs)
        obs, _, te, tr, info = env.step(a)
        done = te or tr
        steps += 1
        if steps % 40 == 0:
            cam.lookat[:] = [float(d.qpos[0]), 0.0, 0.14]
            r.update_scene(d, camera=cam)
            frames.append(r.render())
    from PIL import Image
    idx = np.linspace(0, len(frames) - 1, min(n_frames, len(frames))).astype(int) if frames else []
    paths = []
    for k, i in enumerate(idx):
        p = out_dir / f'frame_{k:02d}.png'
        Image.fromarray(frames[int(i)]).save(p)
        paths.append(str(p))
    return paths
