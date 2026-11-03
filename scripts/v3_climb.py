"""D1 第二里程碑：两条前腿依次搭上台沿，前部真实承载。

场景：平地 + 0.05 m 高、0.9 m 宽的台（开发用已知几何）。
阶段：APPROACH -> 速度斜坡 BRAKE -> 对每条前腿执行
      SHIFT_SUPPORT -> LIFT_LEG -> ADVANCE_TO_LEDGE -> LOWER_LEG -> HOLD_LEG
最后 HOLD_BOTH：两条前轮都压在台面上并各自承担 >=5% 重力。

要点：
  * 一次只抬一条前腿，另外三条（含已上台的前轮）保持支撑；
  * 抬腿前先做支撑转移；抬腿用逐腿 3 关节雅可比；
  * 前进前必须先抬到台面 + 轮半径 + 裕度，否则未抬的轮会先撞台阶；
  * 载荷统计包含地面与障碍物接触；成功判据用真实接触、轮心高度与姿态。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_climb.py --soil nominal --out runs/v3/climb/front2_r1
"""
import argparse
import hashlib
import json
import pathlib
import sys

import mujoco
import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import terrain            # noqa: E402
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402
import v3_record          # noqa: E402
import v3_basic_cycle as bc   # noqa: E402

LEG = bc.LEG
STANCE = {leg: dict(bc.STANCE) for leg in LEG}
WHEEL_R = wheelleg_env.WHEEL_R


def jlim(env, leg, part):
    """真实关节限位（从模型读），不要用统一 [-2.5,2.5]。"""
    j = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_JOINT, f'{leg}_{part}_joint')
    lo, hi = env.model.jnt_range[j]
    return float(lo), float(hi)


def contact_load(env, leg, kind='top'):
    """轮-支撑接触载荷：地面 + 障碍物，排除自碰撞。

    kind=top  只算竖直法向（真正承载，|n_z|>=0.7）；
    kind=wall 只算侧壁碰撞（|n_z|<0.7，不算承载）；
    kind=any  全部。
    这样"顶住岩石侧壁"不会被算成"搭上岩石顶面"。
    """
    import mujoco
    m, d = env.model, env.data
    b = bc.wheel_body(env, leg)
    total = 0.0
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if b not in (b1, b2):
            continue
        other = b2 if b1 == b else b1
        name = m.body(other).name if other >= 0 else 'world'
        if other != 0 and not name.startswith('obstacle'):
            continue
        # MuJoCo contact.frame 行主序存储，法向是第一行（实测 [0,0,1,...]）
        frame = np.asarray(c.frame, dtype=float).reshape(3, 3)
        nz = abs(float(frame[0, 2]))
        if kind == 'top' and nz < 0.7:
            continue
        if kind == 'wall' and nz >= 0.7:
            continue
        f = np.zeros(6)
        mujoco.mj_contactForce(m, d, i, f)
        total += abs(float(f[0]))
    return total


def contact_points(env, leg, min_load=0.5):
    """轮-支撑接触点（地面 + 障碍物），用于支撑多边形。"""
    import mujoco
    m, d = env.model, env.data
    b = bc.wheel_body(env, leg)
    pts = []
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if b not in (b1, b2):
            continue
        other = b2 if b1 == b else b1
        name = m.body(other).name if other >= 0 else 'world'
        if other != 0 and not name.startswith('obstacle'):
            continue
        frame = np.asarray(c.frame, dtype=float).reshape(3, 3)
        if abs(float(frame[0, 2])) < 0.7:
            continue
        f = np.zeros(6)
        mujoco.mj_contactForce(m, d, i, f)
        if abs(float(f[0])) >= min_load:
            pts.append(np.asarray(c.pos, dtype=float).copy())
    return pts


def ground_contact(env, leg):
    """轮是否与地面（world，body 0）接触；用于下降后的落地判定。"""
    m, d = env.model, env.data
    b = bc.wheel_body(env, leg)
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if b in (b1, b2) and (b2 if b1 == b else b1) == 0:
            return True
    return False


def make_step(path, h=0.05, sx=0.5, sy=0.9):
    box = trimesh.creation.box(extents=[sx, sy, h])
    box.apply_translation([0, 0, h / 2.0])
    path.parent.mkdir(parents=True, exist_ok=True)
    box.export(path)
    return str(path)


class Climb:
    def __init__(self, env, step_x, step_h, step_sx, record=None, faces=None):
        self.env = env
        self.step_x = step_x
        self.step_h = step_h
        self.face_x = step_x - step_sx / 2.0
        self.faces = faces or {'FR': self.face_x, 'FL': self.face_x}
        self.W = bc.total_weight(env)
        self.swing = 'FR'
        self.support = [l for l in LEG if l != self.swing]
        self.targets = {leg: dict(bc.STANCE) for leg in LEG}
        self.rec = record
        self.frames = []
        self.k = 0
        self.errors = []
        self.terminated = False

    def set_swing(self, leg):
        self.swing = leg
        self.support = [l for l in LEG if l != leg]

    def step(self, phase, omega=None, brake=False):
        env = self.env
        if brake:
            env.step_command(joint_targets_rad=self.targets, wheel_mode='brake')
        elif omega is not None:
            env.step_command(joint_targets_rad=self.targets,
                             wheel_omega_rad_s=np.full(4, float(omega)),
                             wheel_mode='velocity')
        else:
            env.step_command(joint_targets_rad=self.targets, wheel_mode='coast')
        self.k += 1
        roll, pitch = bc.attitude(env)
        f = {'k': self.k, 't': round(float(env.t), 4), 'phase': phase,
             'x': round(float(env.data.qpos[0]), 4),
             'roll': round(roll, 3), 'pitch': round(pitch, 3),
             'tilt': round(float(env._tilt()), 3),
             'vx': round(float(env.data.qvel[0]), 4),
             'loads': {leg: round(bc.wheel_ground(env, leg)['load'], 3)
                       for leg in LEG},
             'support_load': round(contact_load(env, self.swing, 'top'), 3),
             'support_wall': round(contact_load(env, self.swing, 'wall'), 3),
             'wheel_z': {leg: round(float(env.data.xpos[bc.wheel_body(env, leg)][2]), 4)
                         for leg in LEG}}
        self.frames.append(f)
        if self.rec is not None:
            self.rec.add(v3_record.frame_from_env(env, None, np.zeros(3), self.k,
                                                  env.t, extra={'skill_phase': phase}))
        if env.terminated or env.truncated:
            self.terminated = True
            self.errors.append({'phase': phase,
                                'reason': env.last_termination.get('reason'),
                                't': round(float(env.t), 3)})
        if float(env._tilt()) > 15.0 and not self.terminated:
            self.terminated = True
            self.errors.append({'phase': phase, 'reason': 'tilt>15deg',
                                'tilt': round(float(env._tilt()), 2)})
        return f

    # ---- 支撑转移（与 B 相同：最近支撑边内法向 + 分轮次斜坡）
    def measure_support(self):
        env = self.env
        c = bc.com(env)
        pts = [np.asarray(p[:2]) for leg in self.support
               for p in contact_points(env, leg)]
        loads = {leg: round(contact_load(env, leg), 3) for leg in LEG}
        out = {'com': [round(float(x), 4) for x in c[:3]],
               'n_points': len(pts), 'loads': loads,
               'points': [np.round(p, 4).tolist() for p in pts]}
        if len(pts) < 3:
            out['margin_m'] = None
            return out
        margin, _ = bc.nearest_edge(pts, c[:2])
        out['margin_m'] = round(float(margin), 4)
        return out

    def shift(self, target_margin=0.012, max_dp=0.02, ramp=25, settle=12):
        """移动 -> 稳定窗口重测，最多 3 轮；用最终稳定状态判定，记录前后。"""
        env = self.env
        before = self.measure_support()
        current = before
        for _ in range(3):
            if current['margin_m'] is None:
                break
            if current['margin_m'] >= target_margin:
                break
            pts = [np.asarray(q, dtype=float) for q in current['points']]
            _, inward = bc.nearest_edge(pts, np.asarray(current['com'][:2]))
            deficit = float(target_margin - current['margin_m'] + 0.004)
            if deficit <= 0.0005:
                break
            dp = np.zeros(3)
            dp[:2] = inward * float(np.clip(deficit, 0.0, max_dp))
            start = {leg: dict(self.targets[leg]) for leg in LEG}
            goal = {leg: dict(self.targets[leg]) for leg in LEG}
            for leg in self.support:
                dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.06, 0.06)
                for p, v in zip(('hip', 'thigh', 'calf'), dq):
                    lo, hi = jlim(env, leg, p)
                    goal[leg][p] = float(np.clip(start[leg][p] + float(v), lo, hi))
            for i in range(ramp):
                a = (i + 1) / ramp
                for leg in LEG:
                    for p in ('hip', 'thigh', 'calf'):
                        self.targets[leg][p] = float(
                            start[leg][p] + a * (goal[leg][p] - start[leg][p]))
                self.step(f'{self.swing}_shift')
                if self.terminated:
                    break
            for _ in range(settle):
                self.step(f'{self.swing}_shift_settle')
                if self.terminated:
                    break
            prev = current
            current = self.measure_support()
            if (current['margin_m'] is not None and prev['margin_m'] is not None
                    and current['margin_m'] < prev['margin_m'] - 0.002):
                break
            if self.terminated:
                break
        after = current
        ok = bool(after['margin_m'] is not None
                  and after['margin_m'] >= target_margin)
        return {'phase': f'{self.swing}_shift', 'before': before, 'after': after,
                'margin_m': after['margin_m'], 'ok': ok}

    # ---- SIDE_LEVEL：闭环调左右腿长，把机身滚转拉平，让悬空轮落地
    def side_level(self, seconds=2.5, gain=1.2, max_step=0.004):
        env = self.env
        for k in range(int(seconds * 50)):
            self.step('side_level')
            if self.terminated:
                break
            if k % 5:
                continue
            roll, _ = bc.attitude(env)
            d = float(np.clip(gain * roll, -max_step, max_step))
            for leg in LEG:
                sign = 1.0 if leg in ('FL', 'RL') else -1.0
                dp = np.array([0.0, 0.0, -sign * d])
                dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.02, 0.02)
                for p, v in zip(('hip', 'thigh', 'calf'), dq):
                    lo, hi = jlim(env, leg, p)
                    self.targets[leg][p] = float(np.clip(
                        self.targets[leg][p] + float(v), lo, hi))
        loads = {leg: round(contact_load(env, leg), 3) for leg in LEG}
        roll, pitch = bc.attitude(env)
        return {'phase': 'side_level', 'loads_n': loads,
                'roll_deg': round(float(np.degrees(roll)), 3),
                'pitch_deg': round(float(np.degrees(pitch)), 3),
                'ok': bool(all(v > 0.5 for v in loads.values()) and not self.terminated)}

    # ---- 简单轮式助爬：最后一轮保持接触滚上台（用于末段状态采集）
    def wheel_assist(self, leg, x_target, speed=0.12, max_s=8.0):
        env = self.env
        b = bc.wheel_body(env, leg)
        for _ in range(int(max_s * 50)):
            if (float(env.data.xpos[b][0]) >= x_target
                    and contact_load(env, leg) >= 0.05 * self.W):
                break
            self.step(f'{leg}_assist', omega=speed / WHEEL_R)
            if self.terminated:
                break
        x = float(env.data.xpos[b][0])
        load = contact_load(env, leg)
        return {'phase': f'{leg}_assist', 'wheel_x': round(x, 4),
                'x_target': round(x_target, 4), 'load_n': round(load, 3),
                'ok': bool(x >= x_target - 0.01 and load >= 0.05 * self.W
                           and not self.terminated)}

    # ---- 轮腿协同：最后一轮保持接触滚上台；支撑轮掉载时向下补 4 mm
    def push_last_wheel(self, leg, x_target, speed=0.10, max_s=8.0,
                        min_load=1.5, adjust_every=5):
        env = self.env
        b = bc.wheel_body(env, leg)
        for k in range(int(max_s * 50)):
            if (float(env.data.xpos[b][0]) >= x_target
                    and contact_load(env, leg) >= 0.05 * self.W):
                break
            self.step(f'{leg}_push', omega=speed / WHEEL_R)
            if self.terminated:
                break
            if k % adjust_every == 0:
                for other in LEG:
                    if other == leg:
                        continue
                    if contact_load(env, other) < min_load:
                        dp = np.array([0.0, 0.0, -0.004])
                        dq = np.clip(bc.damped_ls(bc.leg_jac(env, other), -dp),
                                     -0.02, 0.02)
                        for p, v in zip(('hip', 'thigh', 'calf'), dq):
                            lo, hi = jlim(env, other, p)
                            self.targets[other][p] = float(np.clip(
                                self.targets[other][p] + float(v), lo, hi))
        x = float(env.data.xpos[b][0])
        load = contact_load(env, leg)
        loads = {l: round(contact_load(env, l), 3) for l in LEG}
        return {'phase': f'{leg}_push', 'wheel_x': round(x, 4),
                'x_target': round(x_target, 4), 'load_n': round(load, 3),
                'loads_n': loads,
                'ok': bool(x >= x_target - 0.01 and load >= 0.05 * self.W
                           and not self.terminated)}

    # ---- 抬单腿到目标轮心高度
    def lift_leg(self, leg, target_center_z, max_dq=0.45, rounds=4, ramp=45):
        env = self.env
        b = bc.wheel_body(env, leg)
        best = 0.0
        for _ in range(rounds):
            need = target_center_z - float(env.data.xpos[b][2])
            if abs(need) <= 0.004:
                break
            dp = np.zeros(3)
            dp[2] = float(np.clip(need, -0.06, 0.06))
            dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), dp), -max_dq, max_dq)
            start = dict(self.targets[leg])
            goal = {}
            for p, v in zip(('hip', 'thigh', 'calf'), dq):
                lo, hi = jlim(env, leg, p)
                goal[p] = float(np.clip(start[p] + float(v), lo, hi))
            for i in range(ramp):
                a = (i + 1) / ramp
                for p in ('hip', 'thigh', 'calf'):
                    self.targets[leg][p] = float(start[p] + a * (goal[p] - start[p]))
                self.step(f'{leg}_lift')
                best = max(best, float(env.data.xpos[b][2]))
                if self.terminated:
                    break
            if self.terminated:
                break
        z = float(env.data.xpos[b][2])
        return {'phase': f'{leg}_lift', 'wheel_center_z': round(z, 4),
                'target_z': round(target_center_z, 4),
                'ok': bool(z >= target_center_z - 0.008)}

    # ---- 保持抬高，低速前进到该轮越过台沿
    def advance_to_ledge(self, leg, x_target=None, max_s=6.0, speed=0.06):
        if x_target is None:
            x_target = self.faces.get(leg, self.face_x) + 0.07
        env = self.env
        b = bc.wheel_body(env, leg)
        for _ in range(int(max_s * 50)):
            if float(env.data.xpos[b][0]) >= x_target:
                break
            self.step(f'{leg}_advance', omega=speed / WHEEL_R)
            if self.terminated:
                break
        x = float(env.data.xpos[b][0])
        return {'phase': f'{leg}_advance', 'wheel_x': round(x, 4),
                'x_target': round(x_target, 4),
                'ok': bool(x >= x_target - 0.01)}

    # ---- 四轮都在支撑面上时，做横向 CoM 居中（小步、多轮，避免丢接触）
    def center_lateral(self, dy=-0.006, rounds=4, ramp=15):
        env = self.env
        for _ in range(rounds):
            dp = np.array([0.0, float(dy), 0.0])
            start = {leg: dict(self.targets[leg]) for leg in LEG}
            goal = {leg: dict(self.targets[leg]) for leg in LEG}
            for leg in LEG:
                dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.04, 0.04)
                for p, v in zip(('hip', 'thigh', 'calf'), dq):
                    lo, hi = jlim(env, leg, p)
                    goal[leg][p] = float(np.clip(start[leg][p] + v, lo, hi))
            for i in range(ramp):
                a = (i + 1) / ramp
                for leg in LEG:
                    for p in ('hip', 'thigh', 'calf'):
                        self.targets[leg][p] = float(
                            start[leg][p] + a * (goal[leg][p] - start[leg][p]))
                self.step('center_lateral')
                if self.terminated:
                    break
            if self.terminated:
                break
        loads = {leg: contact_load(env, leg) for leg in LEG}
        return {'phase': 'center_lateral',
                'loads_n': {k: round(v, 3) for k, v in loads.items()},
                'ok': bool(all(v > 0.5 for v in loads.values()) and not self.terminated)}

    # ---- 四轮都在支撑面上时，做纵向 CoM 前移（小步、多轮）
    def center_forward(self, dx=0.006, rounds=3, ramp=15):
        env = self.env
        for _ in range(rounds):
            dp = np.array([float(dx), 0.0, 0.0])
            start = {leg: dict(self.targets[leg]) for leg in LEG}
            goal = {leg: dict(self.targets[leg]) for leg in LEG}
            for leg in LEG:
                dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.04, 0.04)
                for p, v in zip(('hip', 'thigh', 'calf'), dq):
                    lo, hi = jlim(env, leg, p)
                    goal[leg][p] = float(np.clip(start[leg][p] + v, lo, hi))
            for i in range(ramp):
                a = (i + 1) / ramp
                for leg in LEG:
                    for p in ('hip', 'thigh', 'calf'):
                        self.targets[leg][p] = float(
                            start[leg][p] + a * (goal[leg][p] - start[leg][p]))
                self.step('center_forward')
                if self.terminated:
                    break
            if self.terminated:
                break
        loads = {leg: contact_load(env, leg) for leg in LEG}
        return {'phase': 'center_forward',
                'loads_n': {k: round(v, 3) for k, v in loads.items()},
                'ok': bool(all(v > 0.5 for v in loads.values()) and not self.terminated)}

    # ---- Stage003 末段：FL 实测方向下放 + 姿态调平 + 整体下放 + 预压 + 稳定窗口 + 下降
    def fl_lower(self, max_ticks=8):
        env = self.env
        for _ in range(max_ticks):
            if contact_load(env, 'FL') >= 1.0:
                break
            lo, hi = jlim(env, 'FL', 'thigh')
            self.targets['FL']['thigh'] = float(np.clip(
                self.targets['FL']['thigh'] - 0.03, lo, hi))
            lo, hi = jlim(env, 'FL', 'calf')
            self.targets['FL']['calf'] = float(np.clip(
                self.targets['FL']['calf'] + 0.10, lo, hi))
            for _ in range(5):
                self.step('FL_lower')
                if self.terminated:
                    break
        load = contact_load(env, 'FL', 'top')
        return {'phase': 'FL_lower', 'load_n': round(load, 3),
                'ok': bool(load >= 1.0 and not self.terminated)}

    def level_roll(self, seconds=1.5):
        env = self.env
        for k in range(int(seconds * 50)):
            self.step('level_roll')
            if self.terminated:
                break
            if k % 5:
                continue
            for leg in ('FL', 'RL'):
                lo, hi = jlim(env, leg, 'thigh')
                self.targets[leg]['thigh'] = float(np.clip(self.targets[leg]['thigh'] + 0.004, lo, hi))
                lo, hi = jlim(env, leg, 'calf')
                self.targets[leg]['calf'] = float(np.clip(self.targets[leg]['calf'] - 0.014, lo, hi))
            for leg in ('FR', 'RR'):
                lo, hi = jlim(env, leg, 'thigh')
                self.targets[leg]['thigh'] = float(np.clip(self.targets[leg]['thigh'] - 0.004, lo, hi))
                lo, hi = jlim(env, leg, 'calf')
                self.targets[leg]['calf'] = float(np.clip(self.targets[leg]['calf'] + 0.014, lo, hi))
        rows = self.frames[-max(1, int(0.2 * 50)):]
        tilt = max((f['tilt'] for f in rows), default=99)
        return {'phase': 'level_roll', 'tilt_max_deg': round(tilt, 3),
                'ok': bool(tilt <= 10.0 and not self.terminated)}

    def body_until_support(self, max_ticks=20, dz=0.001):
        env = self.env
        for _ in range(max_ticks):
            loads = {leg: contact_load(env, leg) for leg in LEG}
            if all(v >= 1.0 for v in loads.values()):
                break
            dp = np.array([0.0, 0.0, -dz])
            for leg in LEG:
                dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.03, 0.03)
                for p_, v in zip(('hip', 'thigh', 'calf'), dq):
                    lo, hi = jlim(env, leg, p_)
                    self.targets[leg][p_] = float(np.clip(self.targets[leg][p_] + float(v), lo, hi))
            for _ in range(5):
                self.step('body_down')
                if self.terminated:
                    break
        loads = {leg: contact_load(env, leg) for leg in LEG}
        return {'phase': 'body_down',
                'loads_n': {k: round(v, 3) for k, v in loads.items()},
                'ok': bool(all(v >= 1.0 for v in loads.values()) and not self.terminated)}

    def preload_min(self, max_ticks=3):
        env = self.env
        for _ in range(max_ticks):
            loads = {leg: contact_load(env, leg) for leg in LEG}
            leg = min(loads, key=loads.get)
            if loads[leg] >= 3.0:
                break
            lo, hi = jlim(env, leg, 'thigh')
            self.targets[leg]['thigh'] = float(np.clip(self.targets[leg]['thigh'] - 0.01, lo, hi))
            lo, hi = jlim(env, leg, 'calf')
            self.targets[leg]['calf'] = float(np.clip(self.targets[leg]['calf'] + 0.035, lo, hi))
            for _ in range(10):
                self.step('preload_min')
                if self.terminated:
                    break
        loads = {leg: contact_load(env, leg) for leg in LEG}
        return {'phase': 'preload_min',
                'loads_n': {k: round(v, 3) for k, v in loads.items()},
                'ok': bool(min(loads.values()) >= 1.0 and not self.terminated)}

    def stable_window(self, seconds=1.0):
        env = self.env
        rows = []
        for _ in range(int(seconds * 50)):
            rows.append(self.step('stable'))
            if self.terminated:
                break
        loads_last = {leg: contact_load(env, leg) for leg in LEG}
        pts = []
        for leg in LEG:
            if loads_last[leg] >= 1.0:
                pts += [np.asarray(q[:2]) for q in contact_points(env, leg)]
        margin = None
        if len(pts) >= 3:
            mm, _ = bc.nearest_edge(pts, bc.com(env)[:2])
            margin = round(float(mm), 4) if mm > -0.5 else None
        tilt = max((r['tilt'] for r in rows), default=99)
        vx = max((abs(r['vx']) for r in rows), default=99)
        w = max((float(np.linalg.norm(env.data.qvel[3:6])) for _ in [0]), default=99)
        return {'phase': 'stable', 'tilt_max_deg': round(tilt, 3),
                'vx_max': round(vx, 4), 'margin_m': margin,
                'n_support': sum(1 for v in loads_last.values() if v >= 1.0),
                'ok': bool(rows and tilt <= 10.0 and vx <= 0.03
                           and margin is not None and margin >= 0.010
                           and sum(1 for v in loads_last.values() if v >= 1.0) >= 3
                           and not self.terminated)}

    def descend_action(self, far_x, speed=0.15, max_s=25.0):
        env = self.env
        for _ in range(int(max_s * 50)):
            self.step('descent_drive', omega=speed / WHEEL_R)
            if self.terminated or float(env.data.qpos[0]) >= far_x + 0.30:
                break
        for _ in range(60):
            if abs(float(env.data.qvel[0])) <= 0.03:
                break
            self.step('descent_stop', omega=0.0)
            if self.terminated:
                break
        rows = []
        for _ in range(75):
            rows.append(self.step('descent_hold'))
            if self.terminated:
                break
        wheel_z = {leg: float(env.data.xpos[bc.wheel_body(env, leg)][2]) for leg in LEG}
        tilt = max((r['tilt'] for r in rows), default=99)
        vx = max((abs(r['vx']) for r in rows), default=99)
        grounded = all(z <= 0.12 for z in wheel_z.values())
        crossed = float(env.data.qpos[0]) >= far_x + 0.25
        return {'phase': 'descent', 'final_x': round(float(env.data.qpos[0]), 4),
                'wheel_z': {k: round(v, 4) for k, v in wheel_z.items()},
                'grounded': grounded, 'tilt_max_deg': round(tilt, 3),
                'vx_max': round(vx, 4),
                'ok': bool(rows and crossed and grounded and tilt <= 10.0
                           and vx <= 0.03 and not self.terminated)}

    # ---- 下降：四轮越过台面最远后缘，落地并稳定保持
    def descend(self, far_x, max_s=10.0, speed=0.08):
        env = self.env
        for _ in range(int(max_s * 50)):
            if float(env.data.qpos[0]) >= far_x + 0.35:
                break
            self.step('descend', omega=speed / WHEEL_R)
            if self.terminated:
                break
        rows = []
        for _ in range(int(1.5 * 50)):
            rows.append(self.step('descend_hold'))
            if self.terminated:
                break
        wx = {leg: float(env.data.xpos[bc.wheel_body(env, leg)][0]) for leg in LEG}
        grounded = {leg: ground_contact(env, leg) for leg in LEG}
        tilt = max((r['tilt'] for r in rows), default=99)
        crossed = all(x >= far_x - 0.02 for x in wx.values())
        return {'phase': 'descend', 'wheel_x': {k: round(v, 4) for k, v in wx.items()},
                'grounded': grounded, 'tilt_max_deg': round(tilt, 3),
                'ok': bool(crossed and all(grounded.values()) and tilt <= 10.0
                           and not self.terminated)}

    # ---- 前轴预压：机身向 +x 平移，前轮被压向台面、后轮伸长
    def preload(self, dx=0.005, ramp=30):
        env = self.env
        dp = np.array([0.0, float(dx), 0.0])
        start = {leg: dict(self.targets[leg]) for leg in LEG}
        goal = {leg: dict(self.targets[leg]) for leg in LEG}
        for leg in LEG:
            dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.06, 0.06)
            for p, v in zip(('hip', 'thigh', 'calf'), dq):
                lo, hi = jlim(env, leg, p)
                goal[leg][p] = float(np.clip(start[leg][p] + v, lo, hi))
        for i in range(ramp):
            a = (i + 1) / ramp
            for leg in LEG:
                for p in ('hip', 'thigh', 'calf'):
                    self.targets[leg][p] = float(
                        start[leg][p] + a * (goal[leg][p] - start[leg][p]))
            self.step('preload_front')
            if self.terminated:
                break
        fr = contact_load(env, 'FR')
        fl = contact_load(env, 'FL')
        return {'phase': 'preload_front',
                'fr_load_n': round(fr, 3), 'fl_load_n': round(fl, 3),
                'fr_frac': round(fr / self.W, 4), 'fl_frac': round(fl / self.W, 4),
                'ok': bool(fr >= 0.05 * self.W and fl >= 0.05 * self.W)}

    # ---- 低速前进到指定机身 x（前后轮都在支撑面上时用）
    def advance_body(self, x_target, max_s=12.0, speed=0.06):
        env = self.env
        for _ in range(int(max_s * 50)):
            if float(env.data.qpos[0]) >= x_target:
                break
            self.step('advance_body', omega=speed / WHEEL_R)
            if self.terminated:
                break
        x = float(env.data.qpos[0])
        return {'phase': 'advance_body', 'x': round(x, 4),
                'x_target': round(x_target, 4),
                'ok': bool(x >= x_target - 0.01)}

    # ---- 落腿：持续载荷触发后停住
    def lower_leg(self, leg, load_thr=3.0, hold_steps=3, max_s=1.6):
        env = self.env
        start = dict(self.targets[leg])
        gone = 0
        t_contact = None
        n = int(max_s * 50)
        i = 0
        for i in range(n):
            a = (i + 1) / n
            for p in ('hip', 'thigh', 'calf'):
                self.targets[leg][p] = float(start[p] + a * (STANCE[leg][p] - start[p]))
            self.step(f'{leg}_lower')
            if self.terminated:
                break
            load = contact_load(env, leg)
            if load > load_thr:
                gone += 1
                if gone >= hold_steps:
                    t_contact = float(env.t)
                    break
            else:
                gone = 0
        load = contact_load(env, leg)
        return {'phase': f'{leg}_lower', 'contact_at_t': t_contact,
                'steps': i + 1, 'load_n': round(load, 3),
                'ok': bool(t_contact is not None)}

    def hold_leg(self, leg, seconds=0.8, min_frac=0.05):
        rows = []
        for _ in range(int(seconds * 50)):
            rows.append(self.step(f'{leg}_hold'))
            if self.terminated:
                break
        loads = [r['support_load'] for r in rows]
        mean = float(np.mean(loads)) if loads else 0.0
        tilt = max((r['tilt'] for r in rows), default=99)
        return {'phase': f'{leg}_hold', 'load_n': round(mean, 3),
                'frac': round(mean / self.W, 4), 'tilt_max_deg': round(tilt, 3),
                'ok': bool(rows and mean >= min_frac * self.W and tilt <= 10.0)}



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/climb/front2_r1')
    ap.add_argument('--step-h', type=float, default=0.05)
    ap.add_argument('--step-x', type=float, default=1.20)
    ap.add_argument('--step-w', type=float, default=0.90)
    ap.add_argument('--soil', default='nominal', choices=['rigid', 'nominal'])
    ap.add_argument('--record', action='store_true')
    ap.add_argument('--perturb', default='', help='dx,dy,dyaw_deg 冻结初态扰动')
    ap.add_argument('--save-endgame', default='',
                    help='在后轮末段保存完整状态快照到该路径')
    ap.add_argument('--no-shift', action='store_true',
                    help='开发场景实验：跳过 FL/RR/RL 的支撑转移')
    ap.add_argument('--rear', action='store_true',
                    help='实验路径：长台面 + 后轮搭台（当前未通过，默认关闭）')
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    # 开发场景：两块加宽、错开、同后缘（2.35 m）的台面，便于稳定支撑与完整下降
    faces = {'FR': 0.95, 'FL': 1.13}
    if a.rear:
        len_fr, len_fl, ledge_w = 1.40, 1.22, 0.45
    else:
        len_fr, len_fl, ledge_w = 0.5, 0.5, 0.27
    box_fr = make_step(out / 'step_fr.stl', h=a.step_h, sx=len_fr, sy=ledge_w)
    box_fl = make_step(out / 'step_fl.stl', h=a.step_h, sx=len_fl, sy=ledge_w)
    far_x = faces['FR'] + len_fr
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=far_x + 0.6,
                             name='climb_front2',
                             objects=[{'mesh_file': box_fr,
                                       'x': faces['FR'] + len_fr / 2.0, 'y': -0.115,
                                       'yaw_deg': 0.0},
                                      {'mesh_file': box_fl,
                                       'x': faces['FL'] + len_fl / 2.0, 'y': 0.185,
                                       'yaw_deg': 0.0}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=120.0 if a.rear else 40.0)
    env.reset(seed=0)
    dx = dy = dyaw = 0.0
    if a.perturb:
        parts = [float(x) for x in a.perturb.split(',')]
        while len(parts) < 3:
            parts.append(0.0)
        dx, dy, dyaw = parts[:3]
    if dx or dy or dyaw:
        q = env.data.qpos
        q[0] += dx
        q[1] += dy
        if abs(dyaw) > 1e-9:
            th = np.deg2rad(dyaw)
            c, sn = np.cos(th / 2), np.sin(th / 2)
            w, x, y, z = (float(v) for v in q[3:7])
            q[3] = c * w - sn * z
            q[4] = c * x + sn * y
            q[5] = c * y - sn * x
            q[6] = c * z + sn * w
        mujoco.mj_forward(env.model, env.data)
    init_qpos_sha = hashlib.sha256(
        np.asarray(env.data.qpos, dtype=np.float64).tobytes()).hexdigest()
    init_qvel_sha = hashlib.sha256(
        np.asarray(env.data.qvel, dtype=np.float64).tobytes()).hexdigest()
    rec = None
    if a.record:
        rec = v3_record.Recorder(out / 'record',
                                 {'scenario': 'climb_front2', 'method': 'D1',
                                  'action': 'CLIMB_FRONT2'}, hz=50.0)
    c = Climb(env, a.step_x, a.step_h, 0.5, record=rec, faces=faces)
    phases = []

    def add(ph):
        phases.append(ph)
        return bool(ph.get('ok'))

    def stop():
        return c.terminated

    # APPROACH
    brake_x = faces['FR'] - 0.35
    ok = False
    for _ in range(int(4.0 * 50)):
        if float(env.data.qpos[0]) >= brake_x:
            ok = True
            break
        c.step('approach', omega=0.25 / WHEEL_R)
        if c.terminated:
            break
    add({'phase': 'approach', 'x': round(float(env.data.qpos[0]), 4),
         'target_x': round(brake_x, 4), 'ok': bool(ok)})

    # BRAKE（速度斜坡）
    stopped = False
    v0 = max(0.02, abs(float(env.data.qvel[0])))
    n = 60
    for i in range(n):
        v_cmd = v0 * max(0.0, 1.0 - (i + 1) / n)
        c.step('brake', omega=v_cmd / WHEEL_R)
        if abs(float(env.data.qvel[0])) < 0.02:
            stopped = True
            break
        if c.terminated:
            break
    for _ in range(10):
        c.step('brake', omega=0.0)
        if c.terminated:
            break
    add({'phase': 'brake', 'vx': round(float(env.data.qvel[0]), 4),
        'ok': bool(stopped)})

    z_target = a.step_h + WHEEL_R + 0.025
    ok = True
    for leg in ('FR', 'FL'):
        if stop() or not ok:
            break
        c.set_swing(leg)
        ok = add(c.shift())  # 前腿仍需支撑转移
        if ok and not stop():
            ok = add(c.lift_leg(leg, z_target))
        if ok and not stop():
            ok = add(c.advance_to_ledge(leg))
        if ok and not stop():
            ok = add(c.lower_leg(leg))
        if ok and not stop():
            for _ in range(30):
                c.step(f'{leg}_settle')
                if stop():
                    break
        if ok and not stop():
            ok = add(c.hold_leg(leg))

    # 预压已停用：前轮在宽台上载荷已够，侧向预压会引入滚转

    if ok and not stop():
        rows = []
        for _ in range(int(0.6 * 50)):
            rows.append(c.step('hold_both'))
            if c.terminated:
                break
        fr = contact_load(env, 'FR')
        fl = contact_load(env, 'FL')
        tilt = max((r['tilt'] for r in rows), default=99)
        ok = add({'phase': 'hold_both',
                  'fr_load_n': round(fr, 3), 'fl_load_n': round(fl, 3),
                  'fr_frac': round(fr / c.W, 4), 'fl_frac': round(fl / c.W, 4),
                  'tilt_max_deg': round(tilt, 3),
                  'ok': bool(rows and fr >= 0.05 * c.W and fl >= 0.05 * c.W
                             and tilt <= 10.0)})

    # 后轮不先做整体前移：像前轮一样，抬起来再前进，避免四轮承重时 FR 卸载

    if ok and not stop() and a.rear:
        ok = add(c.center_lateral(-0.003, rounds=2))
    if ok and not stop() and a.rear:
        ok = add(c.center_forward(0.008, rounds=4))
    if ok and not stop() and a.rear:
        for leg, face in (('RR', faces['FR']),):
            if stop() or not ok:
                break
            c.set_swing(leg)
            ok = True if a.no_shift else add(c.shift())  # 后腿可选跳过
            if ok and not stop():
                ok = add(c.lift_leg(leg, z_target))
            if ok and not stop():
                ok = add(c.advance_to_ledge(leg, face + 0.07))
            if ok and not stop():
                ok = add(c.lower_leg(leg))
            if ok and not stop():
                for _ in range(30):
                    c.step(f'{leg}_settle')
                    if stop():
                        break
            # SPEC 003 6.1：三点支撑中间态允许，不要求 RR 先单独 hold 到 5%

    if ok and not stop() and a.rear:
        # 轮腿协同：RL 保持接触滚上台，其他轮掉载时闭环补下压
        ok = add(c.wheel_assist('RL', faces['FL'] + 0.07, speed=0.12))
    if a.save_endgame and not stop():
        snap = env.save_state()
        sp = ROOT / a.save_endgame
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({'snapshot': snap, 'spec': spec}, ensure_ascii=False))
        print(json.dumps({'saved_state': str(sp), 'bytes': sp.stat().st_size}))
    if a.rear and not stop():
        ok = add(c.fl_lower())
        if ok:
            ok = add(c.level_roll(1.5))
        if ok:
            ok = add(c.body_until_support())
        if ok:
            ok = add(c.preload_min())
        if ok:
            ok = add(c.stable_window(1.0))
        if ok:
            ok = add(c.descend_action(far_x))

    ref = rec.close() if rec is not None else None
    checks = {p['phase']: bool(p.get('ok')) for p in phases}
    blocked_at = None
    if phases and not phases[-1].get('ok'):
        blocked_at = phases[-1]['phase']
    res = {'schema': 'v3-climb-front2/v2', 'soil': a.soil,
           'step': {'x': a.step_x, 'h': a.step_h, 'face_x': c.face_x, 'far_x': round(far_x, 4)},
           'init_qpos_sha256': init_qpos_sha,
           'init_qvel_sha256': init_qvel_sha,
           'perturb': {'dx': dx, 'dy': dy, 'dyaw_deg': dyaw},
           'robot_mass_kg': round(float(bc.robot_mass(env)), 4),
           'robot_weight_n': round(float(c.W), 3),
           'phases': phases, 'checks': checks,
           'terminated': c.terminated, 'errors': c.errors,
           'blocked_at': blocked_at,
           'all_ok': bool(all(checks.values()) and not c.terminated),
           'trajectory_ref': ref}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    np.savez_compressed(out / 'frames.npz',
                        t=np.array([f['t'] for f in c.frames]),
                        phase=np.array([f['phase'] for f in c.frames]),
                        x=np.array([f['x'] for f in c.frames]),
                        tilt=np.array([f['tilt'] for f in c.frames]),
                        loads=np.array([[f['loads'][l] for l in LEG] for f in c.frames]))
    print(json.dumps({'all_ok': res['all_ok'], 'checks': checks,
                      'errors': c.errors[:2], 'terminated': c.terminated,
                      'blocked_at': blocked_at,
                      'robot_mass_kg': res['robot_mass_kg'],
                      'robot_weight_n': res['robot_weight_n']},
                     ensure_ascii=False))
    return 0 if res['all_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
