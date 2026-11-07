"""V7 视觉层：把仿真环境的 MJCF 换上月面外观，用于机器人相机照片与成片渲染。

只改外观（材质、贴图、光照、天空、远景、车道外装饰），不改任何参与碰撞的几何、
不改 body/joint 结构，因此 qpos 可以从仿真环境逐帧原样拷贝过来。

用法：
    vm = VisualModel(env, rocks={'obstacle1': 'moon_rock_02', ...})
    rgb, depth, seg = vm.render_camera(env.data, 'front_cam', 1600, 1200)
"""
import os
import pathlib
import re
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lunar_world as LW  # noqa: E402  贴图、远山、地球、两面岩石网格

# 仓库内岩石资产根目录（本地与沙箱都用仓库路径；可用环境变量覆盖）
ROCK_ROOT = pathlib.Path(os.environ.get('V7_ROCK_ROOT', str(HERE.parents[1] / 'assets/v3/rocks')))
LW.ROCKS = ROCK_ROOT


def _strip_lights(xml):
    return re.sub(r'<light\b[^>]*/>', '', xml)


def visual_xml(env_xml, rock_bodies, lane_half=1.2, width=1600, height=1200,
               sun_dir=(0.35, -0.80, -0.48), deco=True, route_x=(-6.0, 30.0)):
    """rock_bodies: {body_name: rock_id}，这些 body 下的网格几何换成该岩石的贴图材质。"""
    reg, sky, earth = LW.regolith_texture(), LW.sky_texture(), LW.earth_texture()
    xml = _strip_lights(env_xml)
    assets = [f'<texture name="v7_reg" type="2d" file="{reg}"/>',
              '<material name="v7_reg" texture="v7_reg" texuniform="true" texrepeat="0.9 0.9" specular="0" shininess="0"/>',
              f'<texture name="v7_sky" type="skybox" file="{sky}"/>',
              f'<texture name="v7_earth" type="2d" file="{earth}"/>',
              '<material name="v7_earth" texture="v7_earth" emission="0.22" specular="0.1" shininess="0.2"/>',
              '<material name="v7_atmo" rgba="0.35 0.55 1.0 0.18" emission="1"/>',
              f'<mesh name="v7_mtn" file="{LW.mountain_mesh()}"/>',
              '<material name="v7_mtn" texture="v7_reg" texuniform="true" texrepeat="0.05 0.05" rgba="0.62 0.62 0.62 1" specular="0"/>']
    for rid in sorted(set(rock_bodies.values())):
        assets.append(f'<texture name="v7_t_{rid}" type="2d" file="{LW.lunar_tex(rid)}"/>')
        assets.append(f'<material name="v7_m_{rid}" texture="v7_t_{rid}" specular="0.06" shininess="0.05"/>')
    world = ['<geom name="v7_far_ground" type="plane" size="150 150 0.1" pos="0 0 -0.02" material="v7_reg" contype="0" conaffinity="0"/>',
             '<geom name="v7_mtn" type="mesh" mesh="v7_mtn" material="v7_mtn" contype="0" conaffinity="0"/>',
             '<geom name="v7_earth" type="sphere" size="9" pos="170 -40 36" material="v7_earth" euler="20 -10 40" contype="0" conaffinity="0"/>',
             '<geom name="v7_atmo" type="sphere" size="9.35" pos="170 -40 36" material="v7_atmo" contype="0" conaffinity="0"/>']
    if deco:       # 车道外的装饰碎石（只做视觉，|y| > lane_half + 0.3）
        rng = np.random.default_rng(3)
        pool = [r for r in ('moon_rock_01', 'moon_rock_03', 'moon_rock_04', 'moon_rock_05', 'moon_rock_06', 'moon_rock_07')
                if (ROCK_ROOT / r / 'h2' / 'body_vis.obj').exists()]
        for rid in pool:
            if rid not in rock_bodies.values():
                assets.append(f'<texture name="v7_t_{rid}" type="2d" file="{LW.lunar_tex(rid)}"/>')
                assets.append(f'<material name="v7_m_{rid}" texture="v7_t_{rid}" specular="0.06" shininess="0.05"/>')
        for i in range(70):
            x = rng.uniform(*route_x); y = rng.choice([-1, 1]) * (lane_half + 0.3 + rng.exponential(2.4))
            if abs(y) > 20:
                continue
            rid = pool[rng.integers(len(pool))]
            s = float(np.clip(rng.lognormal(-0.1, 0.6), 0.3, 3.5)) * (1.0 + 0.25 * max(0, abs(y) - 4))
            obj, _ = LW.rock_asset(rid, 'h2')
            assets.append(f'<mesh name="v7_deco{i}" file="{obj}" scale="{s:.3f} {s:.3f} {s:.3f}"/>')
            world.append(f'<geom name="v7_deco{i}" type="mesh" mesh="v7_deco{i}" material="v7_m_{rid}" '
                         f'pos="{x:.3f} {y:.3f} {-0.01 * s:.4f}" euler="0 0 {rng.uniform(0, 360):.1f}" contype="0" conaffinity="0"/>')
    sd = np.array(sun_dir, float); sd /= np.linalg.norm(sd)
    world.insert(0, f'<light name="v7_sun" directional="true" castshadow="true" dir="{sd[0]:.3f} {sd[1]:.3f} {sd[2]:.3f}" '
                    'diffuse="1.75 1.72 1.66" specular="0.25 0.25 0.25" ambient="0.035 0.037 0.045"/>')
    xml = xml.replace('<asset>', '<asset>' + ''.join(assets), 1)
    xml = xml.replace('<worldbody>', '<worldbody>' + ''.join(world), 1)
    xml = re.sub(r'<headlight\b[^>]*/>', '', xml)
    vis = ('<visual><headlight ambient="0.05 0.05 0.06" diffuse="0.05 0.05 0.05" specular="0 0 0"/>'
           '<quality shadowsize="8192" offsamples="8"/><map shadowclip="6" shadowscale="0.5" znear="0.01" zfar="600"/>'
           f'<global offwidth="{max(4040, width)}" offheight="{max(3030, height)}"/></visual>')
    xml = xml.replace('</mujoco>', vis + '<statistic center="2 0 0.3" extent="1"/></mujoco>')
    return xml


class VisualModel:
    """与仿真环境同构的可视模型：同样的 body/joint/碰撞几何，只是外观不同。"""

    def __init__(self, env, rock_bodies, width=1600, height=1200, **kw):
        import mujoco
        self.mj = mujoco
        xml = visual_xml(env._xml, rock_bodies, width=width, height=height, **kw)
        self.m = mujoco.MjModel.from_xml_string(xml)
        self.d = mujoco.MjData(self.m)
        if self.m.nq != env.model.nq or self.m.nbody != env.model.nbody:
            raise RuntimeError('visual model is not isomorphic to the physics model')
        # 岩石网格换材质；地形换月壤；机器人换白橙配色
        self.rock_geoms = {}
        for gi in range(self.m.ngeom):
            b = mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_BODY, self.m.geom_bodyid[gi]) or ''
            if b in rock_bodies and self.m.geom_type[gi] == mujoco.mjtGeom.mjGEOM_MESH:
                mid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_MATERIAL, f'v7_m_{rock_bodies[b]}')
                self.m.geom_matid[gi] = mid
                self.m.geom_rgba[gi] = [1, 1, 1, 1]
                self.rock_geoms.setdefault(b, []).append(gi)
            elif self.m.geom_type[gi] == mujoco.mjtGeom.mjGEOM_HFIELD:
                self.m.geom_matid[gi] = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_MATERIAL, 'v7_reg')
                self.m.geom_rgba[gi] = [1, 1, 1, 1]
        LW.style_robot(self.m)
        self._renderers = {}
        self.r = self._renderer(width, height)
        self.W, self.H = width, height

    def _renderer(self, w, h):
        if (w, h) not in self._renderers:
            self._renderers[(w, h)] = self.mj.Renderer(self.m, h, w, max_geom=20000)
        return self._renderers[(w, h)]

    def set_sun(self, sun_dir):
        """运行时改太阳方向（光线传播方向），不重建模型、不新开渲染上下文。"""
        lid = self.mj.mj_name2id(self.m, self.mj.mjtObj.mjOBJ_LIGHT, 'v7_sun')
        d = np.asarray(sun_dir, float); d /= np.linalg.norm(d)
        self.m.light_dir[lid] = d

    def close(self):
        for r in self._renderers.values():
            try:
                r.close()
            except Exception:
                pass
        self._renderers = {}

    def sync(self, data):
        self.d.qpos[:] = data.qpos
        self.d.qvel[:] = 0
        self.mj.mj_forward(self.m, self.d)

    def render_camera(self, data, cam_name, depth=True, seg=True, size=None):
        """返回 rgb (H,W,3)、depth (H,W，米，正 = 相机前方)、seg (H,W，geom id，-1 为背景)。"""
        w, h = size or (self.W, self.H)
        r = self._renderer(w, h)
        self.sync(data)
        cid = self.mj.mj_name2id(self.m, self.mj.mjtObj.mjOBJ_CAMERA, cam_name)
        r.update_scene(self.d, camera=cid)
        rgb = r.render().copy()
        out = [rgb]
        if depth:
            r.enable_depth_rendering(); r.update_scene(self.d, camera=cid)
            out.append(r.render().copy()); r.disable_depth_rendering()
        if seg:
            r.enable_segmentation_rendering(); r.update_scene(self.d, camera=cid)
            s = r.render().copy(); r.disable_segmentation_rendering()
            gid = np.where(s[..., 1] == int(self.mj.mjtObj.mjOBJ_GEOM), s[..., 0], -1)
            out.append(gid)
        return out

    def render_free(self, data, lookat, distance, azimuth, elevation, fovy=45.0):
        self.sync(data)
        self.m.vis.global_.fovy = fovy
        cam = self.mj.MjvCamera(); cam.type = self.mj.mjtCamera.mjCAMERA_FREE
        cam.lookat[:] = lookat; cam.distance = distance; cam.azimuth = azimuth; cam.elevation = elevation
        self.r.update_scene(self.d, camera=cam)
        return self.r.render().copy()
