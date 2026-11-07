"""V8 路径跟随：纯追踪（pure pursuit），差速轮控制。

path: 函数 x -> y_ref（窄道里路径基本沿 +x，横向偏移随 x 变化）。
"""
import numpy as np

BASE_POSE = np.array([[0, 0.85, -1.65]] * 4)


def yaw_of(q):
    w, x, y, z = q[3:7]
    return float(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


class PurePursuit:
    def __init__(self, path, lookahead=0.45, v=2.6, k_turn=2.2, turn_max=1.6, v_min=1.2):
        self.path = path; self.L = lookahead; self.v = v; self.k = k_turn; self.turn_max = turn_max; self.v_min = v_min

    def command(self, q):
        x, y = float(q[0]), float(q[1]); yaw = yaw_of(q)
        xt = x + self.L
        yt = float(self.path(xt))
        psi = np.arctan2(yt - y, self.L)
        e = (psi - yaw + np.pi) % (2 * np.pi) - np.pi
        turn = float(np.clip(self.k * e, -self.turn_max, self.turn_max))
        v = max(self.v_min, self.v * (1 - 0.5 * min(1.0, abs(e) / 0.6)))      # 大航向误差时减速
        # 轮序 FR, FL, RR, RL；右轮快 = 左转
        return np.array([v + turn, v - turn, v + turn, v - turn]), {'e_yaw': e, 'y_ref': float(self.path(x))}


def run_path(env, path, x_end, log=None, phase='FOLLOW', limit=60.0, ctrl=None, on_step=None):
    """沿路径行驶到 x_end；返回 (是否到达, 最大横向误差, 轨迹)。"""
    ctrl = ctrl or PurePursuit(path)
    t0 = env.t; traj = []; emax = 0.0
    while float(env.data.qpos[0]) < x_end and env.t - t0 < limit:
        w, info = ctrl.command(env.data.qpos)
        env.step_command(joint_targets_rad=BASE_POSE, wheel_omega_rad_s=w, wheel_mode='velocity')
        q = env.data.qpos
        err = float(q[1]) - float(path(float(q[0])))
        emax = max(emax, abs(err))
        traj.append((env.t, float(q[0]), float(q[1]), yaw_of(q), err))
        if log is not None:
            log.frame(env, 'FOLLOW', phase)
        if on_step is not None and on_step(env):
            break
    return float(env.data.qpos[0]) >= x_end, emax, np.array(traj)


def smooth_path(knots):
    """knots: [(x, y)]，相邻节点之间用 smoothstep 过渡（横移段两端切线水平，便于跟随）。"""
    kx = np.array([k[0] for k in knots], float); ky = np.array([k[1] for k in knots], float)

    def f(x):
        x = np.asarray(x, float)
        i = np.clip(np.searchsorted(kx, x) - 1, 0, len(kx) - 2)
        a = np.clip((x - kx[i]) / np.maximum(kx[i + 1] - kx[i], 1e-9), 0, 1)
        s = a * a * (3 - 2 * a)
        out = ky[i] * (1 - s) + ky[i + 1] * s
        return np.where(x <= kx[0], ky[0], np.where(x >= kx[-1], ky[-1], out))
    return f


# ---------------------------------------------------------------- 转向—直行—转向（行星车式路点执行）
def _wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def turn_to(env, yaw_t, tol_deg=1.0, max_steps=600, log=None, phase='TURN', settle=20):
    k = 0
    for k in range(max_steps):
        e = _wrap(yaw_t - yaw_of(env.data.qpos))
        if abs(np.degrees(e)) < tol_deg and k > 10:
            break
        w = float(np.clip(6.0 * e, -3.0, 3.0))
        if abs(w) < 0.6:
            w = 0.6 * np.sign(w)
        env.step_command(joint_targets_rad=BASE_POSE, wheel_omega_rad_s=np.array([w, -w, w, -w]), wheel_mode='velocity')
        if log is not None:
            log.frame(env, 'TURN', phase)
    for _ in range(settle):
        env.step_command(joint_targets_rad=BASE_POSE, wheel_brake=np.ones(4, bool))
        if log is not None:
            log.frame(env, 'TURN', phase)
    return abs(np.degrees(_wrap(yaw_t - yaw_of(env.data.qpos))))


def drive_to(env, xt, yt, v=3.0, max_steps=4000, log=None, phase='DRIVE', on_step=None, brake=True):
    """朝 (xt, yt) 直行，航向保持；沿航线方向越过目标即停。返回 (到达点误差, 是否被 on_step 中止)。"""
    q = env.data.qpos; x0, y0 = float(q[0]), float(q[1])
    ux, uy = xt - x0, yt - y0; Lseg = float(np.hypot(ux, uy)); ux, uy = ux / Lseg, uy / Lseg
    stopped = False
    for k in range(max_steps):
        q = env.data.qpos; x, y = float(q[0]), float(q[1])
        s = (x - x0) * ux + (y - y0) * uy
        if s >= Lseg - 0.01:
            break
        # 航向：指向目标点；同时纠正对航线的横向偏离
        cross = -(x - x0) * uy + (y - y0) * ux
        psi = np.arctan2(uy, ux) - np.clip(2.0 * cross, -0.35, 0.35)
        e = _wrap(psi - yaw_of(q))
        turn = float(np.clip(3.0 * e, -1.0, 1.0))
        vv = v if Lseg - s > 0.15 else max(1.2, v * (Lseg - s) / 0.15)
        env.step_command(joint_targets_rad=BASE_POSE, wheel_omega_rad_s=np.array([vv + turn, vv - turn, vv + turn, vv - turn]), wheel_mode='velocity')
        if log is not None:
            log.frame(env, 'DRIVE', phase)
        if on_step is not None and on_step(env):
            stopped = True; break
    if brake:
        for _ in range(25):
            env.step_command(joint_targets_rad=BASE_POSE, wheel_brake=np.ones(4, bool))
            if log is not None:
                log.frame(env, 'DRIVE', phase)
    q = env.data.qpos
    return float(np.hypot(float(q[0]) - xt, float(q[1]) - yt)), stopped


def run_waypoints(env, wps, log=None, phase='PATH', on_step=None, final_yaw=0.0):
    """wps: [(x, y)]（从当前位置出发）。每段：原地转向 -> 直行；最后转回 final_yaw。返回各路点误差。"""
    errs = []
    for (xt, yt) in wps:
        q = env.data.qpos
        yaw_t = float(np.arctan2(yt - float(q[1]), xt - float(q[0])))
        turn_to(env, yaw_t, log=log, phase=phase)
        err, stopped = drive_to(env, xt, yt, log=log, phase=phase, on_step=on_step)
        errs.append(err)
        if stopped:
            return errs, True
    if final_yaw is not None:
        turn_to(env, final_yaw, log=log, phase=phase)
    return errs, False
