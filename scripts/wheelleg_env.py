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
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_scene
import terrain
from drive_test import ids, LEG, STANCE, STANCE_HIGH

WHEEL_R = 0.086
FRONT = {'FR', 'FL'}
REAR = {'RR', 'RL'}
KP, KD = 150.0, 5.0
WHEEL_KP, WHEEL_MAX, LEG_MAX = 1.2, 15.0, 45.0

OBS_DIM = 39
ACT_DIM = 3
ACT_SCALE = np.array([0.30, 0.30, 0.60])     # 前腿偏移, 后腿偏移, 轮速倍率


class WheelLegEnv:
    def __init__(self, spec, control_hz=50.0, max_seconds=12.0,
                 v_ref=1.0, tip_deg=60.0, asset_root=None,
                 settle_seconds=1.0, pass_clearance=0.10, bounds_y=0.45):
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
        self.obs_geom = self._geom_ids('obstacle')
        self.wheel_geoms = set()
        for leg in LEG:
            self.wheel_geoms |= self._geom_ids(f'{leg}_wheel_link')

        self._wheel_bodies = self._body_ids(['%s_wheel_link' % leg for leg in LEG])
        self.t = 0.0
        self.prev_action = np.zeros(ACT_DIM)
        self.prev_x = 0.0
        self.passed_at = None
        self.n_control = 0
        self.n_physics = 0
        self.episode_return = 0.0
        self._reset_state(seed=spec.get('seed', 0))

    # ---------------------------------------------------------------- 场景
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

    def _geom_ids(self, body):
        bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, body) \
            if hasattr(self, 'model') else -1
        return set()

    def _compose(self):
        h, _ = terrain.build_heightfield(self.spec)
        self._h = h
        hf_dir = pathlib.Path(self.spec.get('_hfield_dir') or
                              (pathlib.Path(__file__).resolve().parent.parent / 'runs/_hfield'))
        hf_dir.mkdir(parents=True, exist_ok=True)
        png = hf_dir / f"{terrain.scene_identity(self.spec)}.png"
        if not png.exists():
            terrain.write_heightfield_png(h, png)

        xml = build_scene.moon_scene_xml()
        xml = xml.replace('<asset>', '<asset>' + terrain.heightfield_xml(self.spec, png))

        assets, bodies = [], []
        for i, obj in enumerate(self.spec.get('objects', [])):
            d = self.asset_root / obj['asset']
            res = _resolve_parts(d)
            if not res:
                raise FileNotFoundError(f'物体资产不可用：{d}')
            yaw = np.deg2rad(float(obj.get('yaw_deg', 0.0)))
            quat = f'{np.cos(yaw/2):.6f} 0 0 {np.sin(yaw/2):.6f}'
            inner = []
            for j, p_ in enumerate(res):
                name = f'obj{i}_{j}'
                assets.append(f'<mesh name="{name}" file="{p_}"/>')
                inner.append(
                    f'<geom type="mesh" mesh="{name}" rgba=".72 .56 .36 1" '
                    f'friction="0.9 0.02 0.001" contype="1" conaffinity="1"/>')
            bodies.append(
                f'<body name="obstacle{i}" pos="{obj["x"]:.4f} {obj["y"]:.4f} 0" '
                f'quat="{quat}">{"".join(inner)}</body>')

        block = terrain.terrain_geom_xml() + '\n' + '\n'.join(bodies)
        xml = xml.replace('</worldbody>', block + '\n  </worldbody>')
        xml = xml.replace('<asset>', '<asset>' + ''.join(assets))
        self._obstacle_bodies = [f'obstacle{i}' for i in range(len(self.spec.get('objects', [])))]
        return xml, str(png)

    # ---------------------------------------------------------------- 状态
    def _reset_state(self, seed=0):
        m, d = self.model, self.data
        mujoco.mj_resetData(m, d)
        d.qpos[:] = m.qpos0
        st = STANCE
        for leg in LEG:
            d.qpos[self.J[f'{leg}_thigh_joint']['qadr']] = st['thigh']
            d.qpos[self.J[f'{leg}_calf_joint']['qadr']] = st['calf']
        d.qpos[0] = float(self.spec.get('start', [0.0, 0.0])[0])
        d.qpos[1] = float(self.spec.get('start', [0.0, 0.0])[1])
        # 放到地表之上：取该处 hfield 高度再加一段
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
        # 稳定化：让姿态在固定站姿下落稳，不计入策略成绩
        for _ in range(int(0.6 / self.dt)):
            self._apply_controls(np.zeros(ACT_DIM), drive=False)
            mujoco.mj_step(m, d)
            self.n_physics += 1
        self.prev_x = float(d.qpos[0])
        d.time = 0.0
        self.t = 0.0

    def _ground_height(self, x, y):
        """按 hfield 网格插值出该点的地表高度（hfield 覆盖 [-SPAN,SPAN]）。"""
        from terrain import SPAN, N, ZMAX
        u = (x + SPAN) / (2 * SPAN)     # 对应列
        v = (y + SPAN) / (2 * SPAN)     # 对应行
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            return 0.0
        i = int(round(u * (N - 1)))
        j = int(round(v * (N - 1)))
        peak = float(self._h.max()) or 1.0
        return float(self._h[j, i]) / peak * ZMAX

    def _apply_controls(self, action, drive=True):
        d, m = self.data, self.model
        st = STANCE
        a = np.clip(action, -1.0, 1.0) * ACT_SCALE
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
            vt = self.v_ref * ramp * (1.0 + a[2])
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
        obs = np.concatenate([g_body, omega, [v_body[0]], jp, jv, wv,
                              self.prev_action, [self.v_ref]]).astype(np.float32)
        return obs

    # ---------------------------------------------------------------- 接口
    def reset(self, seed=None):
        self._reset_state(seed=self.spec.get('seed', 0) if seed is None else seed)
        return self._obs(), {'scene': self.spec.get('name'), 't': 0.0}

    def step(self, action):
        action = np.asarray(action, dtype=np.float64).reshape(ACT_DIM)
        action = np.clip(action, -1.0, 1.0)
        reward = 0.0
        for _ in range(self.substeps):
            self._apply_controls(action)
            mujoco.mj_step(self.model, self.data)
            self.n_physics += 1
        self.n_control += 1
        self.t += self.substeps * self.dt

        d = self.data
        x, y = float(d.qpos[0]), float(d.qpos[1])
        vx = float(d.qvel[0])
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
        reward = r_prog + r_speed + r_tilt + r_smooth
        ledger = {}
        self.prev_action = action.copy()

        reason = None
        terminated = False
        truncated = False

        # ---- 通过判据：四个轮子全部越过障碍远端 + 净空 ----
        objs = self.spec.get('objects', [])
        min_wheel_x = min(self._wheel_xs())
        if objs:
            target_x = max(float(o['x']) + float(self._obstacle_half_depth(o))
                           + self.pass_clearance for o in objs)
        else:
            target_x = float(self.spec.get('goal_x', 3.0))

        if self.passed_at is None and min_wheel_x >= target_x:
            self.passed_at = self.t
        if self.passed_at is not None and (self.t - self.passed_at) >= self.settle_seconds:
            terminated, reason = True, 'success'
            reward += self.w_success

        if not terminated and tilt > self.tip_deg:
            terminated, reason = True, 'tipped'
            reward -= self.w_tip
        if not terminated and abs(y) > self.bounds_y:
            terminated, reason = True, 'out_of_bounds'
            reward -= self.w_oob
        if not terminated and x >= float(self.spec.get('goal_x', 6.0)):
            # 兜底：跑过整个场景仍未满足通过判据也没翻 -> 记 out_of_bounds 式失败
            terminated, reason = True, 'out_of_bounds'
            reward -= self.w_oob
        if not terminated and self.t >= self.max_seconds:
            truncated, reason = True, 'time_limit'

        self.episode_return += reward
        ledger[self._ledger_key(reason, terminated)] = round(reward, 4)
        info = {
            'reason': reason, 'terminated': terminated, 'truncated': truncated,
            'tilt_deg': round(tilt, 2), 'x': round(x, 3), 'y': round(y, 3),
            'vx': round(vx, 3), 't': round(self.t, 3),
            'min_wheel_x': round(min_wheel_x, 3), 'pass_x': round(target_x, 3),
            'passed_at': (round(self.passed_at, 3) if self.passed_at is not None else None),
            'rewards': {'progress': round(r_prog, 4), 'speed': round(r_speed, 4),
                        'tilt': round(r_tilt, 4), 'smooth': round(r_smooth, 4),
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
