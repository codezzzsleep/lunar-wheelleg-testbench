"""工作包 B：以重心与真实接触为依据的稳定抬轮基础周期（平地）。

阶段顺序（SPEC RECOVERY-002 B2）：
  STAND -> SHIFT_SUPPORT -> UNLOAD/LIFT -> HOLD -> LOWER_UNTIL_CONTACT
        -> LOAD_TRANSFER -> RETURN_BODY -> DONE

关键约束：
  * 不用目标角度或轮心世界 z 判断成功；用整机重心、支撑多边形裕度、
    真实轮-地法向载荷与轮底对地间隙；
  * 支撑转移用逐腿 3 关节雅可比（阻尼最小二乘）让支撑轮基本不动、机身/重心横移，
    不给三个支撑髋同一个经验偏置；
  * 每个阶段有进入条件、持续判据、最大时间和失败原因；失败立即结束，不继续后续阶段；
  * 首轮抬轮 2–4 cm，抬/落各约 1–2 s，HOLD ≥1 s，触地按持续载荷 + 滞回判定。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_basic_cycle.py --soil rigid \
      --out runs/v3/basic_cycle/rigid_r1
"""
import argparse
import hashlib
import json
import math
import pathlib
import sys

import numpy as np
import mujoco

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import terrain            # noqa: E402
import v7_soil            # noqa: E402
import v3_record          # noqa: E402
import wheelleg_env       # noqa: E402

LEG = ('FR', 'FL', 'RR', 'RL')
SUPPORT3 = ('FL', 'RR', 'RL')
STANCE = {'hip': 0.0, 'thigh': 0.85, 'calf': -1.65}
G_MOON = 1.62
WHEEL_R = wheelleg_env.WHEEL_R


# ---------------------------------------------------------------- 测量
def base_id(env):
    return mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')


def wheel_body(env, leg):
    return mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')


def com(env):
    return np.asarray(env.data.subtree_com[base_id(env)], dtype=float).copy()


def total_weight(env):
    return float(mujoco.mj_getTotalmass(env.model)) * G_MOON


def attitude(env):
    w, x, y, z = (float(v) for v in env.data.qpos[3:7])
    roll = math.degrees(math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))
    return roll, pitch


def wheel_ground(env, leg):
    """轮-地接触：只统计地面/地形体，排除自碰撞与岩石。"""
    m, d = env.model, env.data
    b = wheel_body(env, leg)
    pts, loads = [], []
    for i in range(int(d.ncon)):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if b not in (b1, b2):
            continue
        other = b2 if b1 == b else b1
        if other not in (0, int(getattr(env, 'terrain_body_id', -1))):
            continue
        f = np.zeros(6)
        mujoco.mj_contactForce(m, d, i, f)
        loads.append(abs(float(f[0])))
        pts.append(np.asarray(c.pos, dtype=float).copy())
    return {'load': float(sum(loads)), 'points': pts}


def wheel_clearance(env, leg):
    b = wheel_body(env, leg)
    x, y, z = (float(v) for v in env.data.xpos[b])
    gz = float(env._ground_height(x, y)) if hasattr(env, '_ground_height') else 0.0
    return z - WHEEL_R - gz


def hull_ccw(points):
    pts = sorted(set((round(float(p[0]), 6), round(float(p[1]), 6)) for p in points))
    if len(pts) <= 2:
        return [np.asarray(p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 1e-12:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 1e-12:
            upper.pop()
        upper.append(p)
    return [np.asarray(p) for p in (lower[:-1] + upper[:-1])]


def polygon_margin(points_xy, p_xy):
    """CCW 凸多边形内的最小有符号距离（米）；在外部为负。"""
    poly = hull_ccw(points_xy)
    if len(poly) < 3:
        return -1.0
    best = 1e9
    for i in range(len(poly)):
        a = poly[i]
        b = poly[(i + 1) % len(poly)]
        e = b - a
        n = np.array([-e[1], e[0]], dtype=float)
        ln = float(np.linalg.norm(n))
        if ln < 1e-12:
            continue
        n /= ln
        best = min(best, float(np.dot(np.asarray(p_xy) - a, n)))
    return best


def nearest_edge(points_xy, p_xy):
    """返回 (有符号距离, 指向多边形内部的单位法向)。"""
    poly = hull_ccw(points_xy)
    if len(poly) < 3:
        return -1.0, np.array([0.0, 1.0])
    best_d, best_n = 1e9, np.array([0.0, 1.0])
    for i in range(len(poly)):
        a = poly[i]
        b = poly[(i + 1) % len(poly)]
        e = b - a
        n = np.array([-e[1], e[0]], dtype=float)
        ln = float(np.linalg.norm(n))
        if ln < 1e-12:
            continue
        n /= ln
        d = float(np.dot(np.asarray(p_xy) - a, n))
        if d < best_d:
            best_d, best_n = d, n
    return best_d, best_n


def support_state(env, support=SUPPORT3, swing='FR'):
    loads = {leg: wheel_ground(env, leg) for leg in LEG}
    pts = []
    for leg in support:
        pts += [p[:2] for p in loads[leg]['points']]
    c = com(env)
    margin = polygon_margin(pts, c[:2]) if len(pts) >= 3 else None
    return {
        'com': [round(float(v), 5) for v in c],
        'margin_m': None if margin is None else round(float(margin), 5),
        'loads_n': {leg: round(loads[leg]['load'], 3) for leg in LEG},
        'points': [[round(float(p[0]), 5), round(float(p[1]), 5)]
                   for leg in support for p in loads[leg]['points']],
        'clearance_m': {leg: round(wheel_clearance(env, leg), 5) for leg in LEG},
    }


def leg_jac(env, leg):
    m, d = env.model, env.data
    b = wheel_body(env, leg)
    jacp = np.zeros((3, m.nv), dtype=float)
    jacr = np.zeros((3, m.nv), dtype=float)
    mujoco.mj_jac(m, d, jacp, jacr, np.asarray(d.xpos[b], dtype=float), b)
    cols = [env.J[f'{leg}_{p}_joint']['vadr'] for p in ('hip', 'thigh', 'calf')]
    return jacp[:, cols]


def damped_ls(J, dp, lam=1e-4):
    A = J @ J.T + lam * np.eye(3)
    return J.T @ np.linalg.solve(A, dp)


def clip_targets(t, lo=-1.0, hi=1.0):
    return {leg: {p: float(np.clip(t[leg][p], lo, hi)) for p in ('hip', 'thigh', 'calf')}
            for leg in LEG}


# ---------------------------------------------------------------- 主流程
class Cycle:
    def __init__(self, env, swing='FR', record=None):
        self.env = env
        self.swing = swing
        self.support = [l for l in LEG if l != swing]
        self.W = total_weight(env)
        self.targets = {leg: dict(STANCE) for leg in LEG}
        self.rec = record
        self.frames = []
        self.phases = []
        self.errors = []
        self.k = 0
        self.terminated = False

    # ---- 基础推进
    def step(self, phase, wheel_mode='coast'):
        env = self.env
        ctrl = env.step_command(joint_targets_rad=self.targets, wheel_mode=wheel_mode)
        self.k += 1
        st = support_state(env, self.support, self.swing)
        roll, pitch = attitude(env)
        qv = np.asarray(env.data.qvel, dtype=float)
        jt = getattr(env, '_last_joint_targets', None)
        track = 0.0
        if jt is not None:
            meas = np.array([[env.data.qpos[env.J[f'{leg}_{pp}_joint']['qadr']]
                              for pp in ('hip', 'thigh', 'calf')] for leg in LEG])
            track = float(np.max(np.abs(meas - np.asarray(jt))))
        frame = {'k': self.k, 't': round(float(env.t), 5), 'phase': phase,
                 'com': st['com'], 'margin': st['margin_m'],
                 'loads': st['loads_n'], 'clearance': st['clearance_m'],
                 'roll': round(roll, 3), 'pitch': round(pitch, 3),
                 'tilt': round(float(env._tilt()), 3),
                 'speed': round(float(np.linalg.norm(qv[:2])), 4),
                 'ang_speed': round(float(np.linalg.norm(qv[3:6])), 4),
                 'track_err': round(track, 4),
                 'targets': {leg: {p: round(self.targets[leg][p], 4)
                                   for p in ('hip', 'thigh', 'calf')} for leg in LEG}}
        self.frames.append(frame)
        if self.rec is not None:
            self.rec.add(v3_record.frame_from_env(
                env, None, np.zeros(3), self.k, env.t,
                extra={'skill_phase': phase}))
        if env.terminated or env.truncated:
            self.terminated = True
            self.errors.append({'phase': phase, 'reason': env.last_termination.get('reason'),
                                't': round(float(env.t), 3)})
        if float(env._tilt()) > 20.0 and not self.terminated:
            self.terminated = True
            self.errors.append({'phase': phase, 'reason': 'tilt>20deg',
                                'tilt': round(float(env._tilt()), 2)})
        return frame, ctrl

    # ---- 支撑转移：沿最近支撑边的内法向，分轮次把目标斜坡过去（不积分风up）
    def shift_support(self, phase, seconds, target_margin=0.012,
                      max_dp_m=0.03, max_dq=0.08, ramp_s=0.6):
        env = self.env
        budget = int(round(seconds * 50))
        used = 0
        best = None
        for _ in range(3):
            st = support_state(env, self.support, self.swing)
            pts = [np.asarray(p[:2]) for leg in self.support
                   for p in wheel_ground(env, leg)['points']]
            if len(pts) < 3 or st['margin_m'] is None:
                break
            margin, inward = nearest_edge(pts, np.asarray(st['com'][:2]))
            best = margin if best is None else max(best, margin)
            if margin >= target_margin or used >= budget:
                break
            dp = np.zeros(3)
            dp[:2] = inward * float(np.clip(target_margin - margin + 0.004,
                                            -max_dp_m, max_dp_m))
            start = {leg: dict(self.targets[leg]) for leg in LEG}
            goal = {leg: dict(self.targets[leg]) for leg in LEG}
            for leg in self.support:
                J = leg_jac(env, leg)
                dq = np.clip(damped_ls(J, -dp), -max_dq, max_dq)
                for p, v in zip(('hip', 'thigh', 'calf'), dq):
                    goal[leg][p] = float(np.clip(start[leg][p] + v, -2.5, 2.5))
            n = max(1, int(round(ramp_s * 50)))
            for i in range(n):
                a = (i + 1) / n
                for leg in LEG:
                    for p in ('hip', 'thigh', 'calf'):
                        self.targets[leg][p] = float(
                            start[leg][p] + a * (goal[leg][p] - start[leg][p]))
                self.step(phase)
                used += 1
                if self.terminated or used >= budget:
                    break
            if self.terminated:
                break
        st = support_state(env, self.support, self.swing)
        return {'phase': phase, 'margin_m': st['margin_m'],
                'best_margin_m': best, 'com': st['com'], 'steps': used,
                'ok': bool(st['margin_m'] is not None
                           and st['margin_m'] >= target_margin)}

    # ---- 单腿竖直抬轮：J dq = +dz，分轮次斜坡到目标间隙
    def lift_swing(self, phase, seconds, dz_target=0.03, max_dq=0.30, ramp_s=1.2):
        env = self.env
        budget = int(round(seconds * 50))
        used = 0
        z0 = wheel_clearance(env, self.swing)
        for _ in range(4):
            need = dz_target - (wheel_clearance(env, self.swing) - z0)
            if need <= 0.003 or used >= budget:
                break
            dp = np.zeros(3)
            dp[2] = float(np.clip(need, -0.05, 0.05))
            J = leg_jac(env, self.swing)
            dq = np.clip(damped_ls(J, dp), -max_dq, max_dq)
            start = dict(self.targets[self.swing])
            goal = {p: float(np.clip(start[p] + float(v), -2.5, 2.5))
                    for p, v in zip(('hip', 'thigh', 'calf'), dq)}
            n = max(1, int(round(ramp_s * 50)))
            for i in range(n):
                a = (i + 1) / n
                for p in ('hip', 'thigh', 'calf'):
                    self.targets[self.swing][p] = float(
                        start[p] + a * (goal[p] - start[p]))
                self.step(phase)
                used += 1
                if self.terminated or used >= budget:
                    break
            if self.terminated:
                break
        clear = wheel_clearance(env, self.swing)
        return {'phase': phase, 'dz_m': round(float(clear - z0), 4),
                'clearance_m': round(float(clear), 4), 'steps': used,
                'ok': bool(clear - z0 >= 0.02)}

    # ---- 保持：目标不变，检查姿态/载荷/裕度
    def hold(self, phase, seconds):
        n = int(round(seconds * 50))
        rows = []
        for _ in range(n):
            frame, _ = self.step(phase)
            rows.append(frame)
            if self.terminated:
                break
        loads = np.array([[r['loads'][l] for l in LEG] for r in rows], dtype=float)
        mean = loads.mean(axis=0) if len(loads) else np.zeros(4)
        W = self.W
        tilt = max((r['tilt'] for r in rows), default=99.0)
        margin = min((r['margin'] for r in rows if r['margin'] is not None), default=None)
        swing_load = float(np.mean([r['loads'][self.swing] for r in rows])) if rows else 99.0
        sup_loads = {l: float(np.mean([r['loads'][l] for r in rows])) for l in self.support} \
            if rows else {}
        horiz = max((abs(float(self.env.data.qvel[0])) for _ in [0]), default=0.0)
        speed = max((r['speed'] for r in rows), default=99.0)
        ang = max((r['ang_speed'] for r in rows), default=99.0)
        track = max((r['track_err'] for r in rows), default=99.0)
        ok = bool(rows and not self.terminated and tilt <= 5.0
                  and speed <= 0.03 and ang <= 0.1 and track <= 0.15
                  and swing_load <= 0.02 * W
                  and all(v >= 0.05 * W for v in sup_loads.values())
                  and margin is not None and margin >= 0.010)
        return {'phase': phase, 'seconds': seconds, 'tilt_max_deg': round(tilt, 3),
                'speed_max_mps': round(float(speed), 4),
                'ang_speed_max_radps': round(float(ang), 4),
                'track_err_max_rad': round(float(track), 4),
                'margin_min_m': None if margin is None else round(float(margin), 5),
                'swing_load_n': round(swing_load, 3),
                'swing_load_frac': round(swing_load / W, 4),
                'support_loads_n': {k: round(v, 3) for k, v in sup_loads.items()},
                'support_frac': {k: round(v / W, 4) for k, v in sup_loads.items()},
                'ok': ok}

    # ---- 落轮：缓慢放低，持续载荷 + 滞回后停住
    def lower_until_contact(self, phase, seconds, load_thr=5.0, hold_steps=3):
        env = self.env
        n = int(round(seconds * 50))
        start = {leg: dict(self.targets[leg]) for leg in LEG}
        gone = 0
        contact_t = None
        for i in range(n):
            a = (i + 1) / n
            for leg in LEG:
                for p in ('hip', 'thigh', 'calf'):
                    self.targets[leg][p] = float(start[leg][p]
                                                 + a * (STANCE[p] - start[leg][p]))
            frame, _ = self.step(phase)
            if self.terminated:
                break
            load = wheel_ground(env, self.swing)['load']
            if load > load_thr:
                gone += 1
                if gone >= hold_steps:
                    contact_t = float(env.t)
                    break
            else:
                gone = 0
        load = wheel_ground(env, self.swing)['load']
        return {'phase': phase, 'contact_at_t': contact_t,
                'steps_to_contact': i + 1,
                'swing_load_n': round(load, 3),
                'ok': bool(contact_t is not None)}

    # ---- 承载与回位
    def load_transfer(self, phase, seconds, min_frac=0.05):
        n = int(round(seconds * 50))
        rows = []
        for _ in range(n):
            frame, _ = self.step(phase)
            rows.append(frame)
            if self.terminated:
                break
        mean = float(np.mean([r['loads'][self.swing] for r in rows])) if rows else 0.0
        sustained = sum(1 for r in rows if r['loads'][self.swing] > 1.0) / 50.0
        return {'phase': phase, 'swing_load_n': round(mean, 3),
                'frac': round(mean / self.W, 4),
                'contact_sustained_s': round(sustained, 3),
                'ok': bool(rows and mean >= min_frac * self.W and sustained >= 0.2)}

    def return_body(self, phase, seconds):
        n = int(round(seconds * 50))
        start = {leg: dict(self.targets[leg]) for leg in LEG}
        for i in range(n):
            a = (i + 1) / n
            for leg in LEG:
                for p in ('hip', 'thigh', 'calf'):
                    self.targets[leg][p] = float(start[leg][p]
                                                 + a * (STANCE[p] - start[leg][p]))
            self.step(phase)
            if self.terminated:
                break
        return {'phase': phase, 'ok': not self.terminated}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--soil', default='rigid', choices=['rigid', 'nominal'])
    ap.add_argument('--swing', default='FR')
    ap.add_argument('--out', default='runs/v3/basic_cycle/rigid_r1')
    ap.add_argument('--record', action='store_true')
    ap.add_argument('--hold', type=float, default=1.2)
    ap.add_argument('--cycles', type=int, default=1)
    ap.add_argument('--init-seed', type=int, default=0,
                    help='初态扰动种子；实际 qpos/qvel 哈希写入结果，seed 名不等于初态相同')
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=5.0,
                             name=f'basic_cycle_{a.soil}')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=15.0 + 8.0 * a.cycles)
    env.reset(seed=a.init_seed)
    q0 = np.asarray(env.data.qpos, dtype=np.float64).copy()
    v0 = np.asarray(env.data.qvel, dtype=np.float64).copy()
    init = {'seed': int(a.init_seed),
            'qpos': [round(float(x), 6) for x in q0],
            'qvel': [round(float(x), 6) for x in v0],
            'qpos_sha256': hashlib.sha256(q0.tobytes()).hexdigest(),
            'qvel_sha256': hashlib.sha256(v0.tobytes()).hexdigest(),
            'perturbation': {'lateral_m': env.init_perturbation['lateral'],
                             'yaw_rad': env.init_perturbation['yaw']}}
    rec = None
    if a.record:
        rec = v3_record.Recorder(out / 'record',
                                 {'scenario': f'basic_cycle_{a.soil}',
                                  'method': 'B', 'action': f'LIFT_{a.swing}'}, hz=50.0)
    cyc = Cycle(env, swing=a.swing, record=rec)

    def one_cycle():
        results = []
        results.append({'phase': 'stand', **cyc.hold('stand', 0.8)})
        if not results[-1]['ok']:
            results[-1]['ok'] = results[-1]['tilt_max_deg'] <= 5.0
        if not cyc.terminated:
            results.append(cyc.shift_support('shift_support', 3.0))
        if not cyc.terminated:
            results.append(cyc.lift_swing('small_lift', 1.6, dz_target=0.03))
        if not cyc.terminated:
            results.append(cyc.hold('hold', a.hold))
        if not cyc.terminated:
            results.append(cyc.lower_until_contact('lower_until_contact', 2.0))
        if not cyc.terminated:
            results.append(cyc.load_transfer('load_transfer', 0.4))
        if not cyc.terminated:
            results.append(cyc.return_body('return_body', 1.2))
        return results

    cycles = []
    for c in range(a.cycles):
        rs = one_cycle()
        cycles.append({'cycle': c, 'phases': rs,
                       'terminated': cyc.terminated,
                       'errors': list(cyc.errors)})
        if cyc.terminated:
            break

    ref = rec.close() if rec is not None else None
    checks = {f'c{cy["cycle"]}_{r["phase"]}': bool(r.get('ok'))
              for cy in cycles for r in cy['phases']}
    all_ok = all(checks.values()) and not cyc.terminated
    res = {'schema': 'v3-basic-cycle/v1',
           'env': 'flat', 'soil': a.soil, 'swing': a.swing,
           'init': init,
           'cycles_requested': a.cycles, 'cycles_completed': len(cycles),
           'total_mass_kg': round(float(mujoco.mj_getTotalmass(env.model)), 4),
           'weight_n': round(cyc.W, 3),
           'cycles': cycles, 'checks': checks,
           'terminated': cyc.terminated, 'errors': cyc.errors,
           'all_ok': bool(all_ok), 'trajectory_ref': ref,
           'thresholds': {'hold_s': a.hold, 'lift_m': 0.02,
                          'margin_m': 0.010, 'swing_load_frac': 0.02,
                          'support_frac': 0.05, 'tilt_deg': 5.0,
                          'speed_mps': 0.03, 'ang_speed_radps': 0.1,
                          'track_err_rad': 0.15,
                          'contact_load_n': 5.0, 'contact_sustained_s': 0.2}}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    np.savez_compressed(out / 'frames.npz',
                        t=np.array([f['t'] for f in cyc.frames]),
                        phase=np.array([f['phase'] for f in cyc.frames]),
                        com=np.array([f['com'] for f in cyc.frames]),
                        margin=np.array([np.nan if f['margin'] is None else f['margin']
                                         for f in cyc.frames]),
                        loads=np.array([[f['loads'][l] for l in LEG] for f in cyc.frames]),
                        tilt=np.array([f['tilt'] for f in cyc.frames]))
    last = cycles[-1]['phases'] if cycles else []
    print(json.dumps({'all_ok': res['all_ok'], 'cycles': len(cycles),
                      'checks': checks,
                      'terminated': cyc.terminated, 'errors': cyc.errors[:2],
                      'dz': [r.get('dz_m') for r in last if r['phase'] == 'small_lift']},
                     ensure_ascii=False))
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
