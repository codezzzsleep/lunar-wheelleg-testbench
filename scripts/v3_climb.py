"""D1 第一里程碑：把 FR 前轮搭上台沿并真实承载。

场景：平地 + 一个 0.05 m 高的方台（已知几何，用于能力调试；正式执行不读真值参数）。
阶段：APPROACH -> BRAKE -> SHIFT_SUPPORT -> LIFT_FR -> ADVANCE_TO_LEDGE
      -> LOWER_FR -> HOLD_FRONT

每阶段有进入条件、最大时间、失败原因；成功判据用真实接触载荷、轮心高度与姿态，
不用目标角或"轮心 z 升高"代替。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_climb.py --out runs/v3/climb/front_r1
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


def contact_load(env, leg):
    """轮-支撑接触载荷：地面 + 障碍物（台沿/岩石），排除自碰撞。"""
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
        f = np.zeros(6)
        mujoco.mj_contactForce(m, d, i, f)
        total += abs(float(f[0]))
    return total


def make_step(path, h=0.05, sx=0.5, sy=0.8):
    box = trimesh.creation.box(extents=[sx, sy, h])
    box.apply_translation([0.0, 0.0, h / 2.0])
    path.parent.mkdir(parents=True, exist_ok=True)
    box.export(path)
    return str(path)


class Climb:
    def __init__(self, env, step_x, step_h, step_sx, record=None):
        self.env = env
        self.step_x = step_x
        self.step_h = step_h
        self.face_x = step_x - step_sx / 2.0
        self.W = bc.total_weight(env)
        self.swing = 'FR'
        self.support = [l for l in LEG if l != 'FR']
        self.targets = {leg: dict(bc.STANCE) for leg in LEG}
        self.rec = record
        self.frames = []
        self.k = 0
        self.errors = []
        self.terminated = False

    def step(self, phase, omega=None, wheel_mode='coast', brake=False):
        env = self.env
        if brake:
            env.step_command(joint_targets_rad=self.targets, wheel_mode='brake')
        elif omega is not None:
            # omega 非空必须走速度闭环；不能沿用 'coast' 把目标吃掉
            env.step_command(joint_targets_rad=self.targets,
                             wheel_omega_rad_s=np.full(4, float(omega)),
                             wheel_mode='velocity')
        else:
            env.step_command(joint_targets_rad=self.targets, wheel_mode=wheel_mode)
        self.k += 1
        roll, pitch = bc.attitude(env)
        f = {'k': self.k, 't': round(float(env.t), 4), 'phase': phase,
             'x': round(float(env.data.qpos[0]), 4),
             'roll': round(roll, 3), 'pitch': round(pitch, 3),
             'tilt': round(float(env._tilt()), 3),
             'vx': round(float(env.data.qvel[0]), 4),
             'loads': {leg: round(bc.wheel_ground(env, leg)['load'], 3)
                       for leg in LEG},
             'wheel_z': {leg: round(float(env.data.xpos[bc.wheel_body(env, leg)][2]), 4)
                         for leg in LEG},
             'fr_clearance': round(float(bc.wheel_clearance(env, 'FR')), 4),
             'fr_support_load': round(contact_load(env, 'FR'), 3),
             'margin': None}
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

    def shift(self, target_margin=0.012, max_s=2.0):
        """复用 B 的支撑转移：沿最近支撑边内法向，分轮次斜坡。"""
        env = self.env
        best = None
        for _ in range(3):
            st = bc.support_state(env, self.support, self.swing)
            pts = [np.asarray(p[:2]) for leg in self.support
                   for p in bc.wheel_ground(env, leg)['points']]
            if len(pts) < 3 or st['margin_m'] is None:
                break
            margin, inward = bc.nearest_edge(pts, np.asarray(st['com'][:2]))
            best = margin if best is None else max(best, margin)
            if margin >= target_margin:
                break
            dp = np.zeros(3)
            dp[:2] = inward * float(np.clip(target_margin - margin + 0.004, 0, 0.03))
            start = {leg: dict(self.targets[leg]) for leg in LEG}
            goal = {leg: dict(self.targets[leg]) for leg in LEG}
            for leg in self.support:
                J = bc.leg_jac(env, leg)
                dq = np.clip(bc.damped_ls(J, -dp), -0.08, 0.08)
                for p, v in zip(('hip', 'thigh', 'calf'), dq):
                    goal[leg][p] = float(np.clip(start[leg][p] + v, -2.5, 2.5))
            n = 30
            for i in range(n):
                a = (i + 1) / n
                for leg in LEG:
                    for p in ('hip', 'thigh', 'calf'):
                        self.targets[leg][p] = float(
                            start[leg][p] + a * (goal[leg][p] - start[leg][p]))
                self.step('shift_support')
                if self.terminated:
                    break
            if self.terminated:
                break
        return {'phase': 'shift_support', 'margin_m': best,
                'ok': bool(best is not None and best >= target_margin)}

    def lift_fr(self, target_center_z, max_s=2.4):
        """把 FR 轮心抬到 target_center_z（世界 z），用逐腿雅可比 + 斜坡。"""
        env = self.env
        b = bc.wheel_body(env, 'FR')
        best = 0.0
        for _ in range(4):
            need = target_center_z - float(env.data.xpos[b][2])
            if need <= 0.004:
                break
            dp = np.zeros(3)
            dp[2] = float(np.clip(need, -0.06, 0.06))
            J = bc.leg_jac(env, 'FR')
            dq = np.clip(bc.damped_ls(J, dp), -0.45, 0.45)
            start = dict(self.targets['FR'])
            goal = {p: float(np.clip(start[p] + float(v), -2.5, 2.5))
                    for p, v in zip(('hip', 'thigh', 'calf'), dq)}
            n = 45
            for i in range(n):
                a = (i + 1) / n
                for p in ('hip', 'thigh', 'calf'):
                    self.targets['FR'][p] = float(
                        start[p] + a * (goal[p] - start[p]))
                f = self.step('lift_fr')
                best = max(best, float(env.data.xpos[b][2]))
                if self.terminated:
                    break
            if self.terminated:
                break
        z = float(env.data.xpos[b][2])
        return {'phase': 'lift_fr', 'wheel_center_z': round(z, 4),
                'target_z': round(target_center_z, 4),
                'ok': bool(z >= target_center_z - 0.008)}

    def advance_to_ledge(self, max_s=6.0, speed=0.06):
        """保持 FR 抬起，低速前进到 FR 轮心越过台沿内侧。"""
        env = self.env
        b = bc.wheel_body(env, 'FR')
        x_target = self.face_x + 0.07
        x0 = float(env.data.qpos[0])
        for _ in range(int(max_s * 50)):
            if float(env.data.xpos[b][0]) >= x_target:
                break
            self.step('advance_to_ledge', omega=speed / WHEEL_R)
            if self.terminated:
                break
        return {'phase': 'advance_to_ledge',
                'fr_wheel_x': round(float(env.data.xpos[b][0]), 4),
                'x_target': round(x_target, 4),
                'base_dx': round(float(env.data.qpos[0]) - x0, 4),
                'ok': bool(float(env.data.xpos[b][0]) >= x_target - 0.01)}

    def lower_fr(self, load_thr=3.0, hold_steps=3, max_s=1.6):
        """把 FR 放回站姿目标，触地按持续载荷判定后停住。"""
        env = self.env
        start = dict(self.targets['FR'])
        gone = 0
        t_contact = None
        n = int(max_s * 50)
        for i in range(n):
            a = (i + 1) / n
            for p in ('hip', 'thigh', 'calf'):
                self.targets['FR'][p] = float(start[p] + a * (STANCE['FR'][p] - start[p]))
            self.step('lower_fr')
            if self.terminated:
                break
            load = contact_load(env, 'FR')
            if load > load_thr:
                gone += 1
                if gone >= hold_steps:
                    t_contact = float(env.t)
                    break
            else:
                gone = 0
        load = contact_load(env, 'FR')
        return {'phase': 'lower_fr', 'contact_at_t': t_contact,
                'steps': i + 1, 'load_n': round(load, 3),
                'ok': bool(t_contact is not None)}

    def hold_front(self, seconds=0.8, min_frac=0.05):
        rows = []
        for _ in range(int(seconds * 50)):
            rows.append(self.step('hold_front'))
            if self.terminated:
                break
        mean = float(np.mean([r['fr_support_load'] for r in rows])) if rows else 0.0
        tilt = max((r['tilt'] for r in rows), default=99)
        return {'phase': 'hold_front', 'fr_load_n': round(mean, 3),
                'frac': round(mean / self.W, 4),
                'tilt_max_deg': round(tilt, 3),
                'ok': bool(rows and mean >= min_frac * self.W and tilt <= 10.0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/climb/front_r1')
    ap.add_argument('--step-h', type=float, default=0.05)
    ap.add_argument('--step-x', type=float, default=1.20)
    ap.add_argument('--step-y', type=float, default=-0.115,
                    help='窄台沿横向偏置：只盖住 FR 轮迹，FL 仍走平地')
    ap.add_argument('--step-w', type=float, default=0.27)
    ap.add_argument('--soil', default='nominal', choices=['rigid', 'nominal'])
    ap.add_argument('--record', action='store_true')
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    box = make_step(out / 'step.stl', h=a.step_h, sy=a.step_w)

    spec = terrain.make_spec(kind='flat', seed=0, goal_x=3.0, name='climb_front',
                             objects=[{'mesh_file': box, 'x': a.step_x, 'y': a.step_y,
                                       'yaw_deg': 0.0}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
    env.reset(seed=0)
    rec = None
    if a.record:
        rec = v3_record.Recorder(out / 'record',
                                 {'scenario': 'climb_front', 'method': 'D1',
                                  'action': 'CLIMB_FR'}, hz=50.0)
    c = Climb(env, a.step_x, a.step_h, 0.5, record=rec)

    phases = []
    # APPROACH：直行到台面前 0.35 m
    brake_x = c.face_x - 0.35
    ok = False
    for _ in range(int(4.0 * 50)):
        if float(env.data.qpos[0]) >= brake_x:
            ok = True
            break
        c.step('approach', omega=0.25 / WHEEL_R)
        if c.terminated:
            break
    phases.append({'phase': 'approach', 'x': round(float(env.data.qpos[0]), 4),
                   'target_x': round(brake_x, 4), 'ok': bool(ok)})

    # BRAKE：速度斜坡减速到 0（不用硬刹车，避免后轮瞬间卸载）
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
    phases.append({'phase': 'brake', 'vx': round(float(env.data.qvel[0]), 4),
                   'ok': bool(stopped)})

    if not c.terminated:
        phases.append(c.shift())
    if not c.terminated:
        phases.append(c.lift_fr(a.step_h + WHEEL_R + 0.025))
    if not c.terminated:
        phases.append(c.advance_to_ledge())
    if not c.terminated:
        phases.append(c.lower_fr())
    if not c.terminated:
        phases.append(c.hold_front())

    ref = rec.close() if rec is not None else None
    checks = {p['phase']: bool(p.get('ok')) for p in phases}
    res = {'schema': 'v3-climb-front/v1', 'soil': a.soil,
           'step': {'x': a.step_x, 'h': a.step_h, 'face_x': c.face_x},
           'phases': phases, 'checks': checks,
           'terminated': c.terminated, 'errors': c.errors,
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
                      'errors': c.errors[:2],
                      'terminated': c.terminated}, ensure_ascii=False))
    return 0 if res['all_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
