"""
Gymnasium 风格的轮腿训练环境。

接口：
    env = WheelLegEnv(spec)
    obs, info = env.reset(seed=0)
    obs, reward, terminated, truncated, info = env.step(action)

约定（对应任务书第六节）：
  · 控制频率与物理步长分开：默认 50 Hz 控制 / 0.002 s 物理步。
  · reset 真正重置 qpos/qvel/ctrl/时间/动作历史/奖励累计。
  · terminated 与 truncated 分开：倾覆/到达/出界是 terminated，超时是 truncated，
    每者都有明确 reason。
  · 动作是**残差**：不直接给 16 个电机力矩，而是给"前腿目标偏移 / 后腿目标偏移 /
    轮速调节"三个量，叠加在已验证的站姿 PD 与轮速伺服上。
    学习的是高层残差，不是从零学全身控制。
"""
import json
import pathlib
import sys

import numpy as np
import trimesh
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_scene
import runio
import terrain
from drive_test import ids, LEG, STANCE, STANCE_HIGH

WHEEL_R = 0.086
FRONT = {'FR', 'FL'}
REAR = {'RR', 'RL'}
KP, KD = 150.0, 5.0
WHEEL_KP, WHEEL_MAX, LEG_MAX = 1.2, 15.0, 45.0

# 观测 = 本体感觉 + 导航状态。
# 导航状态只提供**通道相对量**（横向偏差、朝向误差），不是地形图、不是相机、
# 也不是真实的定位系统——它是仿真真值，必须如实标注。
OBS_DIM = 41   # 39 本体感觉 + 2 导航状态（横向偏差、朝向误差）
# 学习器动作 3 维：前腿目标偏移、后腿目标偏移、轮速倍率。
# 第 4 维（差速转向）**由共享导航底座产生**，不再交给学习器。
# 这样"零越障残差"基线 = 导航底座 + 不学习，与学习策略共用同一底座、
# 同一信息、同一约束；学习增益才归因于越障决策本身。
ACT_DIM = 3
ACT_SCALE = np.array([0.30, 0.30, 0.60])
CTRL_DIM = 4                    # 内部实际下发的控制维度（含转向）
NAV_K_LAT = 1.0                 # 导航底座：横向偏差增益（符号由开环标定确定）
NAV_K_HEAD = 0.5                # 导航底座：朝向误差增益


class WheelLegEnv:
    def __init__(self, spec, control_hz=50.0, max_seconds=12.0,
                 v_ref=1.0, tip_deg=60.0, asset_root=None,
                 settle_seconds=1.0, pass_clearance=0.10, bounds_y=0.45,
                 nav_base=True):
        self.spec = spec
        self.control_hz = float(control_hz)
        self.max_seconds = float(max_seconds)
        self.v_ref = float(v_ref)
        self.tip_deg = float(tip_deg)
        self.asset_root = pathlib.Path(asset_root or
                                       pathlib.Path(__file__).resolve().parent.parent
                                       / 'assets/processed')
        # 任务成功判据：整机（四轮）越过障碍远端 + 净空，并稳定保持 settle_seconds
        self.settle_seconds = float(settle_seconds)
        self.pass_clearance = float(pass_clearance)
        self.bounds_y = float(bounds_y)
        ch = spec.get('channel') or {}
        self.channel_center = float(ch.get('center_y', 0.0))
        self.channel_half_width = float(ch.get('half_width', 0.45))
        self.require_contact = bool((spec.get('skill_cfg') or {}).get('require_contact', False))
        self.nav_base = bool(nav_base)
        # 导航横向目标：默认等于通道中心，绕行动作通过它真正改变横向轨迹
        self.nav_target_y = float((self.spec.get('channel') or {}).get('center_y', 0.0))
        cfg = spec.get('skill_cfg') or {}
        self.task = str(cfg.get('task', 'M')).upper()   # M 安全通行 / K 接触越障
        # 初态扰动幅度（米 / 弧度）。所有策略共用同一组 seed，因此是配对比较。
        ip = spec.get('init_perturbation') or {}
        self.init_perturbation = {'lateral': float(ip.get('lateral_m', 0.05)),
                                  'yaw': float(ip.get('yaw_rad', 0.05))}
        # 终态奖励：有限且可解释；不靠无限加大倾覆罚值来"修好"排序
        self.w_success = 50.0
        self.w_tip = 50.0
        self.w_oob = 30.0

        self._xml, self._hf_png = self._compose()
        self.model = mujoco.MjModel.from_xml_string(self._xml)
        self.data = mujoco.MjData(self.model)
        self.dt = float(self.model.opt.timestep)
        self.substeps = max(1, int(round((1.0 / self.control_hz) / self.dt)))
        self.J = ids(self.model)
        self.wheel_geoms = set()
        self._wheel_body_ids = {}
        for leg in LEG:
            _g = self._body_geoms(f'{leg}_wheel_link')
            self.wheel_geoms |= _g
            _bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY,
                                     f'{leg}_wheel_link')
            for _gg in _g:
                self._wheel_body_ids[_gg] = _bid

        self._wheel_bodies = self._body_ids(['%s_wheel_link' % leg for leg in LEG])
        self.obstacle_geoms = set()
        for i in range(len(self.spec.get('objects', []))):
            self.obstacle_geoms |= self._body_geoms(f'obstacle{i}')
        self.t = 0.0
        self.prev_action = np.zeros(ACT_DIM)
        self.nav_target_y = float(self.channel_center)
        self.prev_x = 0.0
        self.passed_at = None
        self.n_control = 0
        self.n_physics = 0
        # 土壤模式：rigid（默认）/ soil（Bekker 简化软接触）
        sc = (spec.get('soil') or {})
        self.soil_mode = str(sc.get('mode', 'rigid'))
        self.soil_params = None
        self.soil_calib = None
        if self.soil_mode != 'rigid':
            import soil as SOIL
            p_ = sc.get('params') or {}
            self.soil_params = SOIL.SoilParams(**p_) if p_ else SOIL.SoilParams.moon_nominal()
            self.soil_calib = float(sc.get('stiffness_factor', 0.00151))
            self._soil_stats = {'steps': 0, 'max_sink_m': 0.0, 'resistance_n': 0.0,
                                'traction_n': 0.0, 'load_n': 0.0, 'n_wheels': 0,
                                'wheel_contact_steps': 0, 'sum_Rc': 0.0, 'sum_Ft': 0.0,
                                'sum_work_j': 0.0, 'sum_load': 0.0}
        self._soil_force = np.zeros(6)
        self.episode_return = 0.0
        self._reset_state(seed=spec.get('seed', 0))

    # ---------------------------------------------------------------- 场景
    def _compose(self):
        h, meta = terrain.build_heightfield(self.spec)
        self._h = h
        self._zmax = meta['zmax']
        self._terrain_meta = meta
        hf_dir = pathlib.Path(self.spec.get('_hfield_dir') or
                              (pathlib.Path(__file__).resolve().parent.parent / 'runs/_hfield'))
        hf_dir.mkdir(parents=True, exist_ok=True)
        png = hf_dir / f"{terrain.scene_identity(self.spec)}.png"
        terrain.write_heightfield_png(h, png, zmax=meta['zmax'])   # 每次重写，避免陈旧地形

        # 有地形 heightfield 时不要再叠一块平面地面（会填平坑洼、遮挡射线测量）
        xml = build_scene.moon_scene_xml(floor=False)
        cam = self.spec.get('front_cam')
        if cam:
            # 机头前上方相机，用 xyaxes 显式定义朝向（之前只用绕 y 轴转向，
            # 图像 up 落在世界 +y 上，导致地平线竖立 90°）：
            #   x 轴（图像右）= 世界 -y ，y 轴（图像上）= (sin p, 0, cos p)
            #   => 视线 -z = (cos p, 0, -sin p)，p 为俯角
            pitch = float(cam.get('pitch_deg', -12.0))      # 负值 = 向下俯
            p_ = np.deg2rad(abs(pitch))
            xyaxes = f"0 -1 0  {np.sin(p_):.6f} 0 {np.cos(p_):.6f}"
            pos = cam.get('pos', [0.30, 0.0, 0.06])
            tag = (f'<camera name="front_cam" pos="{pos[0]} {pos[1]} {pos[2]}" '
                   f'xyaxes="{xyaxes}" fovy="{cam.get("fovy", 70.0)}"/>')
            i = xml.find('<body name="base_link"')
            if i >= 0:
                j = xml.find('>', i) + 1
                xml = xml[:j] + tag + xml[j:]
        vis = self.spec.get('visual') or {}
        if vis:
            lx = float(vis.get('light', {}).get('pos', [-1.2, -0.7, 1.5])[0])
            ly = float(vis.get('light', {}).get('pos', [-1.2, -0.7, 1.5])[1])
            lz = float(vis.get('light', {}).get('pos', [-1.2, -0.7, 1.5])[2])
            d_x, d_y, d_z = vis.get('light', {}).get('dir', [0.6, 0.35, -0.72])
            amb = vis.get('headlight', {}).get('ambient', '0.4 0.4 0.4')
            dif = vis.get('headlight', {}).get('diffuse', '0.55 0.55 0.55')
            import re as _re
            if '<headlight' in xml:
                xml = _re.sub(r'<headlight[^/]*/>',
                              f'<headlight ambient="{amb}" diffuse="{dif}"/>', xml)
            else:
                xml = xml.replace('<visual>',
                    f'<visual><headlight ambient="{amb}" diffuse="{dif}"/>')
            xml = xml.replace('<worldbody>',
                f'<worldbody><light pos="{lx} {ly} {lz}" dir="{d_x} {d_y} {d_z}" '
                f'diffuse="0.85 0.8 0.7" castshadow="false"/>')
        mat = self.spec.get('object_material')
        if mat:
            # 纹理只改视觉，不改碰撞；贴图按盒投影（MuJoCo 2d 纹理默认行为）
            tex_xml = (f'<texture name="{mat["name"]}_tex" type="2d" '
                       f'file="{mat["texture"]}"/>'
                       f'<material name="{mat["name"]}" texture="{mat["name"]}_tex" '
                       f'specular="0.05" shininess="0.1"/>')
            xml = xml.replace('<asset>', '<asset>' + tex_xml)
        xml = xml.replace('<asset>', '<asset>' + terrain.heightfield_xml(self.spec, png, meta['zmax']))

        assets, bodies, placements, bounds = [], [], [], []
        for i, obj in enumerate(self.spec.get('objects', [])):
            if obj.get('posed_dir'):
                d = pathlib.Path(obj['posed_dir'])
            elif obj.get('mesh_file'):
                d = pathlib.Path(obj['mesh_file'])
            else:
                d = self.asset_root / obj['asset']
            if obj.get('posed_dir'):
                import json as _json
                _man = _json.loads((pathlib.Path(obj['posed_dir']) / 'manifest.json').read_text())
                if _man.get('coordinate_frame') == 'world':
                    # 世界坐标资产：只允许 identity 放置，拒绝再平移/缩放/贴地
                    if any(abs(float(obj.get(k, 0) or 0)) > 1e-9 for k in ('x', 'y')):
                        raise ValueError(
                            f"world-frame 资产禁止再平移：x={obj.get('x')} y={obj.get('y')}")
                    if obj.get('scale') not in (None, 1, 1.0):
                        raise ValueError('world-frame 资产禁止再缩放')
                    if abs(float(obj.get('yaw_deg', 0) or 0)) > 1e-9:
                        raise ValueError(
                            f"world-frame 资产禁止再旋转：yaw_deg={obj.get('yaw_deg')}")
                    if obj.get('target_height_m') is not None:
                        raise ValueError('world-frame 资产禁止 target_height_m 改写')
                    if obj.get('quat') is not None:
                        raise ValueError('world-frame 资产禁止外部 quat')
                    obj = dict(obj); obj['_world_frame'] = True
                res = [str((pathlib.Path(obj['posed_dir']) / p_).resolve())
                       for p_ in _man['parts']]
                obj = dict(obj); obj['_posed'] = True
            elif obj.get('mesh_file'):
                res = [str(pathlib.Path(obj['mesh_file']).resolve())]
            else:
                res = _resolve_parts(d)
                if not res:
                    raise FileNotFoundError(f'物体资产不可用：{d}')
            yaw = np.deg2rad(float(obj.get('yaw_deg', 0.0)))
            quat = f'{np.cos(yaw/2):.6f} 0 0 {np.sin(yaw/2):.6f}'

            # 统一按目标高度缩放：P/G 两组因此共享同一尺度分布，尺度不再是混淆变量。
            # 缩放后的家族仍算同源变体，不宣称是新的独立形状。
            # 各向异性归一化：高度控制难度、横向宽度保证封住通道。
            # 等比缩放会让高瘦资产（如货箱）在压低后只剩几厘米宽，机器人直接绕过；
            # 各向异性会改变长宽比，因此这是"同源变体"，不是新的独立形状。
            # **整体等比缩放**到目标高度，不做各向异性拉伸：
            # 之前为了统一横向宽度把 x/y 一起放大，T2 被拉成 1.2 m 长的板，
            # 形状被扭曲。现在只按高度等比缩放，横向宽度保持自然比例；
            # 通道宽度由场景按障碍实际横向尺寸决定，保证仍然封路。
            target_h = (None if obj.get('posed_dir')
                        else obj.get('target_height_m'))
            man = ({} if (obj.get('mesh_file') or obj.get('posed_dir'))
                   else runio.resolve_asset(d)['manifest'] or {})
            h0 = float(man.get('height_m') or 0)
            s_ = 1.0
            if target_h and h0 > 0:
                s_ = float(target_h) / h0
            scale = (s_, s_, s_)
            scale_attr = ('' if all(abs(float(c) - 1.0) < 1e-9 for c in scale)
                          else f' scale="{s_:.6f} {s_:.6f} {s_:.6f}"')

            # 用**旋转并缩放后的真实顶点**求落地高度：最低点贴到其正下方地面，
            # 任何顶点都不低于地形（不埋），且至少一个顶点接触（不悬空）。
            if obj.get('_world_frame'):
                # 世界坐标资产：顶点即世界坐标，不做任何变换，直接读原始顶点
                verts = np.vstack([trimesh.load(r, force='mesh',
                                                process=False).vertices.copy()
                                   for r in res])
            else:
                verts = _world_vertices(res, float(obj.get('x', 0.0)),
                                        float(obj.get('y', 0.0)), yaw, scale=scale)
            if obj.get('_world_frame'):
                # 世界坐标资产：顶点已是世界坐标，body 必须 identity，**不再**贴地
                body_z = 0.0
                place_meta = {'body_z': 0.0, 'world_frame': True,
                              'min_clearance_m': round(
                                  float(verts[:, 2].min()), 9),
                              'note': 'coordinate_frame=world；下游未做任何平移/缩放/贴地'}
            elif obj.get('_posed'):
                # 已配准资产：姿态固定，机身 z 直接取网格最低点贴地，
                # 且**不**再叠加 place_on_terrain 的抬升（否则等于偷偷移位）。
                body_z = -float(verts[:, 2].min())
                place_meta = {'body_z': round(body_z, 5), 'posed': True,
                              'min_clearance_m': 0.0,
                              'ground_under_min_object_m': round(
                                  float(terrain.ground_height_many(
                                      h, verts[:, 0], verts[:, 1]).min()), 4)}
            else:
                body_z, place_meta = terrain.place_on_terrain(h, verts)
            _name = (obj.get('asset')
                     or pathlib.Path(obj.get('posed_dir') or obj.get('mesh_file') or 'asset').name)
            place_meta.update({'asset': _name,
                               'x': float(obj.get('x', 0.0)), 'y': float(obj.get('y', 0.0)),
                               'yaw_deg': obj.get('yaw_deg', 0.0),
                               'n_vertices': int(len(verts)),
                               'target_height_m': target_h,
                               'mesh_scale': [round(float(c), 5) for c in scale]})
            placements.append(place_meta)
            bounds.append({'asset': _name,
                           'x_min': float(verts[:, 0].min()),
                           'x_max': float(verts[:, 0].max()),
                           'y_min': float(verts[:, 1].min()),
                           'y_max': float(verts[:, 1].max()),
                           'z_min': float(verts[:, 2].min()) + body_z,
                           'z_max': float(verts[:, 2].max()) + body_z})

            inner = []
            for j, p_ in enumerate(res):
                name = f'obj{i}_{j}'
                assets.append(f'<mesh name="{name}" file="{p_}"{scale_attr}/>')
                mat = self.spec.get('object_material')
                mat_attr = f' material="{mat["name"]}"' if mat else ''
                rgba = ('.72 .56 .36 1' if not mat else '1 1 1 1')
                inner.append(
                    f'<geom type="mesh" mesh="{name}" rgba="{rgba}"{mat_attr} '
                    f'friction="0.9 0.02 0.001" contype="1" conaffinity="1"/>')
            bodies.append(
                f'<body name="obstacle{i}" pos="{float(obj.get("x", 0.0)):.4f} '
                f'{float(obj.get("y", 0.0)):.4f} {body_z:.5f}" '
                f'quat="{quat}">{"".join(inner)}</body>')

        self.placements = placements
        self.obj_bounds = bounds
        block = terrain.terrain_geom_xml() + '\n' + '\n'.join(bodies)
        xml = xml.replace('</worldbody>', block + '\n  </worldbody>')
        xml = xml.replace('<asset>', '<asset>' + ''.join(assets))
        self._obstacle_bodies = [f'obstacle{i}' for i in range(len(self.spec.get('objects', [])))]
        return xml, str(png)

    def _body_geoms(self, body_name):
        bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, body_name)
        if bid < 0:
            return set()
        return {g for g in range(self.model.ngeom) if self.model.geom_bodyid[g] == bid}

    def _body_ids(self, names):
        out = []
        for n in names:
            bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, n)
            out.append(bid if bid >= 0 else None)
        return out

    def _wheel_xs(self):
        xs = [float(self.data.xpos[b][0]) for b in self._wheel_bodies if b is not None]
        return xs or [float(self.data.qpos[0])]

    def _obstacle_half_depth(self, obj):
        """障碍沿 x 的半深，取自资产 manifest 的真实尺寸（缺省 0.15）。"""
        import runio as _ri
        try:
            man = _ri.resolve_asset(self.asset_root / obj['asset'])['manifest'] or {}
            return float(man.get('width_x_m') or 0.30) / 2.0
        except Exception:
            return 0.15

    def _ledger_key(self, reason, terminated):
        if reason in ('success', 'tipped', 'out_of_bounds'):
            return 'terminal_' + reason
        return 'truncated_time_limit'

    # ---------------------------------------------------------------- 状态
    def _reset_state(self, seed=0):
        m, d = self.model, self.data
        mujoco.mj_resetData(m, d)
        d.qpos[:] = m.qpos0
        st = STANCE
        for leg in LEG:
            d.qpos[self.J[f'{leg}_thigh_joint']['qadr']] = st['thigh']
            d.qpos[self.J[f'{leg}_calf_joint']['qadr']] = st['calf']
        # 初态扰动：真的按 seed 改变横向位置、朝向与起始速度。
        # 旧实现完全忽略 seed，确定性评估的多个 episode_seed 是同一轨迹。
        prng = np.random.default_rng(int(seed) * 7919 + 13)
        pert = self.init_perturbation
        d.qpos[0] = float(self.spec.get('start', [0.0, 0.0])[0])
        d.qpos[1] = (float(self.spec.get('start', [0.0, 0.0])[1])
                     + float(prng.uniform(-pert['lateral'], pert['lateral'])))
        # 放到地表之上：取该处 hfield 高度再加一段
        # 出生姿态对齐局部地形法线：坡面上让机身与地面平行，
        # 否则初始倾角就是坡角，机器人一落地就滑/翻（实测 12.9° 起步直接翻车）。
        n = self._terrain_normal(d.qpos[0], d.qpos[1])
        d.qpos[3:7] = _quat_from_up(n)
        # 初始朝向误差：绕 z 旋转一个种子相关的小角度
        yaw_err = float(prng.uniform(-pert['yaw'], pert['yaw']))
        d.qpos[3:7] = _quat_mul(d.qpos[3:7], np.array([np.cos(yaw_err/2), 0, 0,
                                                       np.sin(yaw_err/2)]))
        d.qpos[2] = self._ground_height(d.qpos[0], d.qpos[1]) + 0.42
        d.qvel[:] = 0.0
        d.ctrl[:] = 0.0
        d.time = 0.0
        mujoco.mj_forward(m, d)

        self.t = 0.0
        self.n_control = 0
        self.n_physics = 0
        self.episode_return = 0.0
        self.prev_action = np.zeros(ACT_DIM)
        self.prev_x = float(d.qpos[0])
        self.passed_at = None
        self.first_contact_t = None
        self.contact_steps = 0
        self.wheel_contact_steps = 0
        # 稳定化：让姿态在固定站姿下落稳，不计入策略成绩
        for _ in range(int(0.6 / self.dt)):
            self._apply_controls(np.zeros(CTRL_DIM), drive=False)
            self._soil_step()
            mujoco.mj_step(m, d)
            self.n_physics += 1
        self.prev_x = float(d.qpos[0])
        d.time = 0.0
        self.t = 0.0

    def _wheel_geom_radius(self, gid):
        """从模型几何读取轮半径与轮宽（不写死）。"""
        size = np.asarray(self.model.geom_size[gid], dtype=float)
        # cylinder: size=[radius, half_length, -]；按实际类型取值
        rad = float(size[0])
        half_len = float(size[1]) if size.shape[0] > 1 else 0.05
        return rad, max(2.0 * half_len, 1e-3)

    def _soil_step(self):
        """
        每物理步的土壤入口（逐轮汇总，只作用于 wheel–soil）。

        实现的状态（名实相符）：
          · 法向轮载：用 mj_contactForce 取该接触的法向分量，按轮体**累加**；
          · 下陷：由该轮总轮载按 Bekker 公式**估算**（刚性接触本身不产生几何穿透）；
          · 压实阻力 Rc：沿轮子局部切平面、反向于该轮相对运动施加；
          · 牵引上限：A*c + W*tan(phi)；超过时对**驱动力方向**做截断，
            通过按比例缩放轮体水平外力实现，不与 MuJoCo 原生摩擦双算（原生摩擦仍在，
            这里的力是额外的土壤阻力，净牵引不会超过上限）。
          · 腾空轮（无接触力）不加力；轮–岩石接触跳过，不软。
        不累加：每步先清空 xfrc_applied 中由本模块写入的分量。
        """
        if self.soil_mode == 'rigid':
            return
        d, m = self.data, self.model
        # 只清本模块负责的轮体外力，不抹掉其他模块拥有的分量
        for b_id in set(self._wheel_body_ids.values()):
            d.xfrc_applied[b_id][:] = 0.0
        pm = self.soil_params
        per_wheel = {}
        for c in range(d.ncon):
            con = d.contact[c]
            g1, g2 = int(con.geom1), int(con.geom2)
            in1, in2 = g1 in self.wheel_geoms, g2 in self.wheel_geoms
            if in1 == in2:
                continue
            other = g2 if in1 else g1
            if other in self.obstacle_geoms:
                continue                        # 轮–岩石：刚性，不施土壤力
            wg = g1 if in1 else g2              # 轮侧几何
            b_id = self._wheel_body_ids.get(wg)
            if b_id is None:
                continue
            # 该接触的六维力（MjContact 没有 force 字段，必须调用 mj_contactForce）
            buf = np.zeros(6, dtype=np.float64)
            try:
                mujoco.mj_contactForce(m, d, c, buf)
            except Exception:
                continue
            f_norm = abs(float(buf[0]))         # 接触坐标系第 0 轴 = 法向
            if f_norm <= 0.0:
                continue
            rec = per_wheel.setdefault(b_id, {'fz': 0.0, 'gid': wg})
            rec['fz'] += f_norm                 # 逐轮汇总，避免同一轮多个接触重复计

        sink_max, resist, load_max, Ft_applied = 0.0, 0.0, 0.0, 0.0
        for b_id, rec in per_wheel.items():
            fz = rec['fz']
            if fz <= 0:
                continue
            R, b_w = self._wheel_geom_radius(rec['gid'])
            z_est = pm.sinkage(fz, b_w, R)
            sink_max = max(sink_max, z_est)
            load_max = max(load_max, fz)
            Rc = pm.compaction_resistance(z_est, b_w)
            resist = max(resist, Rc)
            A = b_w * float(np.sqrt(max(2.0 * R * z_est, 1e-9)))
            # 该轮局部切向速度（轮体世界速度投影到水平面）
            v = float(np.linalg.norm(d.cvel[b_id][3:5]))
            if v < 1e-6:
                continue                        # 静止不加"无中生有"的驱动力
            j = abs(v) * float(m.opt.timestep)  # 单步滑移位移（m）
            sigma = fz / max(A, 1e-9)
            tau = pm.shear_stress(j, sigma)
            Ft_cap = pm.traction_limit(fz, max(A, 1e-9))
            Ft = min(tau * A, Ft_cap)           # 牵引上限在这里真正生效
            Ft_applied = max(Ft_applied, Ft)
            vx = float(d.cvel[b_id][3])
            sgn = -1.0 if vx > 0 else 1.0
            # 净阻力 = 压实阻力，且不超过牵引上限（避免把驱动力"推"过上限）
            net = min(Rc, Ft)
            d.xfrc_applied[b_id][0] += sgn * net
        st = self._soil_stats
        st['steps'] += 1
        st['max_sink_m'] = max(st['max_sink_m'], sink_max)
        st['resistance_n'] = resist
        st['load_n'] = load_max
        st['traction_n'] = Ft_applied
        st['n_wheels'] = len(per_wheel)
        if per_wheel:
            st['wheel_contact_steps'] += 1
        st['sum_Rc'] += resist
        st['sum_Ft'] += Ft_applied
        st['sum_load'] += load_max
        # 机械功：阻力 × 位移（阻力总是反向于运动，所以功应为负或零）
        dx = float(d.qvel[0]) * float(m.opt.timestep)
        st['sum_work_j'] += float(d.xfrc_applied[min(per_wheel)].copy()[0]) * dx \
            if per_wheel else 0.0
        st['mode'] = ('rigid-contact + Bekker resistance/traction '
                      '(sinkage estimated per wheel load, not geometric)')

    def _terrain_normal(self, x, y, eps=0.08):
        """用中心差分求地表法线（世界坐标），平地返回 +z。"""
        hx1 = self._ground_height(x + eps, y); hx0 = self._ground_height(x - eps, y)
        hy1 = self._ground_height(x, y + eps); hy0 = self._ground_height(x, y - eps)
        dzdx = (hx1 - hx0) / (2 * eps)
        dzdy = (hy1 - hy0) / (2 * eps)
        n = np.array([-dzdx, -dzdy, 1.0])
        return n / np.linalg.norm(n)

    def _ground_height(self, x, y):
        """该点地表高度（米）。与地形生成共用同一份插值实现，避免两套约定。"""
        return terrain.ground_height_at(self._h, x, y)

    def _steer_from_nav(self):
        """
        共享导航底座：向 nav_target_y 收敛的比例控制。
        nav_target_y 默认等于 channel_center（保持旧行为）；绕行动作会改它。
        """
        y = float(self.data.qpos[1])
        target = float(getattr(self, 'nav_target_y', self.channel_center))
        lat_err = y - target
        head = self._nav_state()[1]
        return float(np.clip(NAV_K_LAT * lat_err + NAV_K_HEAD * head, -1.0, 1.0))

    def _full_action(self, action):
        """把学习器 3 维动作补上底座产生的转向，得到内部 4 维控制量。"""
        a = np.asarray(action, dtype=np.float64).reshape(ACT_DIM)
        steer = self._steer_from_nav() if self.nav_base else 0.0
        return np.concatenate([np.clip(a, -1, 1), [steer]])

    def _apply_controls(self, action, drive=True):
        d, m = self.data, self.model
        st = STANCE
        a = np.asarray(action, dtype=np.float64).reshape(CTRL_DIM)
        a = np.concatenate([np.clip(a[:3], -1, 1) * ACT_SCALE, [np.clip(a[3], -1, 1) * 0.6]])
        for leg in LEG:
            off = a[0] if leg in FRONT else a[1]
            for p, base in (('hip', st['hip']), ('thigh', st['thigh']), ('calf', st['calf'])):
                e = self.J[f'{leg}_{p}_joint']
                tgt = base + (off if p == 'thigh' else 0.0)
                d.ctrl[e['act']] = np.clip(
                    KP * (tgt - d.qpos[e['qadr']]) - KD * d.qvel[e['vadr']],
                    -LEG_MAX, LEG_MAX)
            e = self.J[f'{leg}_wheel_joint']
            if not drive:
                d.ctrl[e['act']] = np.clip(
                    WHEEL_KP * (0.0 - d.qvel[e['vadr']]), -WHEEL_MAX, WHEEL_MAX)
                continue
            ramp = min(1.0, max(1e-3, self.t) / 2.0)
            turn = a[3] * (1.0 if leg in ('FL', 'RL') else -1.0)
            vt = self.v_ref * ramp * (1.0 + a[2] + turn)
            d.ctrl[e['act']] = np.clip(
                WHEEL_KP * (vt / WHEEL_R - d.qvel[e['vadr']]), -WHEEL_MAX, WHEEL_MAX)

    # ---------------------------------------------------------------- 观测
    def _tilt(self):
        w, x, y, z = self.data.qpos[3:7]
        up = 1.0 - 2.0 * (x * x + y * y)
        return float(np.degrees(np.arccos(np.clip(up, -1.0, 1.0))))

    def _obs(self):
        d = self.data
        w, x, y, z = d.qpos[3:7]
        R = np.array([
            [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
            [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
            [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)]])
        g_body = R.T @ np.array([0, 0, -1.0])
        omega = R.T @ d.qvel[3:6]
        v_body = R.T @ d.qvel[0:3]
        jp, jv = [], []
        for leg in LEG:
            for p in ('hip', 'thigh', 'calf'):
                e = self.J[f'{leg}_{p}_joint']
                jp.append(d.qpos[e['qadr']])
                jv.append(d.qvel[e['vadr']])
        wv = [d.qvel[self.J[f'{leg}_wheel_joint']['vadr']] for leg in LEG]
        lat, head = self._nav_state()
        obs = np.concatenate([g_body, omega, [v_body[0]], jp, jv, wv,
                              self.prev_action, [self.v_ref],
                              [lat, head]]).astype(np.float32)
        return obs

    def soil_report(self):
        """土壤模块的累计指标（给报告用，不含单步瞬时值）。"""
        st = dict(self._soil_stats)
        n = max(st.get('wheel_contact_steps', 0), 1)
        st['mean_resistance_n'] = round(st['sum_Rc'] / n, 3)
        st['mean_traction_cap_n'] = round(st['sum_Ft'] / n, 3)
        st['mean_wheel_load_n'] = round(st['sum_load'] / n, 3)
        st['work_j'] = round(st['sum_work_j'], 6)
        st['contact_fraction'] = round(st.get('wheel_contact_steps', 0) /
                                       max(st.get('steps', 1), 1), 4)
        return st

    def robot_state(self):
        """给动作库用的受限接口：本体状态 + 可见量 + 导航目标，不含真值背面。"""
        d = self.data
        w, x, y, z = d.qpos[3:7]
        fwd = np.array([1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 0.0])
        return {'x': float(d.qpos[0]), 'y': float(d.qpos[1]),
                'z': float(d.qpos[2]), 'vx': float(d.qvel[0]),
                'tilt': self._tilt(), 'lateral': float(d.qpos[1]) - self.channel_center,
                'heading': float(np.arctan2(fwd[1], fwd[0])),
                'dt': float(self.substeps * self.dt), 't': float(self.t),
                'finished': False, 'time_limit': float(self.max_seconds),
                'x_front': self.plan_visible.get('x_front') if hasattr(self, 'plan_visible') else None,
                'W_vis': self.plan_visible.get('W_vis') if hasattr(self, 'plan_visible') else None}

    def brake_step(self):
        """显式刹车一步（轮速目标 0）：实测 a[2]=-1 不停车，A0 必须走这条。"""
        for _ in range(self.substeps):
            self._soil_step() if hasattr(self, '_soil_step') else None
            for leg in LEG:
                e = self.J[f'{leg}_wheel_joint']
                self.data.ctrl[e['act']] = float(np.clip(
                    -6.0 * self.data.qvel[e['vadr']],
                    -WHEEL_MAX, WHEEL_MAX))
            for leg in LEG:
                for p_ in ('hip', 'thigh', 'calf'):
                    e = self.J[f'{leg}_{p_}_joint']
                    tgt = STANCE[p_ if p_ != 'hip' else 'hip']
                    self.data.ctrl[e['act']] = float(np.clip(
                        KP * (tgt - self.data.qpos[e['qadr']])
                        - KD * self.data.qvel[e['vadr']], -LEG_MAX, LEG_MAX))
            mujoco.mj_step(self.model, self.data)
            self.n_physics += 1
        self.t += self.substeps * self.dt
        self.n_control += 1

    def _nav_state(self):
        """通道相对导航量：横向偏差（米，左正）与朝向误差（弧度）。"""
        d = self.data
        y = float(d.qpos[1])
        w, x, yy, z = d.qpos[3:7]
        # 机体系 +x 在世界系的方向（前进方向）
        fwd = np.array([1 - 2 * (yy * yy + z * z), 2 * (x * yy + z * w), 0.0])
        heading = float(np.arctan2(fwd[1], fwd[0]))
        return y - self.channel_center, heading

    # ---------------------------------------------------------------- 接口
    def reset(self, seed=None):
        self._reset_state(seed=self.spec.get('seed', 0) if seed is None else seed)
        return self._obs(), {'scene': self.spec.get('name'), 't': 0.0}

    def step(self, action):
        action = np.asarray(action, dtype=np.float64).reshape(ACT_DIM)
        action = np.clip(action, -1.0, 1.0)
        full = self._full_action(action)          # 补上导航底座的转向
        reward = 0.0
        r_lat = 0.0
        for _ in range(self.substeps):
            self._apply_controls(full)
            self._soil_step()
            mujoco.mj_step(self.model, self.data)
            self.n_physics += 1
            # 接触必须逐物理步检测：只在控制步末采样会漏掉滚过矮障碍的短暂接触
            if self.obstacle_geoms:
                hit = wheel = False
                dd = self.data
                for c in dd.contact[:dd.ncon]:
                    g1, g2 = c.geom1, c.geom2
                    if (g1 in self.obstacle_geoms) != (g2 in self.obstacle_geoms):
                        other = g2 if g1 in self.obstacle_geoms else g1
                        if other not in self.obstacle_geoms:
                            hit = True
                            if other in self.wheel_geoms:
                                wheel = True
                if hit:
                    self.contact_steps += 1
                    if self.first_contact_t is None:
                        self.first_contact_t = self.t
                if wheel:
                    self.wheel_contact_steps += 1
        self.n_control += 1
        self.t += self.substeps * self.dt

        d = self.data
        x, y = float(d.qpos[0]), float(d.qpos[1])
        vx = float(d.qvel[0])
        lat = y - self.channel_center
        tilt = self._tilt()
        progress = x - self.prev_x
        self.prev_x = x

        # 奖励分解（全部保存，不只存总分）
        # 量级必须让"成功"优于"翻车"。旧版每步速度惩罚累计约 -50，
        # 而倾覆只罚 -20 —— 策略会认定"翻车比减速便宜"。实测 40k 步学不到东西。
        r_prog = 20.0 * progress
        r_speed = -0.1 * abs(vx - self.v_ref)
        r_tilt = -0.5 * max(0.0, tilt - 20.0) / 40.0
        r_smooth = -0.05 * float(np.sum((action - self.prev_action) ** 2))
        # 密集通道惩罚：失败的种子全部是"早早横向出界、永远拿不到成功信号"，
        # 稀疏的终态奖励无法给出梯度。这里给横向偏差一个逐步惩罚，
        # 让"留在通道内"成为一个可学的密集信号（假设，见报告）。
        r_lat = -0.3 * abs(lat)
        reward = r_prog + r_speed + r_tilt + r_smooth + r_lat
        ledger = {}
        self.prev_action = action.copy()

        reason = None
        terminated = False
        truncated = False

        # ---- 任务 M / K 分开定义（训练前冻结，不按成绩修改） ----
        #   M 安全通行：四轮越过终点线 + 通道内稳定保持；允许绕行/跨骑/接触
        #   K 接触越障：四轮越过障碍**变换后**远端 + 净空 + 稳定保持，且必须接触
        min_wheel_x = min(self._wheel_xs())
        task = self.task
        if task == 'K' and self.obj_bounds:
            finish_x = max(b['x_max'] for b in self.obj_bounds) + self.pass_clearance
        else:
            finish_x = float(self.spec.get('goal_x', 3.0))

        lat = y - self.channel_center
        in_channel = abs(lat) <= self.channel_half_width

        # 连续稳定保持：进入完成区开始计时；退回、倾覆或出通道都清零
        if min_wheel_x >= finish_x and in_channel:
            if self.passed_at is None:
                self.passed_at = self.t
        else:
            if self.passed_at is not None and min_wheel_x < finish_x - 0.02:
                self.passed_at = None
            if not in_channel:
                self.passed_at = None

        if (self.passed_at is not None
                and (self.t - self.passed_at) >= self.settle_seconds):
            if task == 'K' and self.require_contact and self.first_contact_t is None:
                terminated, reason = True, 'bypass'      # K 任务：无接触不算接触越障
                reward -= self.w_oob * 0.5
            else:
                terminated, reason = True, 'success'
                reward += self.w_success

        if not terminated and tilt > self.tip_deg:
            terminated, reason = True, 'tipped'
            reward -= self.w_tip
        if not terminated and not in_channel:
            terminated, reason = True, 'out_of_bounds'
            reward -= self.w_oob
        # 兜底：K 任务里跑过整个场景仍未满足完成条件 -> 记为未通过，不再伪装成出界
        if (not terminated and self.passed_at is None
                and x >= float(self.spec.get('goal_x', 6.0)) + 1.0):
            terminated, reason = True, 'failed_to_pass'
            reward -= self.w_oob * 0.5
        if not terminated and self.t >= self.max_seconds:
            truncated, reason = True, 'time_limit'

        self.episode_return += reward
        ledger[self._ledger_key(reason, terminated)] = round(reward, 4)
        info = {
            'reason': reason, 'terminated': terminated, 'truncated': truncated,
            'tilt_deg': round(tilt, 2), 'x': round(x, 3), 'y': round(y, 3),
            'vx': round(vx, 3), 't': round(self.t, 3),
            'min_wheel_x': round(min_wheel_x, 3), 'pass_x': round(finish_x, 3),
            'passed_at': (round(self.passed_at, 3) if self.passed_at is not None else None),
            'first_contact_s': (round(self.first_contact_t, 3)
                                if self.first_contact_t is not None else None),
            'contact_any': self.first_contact_t is not None,
            'contact_wheel': self.wheel_contact_steps > 0,
            'contact_substeps': self.contact_steps,
            'lateral_offset': round(lat, 3), 'task': task,
            'channel_half_width': self.channel_half_width,
            'contact_style': ('none' if self.first_contact_t is None
                              else ('wheel' if self.wheel_contact_steps > 0
                                    else 'body')),
            'rewards': {'progress': round(r_prog, 4), 'speed': round(r_speed, 4),
                        'tilt': round(r_tilt, 4), 'smooth': round(r_smooth, 4),
                        'lateral': round(r_lat, 4),
                        'terminal': round(reward - (r_prog + r_speed + r_tilt + r_smooth), 4)},
            'episode_return_ledger': dict(ledger),
            'n_control': self.n_control, 'n_physics': self.n_physics,
            'scene': self.spec.get('name')}
        return self._obs(), float(reward), terminated, truncated, info


def _resolve_parts(asset_dir):
    """复用 runio 的解析规则，保证训练与考场用同一套路径约定。"""
    import runio
    r = runio.resolve_asset(asset_dir)
    return [str(p) for p in r['part_paths']] if r['ok'] else None


def _world_vertices(part_paths, x, y, yaw, scale=1.0):
    """scale 可为标量或 (sx, sy, sz)。"""
    """读取碰撞网格顶点，绕 z 旋转并平移到世界坐标（只取顶点，不建场景）。"""
    import trimesh
    allv = []
    for p_ in part_paths:
        m = trimesh.load(p_, force='mesh')
        v = np.asarray(m.vertices, dtype=np.float64)
        if len(v):
            allv.append(v)
    if not allv:
        return np.zeros((1, 3))
    v = np.vstack(allv)
    sv = np.asarray(scale, dtype=np.float64).reshape(-1)
    v = v * (sv if sv.size == 3 else float(sv[0]))
    c, s_ = np.cos(yaw), np.sin(yaw)
    R = np.array([[c, -s_, 0.0], [s_, c, 0.0], [0.0, 0.0, 1.0]])
    v = v @ R.T
    v[:, 0] += x
    v[:, 1] += y
    return v


def _quat_from_up(up):
    """返回把机体 +z 对齐到 up 的四元数 (w, x, y, z)。"""
    up = np.asarray(up, dtype=np.float64)
    up = up / (np.linalg.norm(up) + 1e-12)
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(z, up)
    c = float(np.dot(z, up))
    if np.linalg.norm(v) < 1e-9:
        return np.array([1.0, 0.0, 0.0, 0.0]) if c > 0 else np.array([0.0, 1.0, 0.0, 0.0])
    s_ = float(np.linalg.norm(v))
    axis = v / s_
    ang = float(np.arctan2(s_, c))
    q = np.concatenate([[np.cos(ang / 2)], axis * np.sin(ang / 2)])
    return q


def _quat_mul(a, b):
    """四元数乘法 (w,x,y,z)。"""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw*bw - ax*bx - ay*by - az*bz,
        aw*bx + ax*bw + ay*bz - az*by,
        aw*by - ax*bz + ay*bw + az*bx,
        aw*bz + ax*by - ay*bx + az*bw])
