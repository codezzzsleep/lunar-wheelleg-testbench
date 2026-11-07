"""成片专用的视觉模型：在 v7 视觉层之上
  · 隐藏机身上的品牌字样（base_link 的第 4 个网格），加一个相机"头"（只做外观）；
  · 把 Lux3D 生成的 GLB 作为 mocap 物体放进场景（不参与物理），两套外观：
      组 4 = 原贴图（想象出的真实样子），组 5 = 青色全息；
  · 每帧可设置每个全息体的位姿、显示哪一组。
"""
import pathlib
import re
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parent / 'v7'))
import v7_visual as VV
import lunar_world as LW

import os
CACHE = pathlib.Path(os.environ.get('V8_HOLO_CACHE', str(HERE.parents[1] / 'runs/v8/cache/holo')))


def glb_to_obj(glb, scale=1.0, name=None):
    """GLB -> 带 UV 的 OBJ + 贴图 PNG（顶点乘以 scale）。返回 (obj, png 或 None)。"""
    import trimesh
    glb = pathlib.Path(glb)
    name = name or glb.parent.name
    out = CACHE / name; out.mkdir(parents=True, exist_ok=True)
    obj = out / f'mesh_s{scale:.5f}.obj'
    png = out / 'tex.png'
    if obj.exists():
        return obj, (png if png.exists() else None)
    mesh = trimesh.load(str(glb), force='mesh', process=False)
    V = np.asarray(mesh.vertices) * scale
    F = np.asarray(mesh.faces)
    uv = None
    try:
        uv = np.asarray(mesh.visual.uv)
        img = mesh.visual.material.baseColorTexture if hasattr(mesh.visual.material, 'baseColorTexture') else mesh.visual.material.image
        if img is not None:
            im2 = img.convert('RGB'); im2.thumbnail((1024, 1024)); im2.save(png)
    except Exception:
        uv = None
    lines = [f'v {a:.6f} {b:.6f} {c:.6f}' for a, b, c in V]
    if uv is not None and len(uv) == len(V):
        lines += [f'vt {u:.6f} {v:.6f}' for u, v in uv]
        lines += [f'f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}' for a, b, c in F]
    else:
        lines += [f'f {a+1} {b+1} {c+1}' for a, b, c in F]
    obj.write_text('\n'.join(lines) + '\n')
    return obj, (png if png.exists() else None)


def decompose(M):
    """M = [sR | t]（registration 输出，均匀缩放） -> s, R, t。"""
    M = np.asarray(M, float)
    A = M[:3, :3]
    s = float(np.cbrt(np.linalg.det(A)))
    R = A / s
    U, _, Vt = np.linalg.svd(R); R = U @ Vt
    return s, R, M[:3, 3].copy()


def mat2quat(R):
    import mujoco
    q = np.zeros(4); mujoco.mju_mat2Quat(q, np.asarray(R, float).reshape(-1)); return q


class VideoModel:
    def __init__(self, env, rock_bodies, holos=(), width=1920, height=1080, shadowclip=8.0):
        """holos: [{'name', 'glb', 'scale'}]。"""
        import mujoco
        self.mj = mujoco
        xml = VV.visual_xml(env._xml, rock_bodies, width=width, height=height)
        xml = xml.replace('shadowclip="6"', f'shadowclip="{shadowclip}"')
        # 成片最大 1920×1080：离屏缓冲不必按 4040×3030 的观测图分配（每个渲染器省约 0.7 GB）
        xml = xml.replace('offwidth="4040" offheight="3030"', 'offwidth="1920" offheight="1080"').replace('offsamples="8"', 'offsamples="6"')
        # 机身外壳：原外壳网格（base_3/base_4）带刻字，换成它的凸包（同样轮廓，没有字样）；前端加相机模块（只做外观）
        shell = self._shell_obj(env._xml)
        head = (f'<geom name="vid_shell" type="mesh" mesh="vid_shell" rgba="0.94 0.94 0.93 1" contype="0" conaffinity="0" group="1"/>'
                '<geom name="vid_head" type="box" size="0.016 0.056 0.03" pos="0.345 0 0.012" rgba="0.92 0.92 0.91 1" contype="0" conaffinity="0" group="1"/>'
                '<geom name="vid_glass" type="box" size="0.004 0.047 0.02" pos="0.362 0 0.012" rgba="0.04 0.05 0.07 1" contype="0" conaffinity="0" group="1"/>'
                '<geom name="vid_lensL" type="cylinder" size="0.009 0.002" pos="0.367 0.022 0.012" euler="0 90 0" rgba="0.35 0.85 1 1" contype="0" conaffinity="0" group="1"/>'
                '<geom name="vid_lensR" type="cylinder" size="0.009 0.002" pos="0.367 -0.022 0.012" euler="0 90 0" rgba="0.35 0.85 1 1" contype="0" conaffinity="0" group="1"/>')
        xml = xml.replace('<asset>', f'<asset><mesh name="vid_shell" file="{shell}"/>', 1)
        xml = re.sub(r'(<body name="base_link"[^>]*>)', r'\1' + head, xml, count=1)
        assets, bodies = [], []
        self.holo_names = []
        for h in holos:
            obj, png = glb_to_obj(h['glb'], h.get('scale', 1.0), h['name'])
            n = h['name']
            assets.append(f'<mesh name="hm_{n}" file="{obj}"/>')
            if png is not None:
                assets.append(f'<texture name="ht_{n}" type="2d" file="{png}"/>')
                assets.append(f'<material name="hmt_{n}" texture="ht_{n}" specular="0.05" shininess="0.05"/>')
            else:
                assets.append(f'<material name="hmt_{n}" rgba="0.6 0.6 0.6 1" specular="0.05"/>')
            assets.append(f'<material name="hmc_{n}" rgba="0.30 0.85 1.0 0.42" emission="0.9" specular="0.6" shininess="0.8"/>')
            bodies.append(f'<body name="hb_{n}" mocap="true" pos="0 0 -50">'
                          f'<geom name="hg_{n}" type="mesh" mesh="hm_{n}" material="hmt_{n}" group="4" contype="0" conaffinity="0"/>'
                          f'<geom name="hc_{n}" type="mesh" mesh="hm_{n}" material="hmc_{n}" group="5" contype="0" conaffinity="0"/></body>')
            self.holo_names.append(n)
        xml = xml.replace('<asset>', '<asset>' + ''.join(assets), 1)
        xml = xml.replace('</worldbody>', ''.join(bodies) + '</worldbody>', 1)
        self.m = mujoco.MjModel.from_xml_string(xml)
        self.d = mujoco.MjData(self.m)
        if self.m.nq != env.model.nq:
            raise RuntimeError('video model nq mismatch')
        m = self.m
        self.rock_geoms = {}
        for gi in range(m.ngeom):
            b = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[gi]) or ''
            if b in rock_bodies and m.geom_type[gi] == mujoco.mjtGeom.mjGEOM_MESH:
                m.geom_matid[gi] = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, f'v7_m_{rock_bodies[b]}')
                m.geom_rgba[gi] = [1, 1, 1, 1]
                self.rock_geoms.setdefault(b, []).append(gi)
            elif m.geom_type[gi] == mujoco.mjtGeom.mjGEOM_HFIELD:
                m.geom_matid[gi] = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, 'v7_reg')
                m.geom_rgba[gi] = [1, 1, 1, 1]
        LW.style_robot(m)
        for gi in range(m.ngeom):
            b = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[gi]) or ''
            if b == 'base_link' and m.geom_type[gi] == mujoco.mjtGeom.mjGEOM_MESH and m.geom_contype[gi] == 0:
                mesh = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_MESH, m.geom_dataid[gi])
                m.geom_matid[gi] = -1
                m.geom_rgba[gi] = [0.94, 0.94, 0.93, 1] if mesh in ('base_3', 'base_4', 'vid_shell') else [0.16, 0.16, 0.18, 1]
                if mesh in ('base_3', 'base_4'):          # 原外壳（带刻字）不渲染，由凸包外壳 vid_shell 代替
                    m.geom_group[gi] = 3
        self.hg = {n: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f'hg_{n}') for n in self.holo_names}
        self.hc = {n: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f'hc_{n}') for n in self.holo_names}
        self.mocap = {n: int(m.body_mocapid[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'hb_{n}')]) for n in self.holo_names}
        self.W, self.H = width, height
        self._r = None                                   # 渲染器按需创建（每个渲染上下文都会复制一份全部贴图，很占内存）
        self.opt = mujoco.MjvOption()
        self.rock_body_ids = {b: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, b) for b in rock_bodies}


    @staticmethod
    def _shell_obj(env_xml):
        """编译一次原模型，取 base_link 的 base_3 + base_4 网格顶点（机身坐标系），做凸包，写成 OBJ。"""
        import mujoco, trimesh
        out = CACHE / 'robot_shell.obj'
        if out.exists():
            return out
        m = mujoco.MjModel.from_xml_string(env_xml)
        pts = []
        for gi in range(m.ngeom):
            if m.geom_type[gi] != mujoco.mjtGeom.mjGEOM_MESH:
                continue
            if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_MESH, m.geom_dataid[gi]) or '') not in ('base_3', 'base_4'):
                continue
            mid = m.geom_dataid[gi]
            V = m.mesh_vert[m.mesh_vertadr[mid]:m.mesh_vertadr[mid] + m.mesh_vertnum[mid]]
            R = np.zeros(9); mujoco.mju_quat2Mat(R, m.geom_quat[gi])
            pts.append(V @ R.reshape(3, 3).T + m.geom_pos[gi])
        hull = trimesh.Trimesh(np.concatenate(pts), process=True).convex_hull
        CACHE.mkdir(parents=True, exist_ok=True)
        hull.export(str(out))
        return out

    @property
    def r(self):
        if self._r is None:
            self._r = self.mj.Renderer(self.m, self.H, self.W, max_geom=30000)
        return self._r

    # ---------------------------------------------------------------- 状态
    def set_sun(self, sun_dir):
        lid = self.mj.mj_name2id(self.m, self.mj.mjtObj.mjOBJ_LIGHT, 'v7_sun')
        d = np.asarray(sun_dir, float); self.m.light_dir[lid] = d / np.linalg.norm(d)

    def set_holo(self, name, pos=None, quat=None):
        i = self.mocap[name]
        self.d.mocap_pos[i] = pos if pos is not None else [0, 0, -50]
        if quat is not None:
            self.d.mocap_quat[i] = quat

    def hide_all_holos(self):
        for n in self.holo_names:
            self.set_holo(n, None)

    def holo_alpha(self, name, alpha):
        mid = self.m.geom_matid[self.hc[name]]
        self.m.mat_rgba[mid][3] = alpha

    def sync(self, qpos):
        self.d.qpos[:] = qpos; self.d.qvel[:] = 0
        self.mj.mj_forward(self.m, self.d)

    # ---------------------------------------------------------------- 渲染
    def _cam(self, lookat, distance, azimuth, elevation):
        cam = self.mj.MjvCamera(); cam.type = self.mj.mjtCamera.mjCAMERA_FREE
        cam.lookat[:] = lookat; cam.distance = distance; cam.azimuth = azimuth; cam.elevation = elevation
        return cam

    def render(self, cam, fovy=45.0, groups=(0, 1, 2, 4), seg=False):
        """cam: MjvCamera 或相机名。groups: 显示的几何组（4 = 原贴图想象，5 = 青色全息）。"""
        self.m.vis.global_.fovy = fovy
        for g in range(6):
            self.opt.geomgroup[g] = 1 if g in groups else 0
        if isinstance(cam, str):
            cam = self.mj.mj_name2id(self.m, self.mj.mjtObj.mjOBJ_CAMERA, cam)
        self.r.update_scene(self.d, camera=cam, scene_option=self.opt)
        if seg:
            self.r.enable_segmentation_rendering(); out = self.r.render().copy(); self.r.disable_segmentation_rendering()
            return out[..., 0]
        return self.r.render().copy()

    def free(self, lookat, distance, azimuth, elevation, fovy=45.0, groups=(0, 1, 2, 4), seg=False):
        return self.render(self._cam(lookat, distance, azimuth, elevation), fovy, groups, seg)
