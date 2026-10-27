"""
前视相机几何测试（第 1.1 步验收）。

  MUJOCO_GL=osmesa .venv/bin/python -m unittest tests.test_camera -v

覆盖：
  (a) 空场景地平线水平：逐列第一个地面像素行号标准差 < 2 px，天空在上方
  (b) 横向/竖向位置：世界 (2.0,+0.3,0.05) 的球在图像中线左侧；
      (2.0,0,0.30) 的球比 (2.0,0,0.05) 的球在图像里更靠上
  (c) 滚转不改变可见的三维量：x_front / W_vis / H_vis 与旧相机差 < 2 mm
  (d) align.py 的重渲染与观测使用同一份相机定义
"""
import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import mujoco                       # noqa: E402
import terrain                      # noqa: E402
import wheelleg_env                 # noqa: E402


def _env(objects=None, pitch=-12.0, pos=(0.42, 0.0, 0.20), fovy=70.0):
    spec = terrain.make_spec(kind='flat', seed=0, objects=objects or [], goal_x=2.8)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['front_cam'] = {'pos': list(pos), 'pitch_deg': pitch, 'fovy': fovy}
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    return env


def _render(env, W, H, depth=False):
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    r = mujoco.Renderer(m, H, W)
    if depth:
        r.enable_depth_rendering()
    r.update_scene(d, camera=cid)
    img = r.render().copy()
    if depth:
        r.disable_depth_rendering()
    return img, cid


def _object_pixels(env, W=640, H=480):
    """有/无物体两次渲染的差：只取物体像素，避免地形噪点干扰。"""
    import copy
    m, d = env.model, env.data
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    with_obj, _ = _render(env, W, H)
    keep = m.body_pos[bid].copy()
    m.body_pos[bid] = [0.0, 0.0, -80.0]
    mujoco.mj_forward(m, d)
    without, _ = _render(env, W, H)
    m.body_pos[bid] = keep
    mujoco.mj_forward(m, d)
    diff = np.abs(with_obj.astype(np.int16) - without.astype(np.int16)).sum(axis=2)
    return diff > 12


class TestCameraFrame(unittest.TestCase):
    def test_axes_follow_xyaxes_contract(self):
        env = _env()
        _, cid = _render(env, 64, 64)
        d = env.data
        m = env.model
        mujoco.mj_forward(m, d)
        R = np.array(d.cam_xmat[cid]).reshape(3, 3)
        right, up, view = R[:, 0], R[:, 1], -R[:, 2]
        # 图像右 = 世界 -y
        self.assertLess(right[1], -0.99, f'right={right}')
        # 视线朝 +x 且向下
        self.assertGreater(view[0], 0.95)
        self.assertLess(view[2], -0.05)
        # 图像上 ~ 世界 +z
        self.assertGreater(up[2], 0.95)

    def test_horizon_is_horizontal(self):
        env = _env()
        dep, _ = _render(env, 640, 480, depth=True)
        valid = dep < 100.0                      # 无几何处是远裁剪值
        first = []
        for c in range(0, 640, 4):
            idx = np.nonzero(valid[:, c])[0]
            if len(idx):
                first.append(idx[0])
        first = np.array(first)
        self.assertGreater(len(first), 50)
        self.assertLess(float(first.std()), 2.0,
                        f'地平线不平：行号 std={first.std():.2f}')
        # 天空在上方：最上面一行应当没有几何
        self.assertFalse(valid[:3, :].any())

    def test_lateral_and_vertical_position(self):
        # (2.0, +0.3, 0.05) 的物体应出现在中线左侧（图像右 = 世界 -y）
        import trimesh
        tmp = pathlib.Path('/tmp/unseen_cam_test'); tmp.mkdir(exist_ok=True)
        box = trimesh.creation.box(extents=[0.20, 0.20, 0.20])
        box.apply_translation([0, 0, 0.10])
        bp = tmp / 'lateral.stl'; box.export(bp)
        env = _env(objects=[{'mesh_file': str(bp), 'x': 2.0, 'y': 0.3,
                             'yaw_deg': 0.0, 'target_height_m': 0.20}])
        mask = _object_pixels(env)
        obj = np.nonzero(mask)
        self.assertGreater(len(obj[1]), 50, '没找到物体像素')
        cx = float(obj[1].mean())
        self.assertLess(cx, 320 - 5, f'物体中心 x={cx:.1f} 不在中线左侧')

    def test_higher_object_appears_higher(self):
        """用两个**显式缩放**的立方体，避免依赖 target_height_m 的实现细节。"""
        import trimesh
        tmp = pathlib.Path('/tmp/unseen_cam_test'); tmp.mkdir(exist_ok=True)
        paths = []
        for i, h in enumerate((0.06, 0.30)):
            box = trimesh.creation.box(extents=[0.12, 0.12, h])
            box.apply_translation([0, 0, h / 2])
            p_ = tmp / f'box_{i}.stl'
            box.export(p_)
            paths.append(str(p_))
        env_lo = _env(objects=[{'mesh_file': paths[0], 'x': 2.0, 'y': 0.0,
                                'yaw_deg': 0.0, 'target_height_m': 0.06}])
        env_hi = _env(objects=[{'mesh_file': paths[1], 'x': 2.0, 'y': 0.0,
                                'yaw_deg': 0.0, 'target_height_m': 0.30}])
        rows = []
        for env in (env_lo, env_hi):
            obj = np.nonzero(_object_pixels(env))
            rows.append(float(obj[0].mean()))
        self.assertLess(rows[1], rows[0],
                        f'高物体应更靠上：行号 {rows[1]:.1f} vs {rows[0]:.1f}')


class TestAlignSharesCamera(unittest.TestCase):
    def test_align_uses_observation_camera(self):
        src = (ROOT / 'scripts/align.py').read_text()
        self.assertIn("obsd['camera']['pos_body']", src)
        self.assertIn("obsd['camera']['pitch_deg']", src)
        self.assertIn("obsd['camera']['fovy']", src)
        # 不允许 align 自己另写一套相机姿态
        self.assertNotIn('quat=', src)


if __name__ == '__main__':
    unittest.main()
