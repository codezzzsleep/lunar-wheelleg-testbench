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
import json
import pathlib
import sys

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
    def shift(self, target_margin=0.012, max_dp=0.03, ramp=30):
        env = self.env
        best = None
        gentle = self.swing == 'RL'   # 最后一条腿：小步、只走一轮，避免丢接触
        rounds = 1 if gentle else 3
        max_dp = 0.004 if gentle else max_dp
        for _ in range(rounds):
            c = bc.com(env)
            pts = [np.asarray(p[:2]) for leg in self.support
                   for p in contact_points(env, leg)]
            if len(pts) < 3:
                break
            margin, inward = bc.nearest_edge(pts, c[:2])
            best = margin if best is None else max(best, margin)
            if margin >= target_margin:
                break
            dp = np.zeros(3)
            dp[:2] = inward * float(np.clip(target_margin - margin + 0.004, 0, max_dp))
            start = {leg: dict(self.targets[leg]) for leg in LEG}
            goal = {leg: dict(self.targets[leg]) for leg in LEG}
            for leg in self.support:
                dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), -dp), -0.08, 0.08)
                for p, v in zip(('hip', 'thigh', 'calf'), dq):
                    goal[leg][p] = float(np.clip(start[leg][p] + v, -2.5, 2.5))
            for i in range(ramp):
                a = (i + 1) / ramp
                for leg in LEG:
                    for p in ('hip', 'thigh', 'calf'):
                        self.targets[leg][p] = float(
                            start[leg][p] + a * (goal[leg][p] - start[leg][p]))
                self.step(f'{self.swing}_shift')
                if self.terminated:
                    break
            if self.terminated:
                break
        return {'phase': f'{self.swing}_shift', 'margin_m': best,
                'ok': bool(best is not None and best >= target_margin)}

    # ---- 抬单腿到目标轮心高度
    def lift_leg(self, leg, target_center_z, max_dq=0.45, rounds=4, ramp=45):
        env = self.env
        b = bc.wheel_body(env, leg)
        best = 0.0
        for _ in range(rounds):
            need = target_center_z - float(env.data.xpos[b][2])
            if need <= 0.004:
                break
            dp = np.zeros(3)
            dp[2] = float(np.clip(need, -0.06, 0.06))
            dq = np.clip(bc.damped_ls(bc.leg_jac(env, leg), dp), -max_dq, max_dq)
            start = dict(self.targets[leg])
            goal = {p: float(np.clip(start[p] + float(v), -2.5, 2.5))
                    for p, v in zip(('hip', 'thigh', 'calf'), dq)}
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
                    goal[leg][p] = float(np.clip(start[leg][p] + v, -2.5, 2.5))
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
                goal[leg][p] = float(np.clip(start[leg][p] + v, -2.5, 2.5))
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
        for leg, face in (('RR', faces['FR']), ('RL', faces['FL'])):
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
            if ok and not stop():
                ok = add(c.hold_leg(leg))

    if ok and not stop() and a.rear:
        rows = []
        for _ in range(int(1.0 * 50)):
            rows.append(c.step('hold_all'))
            if c.terminated:
                break
        loads = {leg: contact_load(env, leg) for leg in LEG}
        tilt = max((r['tilt'] for r in rows), default=99)
        ok = add({'phase': 'hold_all',
                  'loads_n': {k: round(v, 3) for k, v in loads.items()},
                  'frac': {k: round(v / c.W, 4) for k, v in loads.items()},
                  'tilt_max_deg': round(tilt, 3),
                  'ok': bool(rows and all(v >= 0.05 * c.W for v in loads.values())
                             and tilt <= 10.0)})

    if ok and not stop() and a.rear:
        ok = add(c.descend(far_x))

    ref = rec.close() if rec is not None else None
    checks = {p['phase']: bool(p.get('ok')) for p in phases}
    blocked_at = None
    if phases and not phases[-1].get('ok'):
        blocked_at = phases[-1]['phase']
    res = {'schema': 'v3-climb-front2/v2', 'soil': a.soil,
           'step': {'x': a.step_x, 'h': a.step_h, 'face_x': c.face_x, 'far_x': round(far_x, 4)},
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
