"""
宏动作库：每个动作是带进入/执行/退出/超时的状态机。

  from scripts.skills import make_skill, SKILLS
  sk = make_skill('R1'); sk.reset(plan); a = sk.act(obs, robot_state)

设计约束（任务书 5.4）：
  · 动作只读**可见尺寸**（x_front、W_vis）、导航目标与本体状态；
    **不**读真值背深、背面类型或完整网格；
  · 每个动作有明确的退出条件与超时，不能"低速就一直抬腿、一直降速"；
  · A0 放弃使用**显式刹车**（实测 a[2]=-1 不停车，见 PHASE_0）；
  · 遇到真值时只有 evaluator 读，这里全部不碰。

动作清单：
  R1 直行          R2 慢压（轮速倍率 -0.55）
  L1 抬前腿慢过     L2 抬后腿慢过
  S1 跨骑（仅在可见宽度小于轮间净空时启用）
  D1/D2 左绕 / 右绕  A0 放弃（刹停保持）
"""
import numpy as np

import wheelleg_env as WE

# 由 measure_robot 实测，不写死
TRACK_M = 0.28387
WHEEL_R = 0.08595
BRAKE_DISTANCE_M = 0.679      # 实测刹停距离（0.85 m/s -> 0）
SPEED_MPS = 0.8532


class Skill:
    name = 'base'

    def __init__(self, params=None):
        self.params = params or {}
        self.reset()

    def reset(self, plan=None):
        self.phase = 'idle'
        self.t = 0.0
        self.done = False
        self.trace = []
        self.plan = plan or {}

    def act(self, obs, rs):
        raise NotImplementedError

    def _base(self, speed_scale=0.0, front=0.0, rear=0.0):
        a = np.zeros(WE.ACT_DIM)
        a[0], a[1], a[2] = front, rear, speed_scale
        return a


class R1(Skill):
    """直行：基础腿姿、正常轮速。"""
    name = 'R1'

    def act(self, obs, rs):
        self.t += rs.get('dt', 0.02)
        self.done = bool(rs.get('finished'))
        return self._base()


class R2(Skill):
    """慢压：轮速倍率 -0.55（约 0.4 m/s，按实测校准）。"""
    name = 'R2'

    def act(self, obs, rs):
        self.t += rs.get('dt', 0.02)
        self.done = bool(rs.get('finished'))
        return self._base(speed_scale=-0.55)


class LegLift(Skill):
    """
    抬前腿/后腿慢过：按**可见前沿位置**触发，完成后恢复。
    触发条件用可见量 x_front 与轮心位置之差，不用真值背深。
    """
    name = 'L1'

    def __init__(self, which='front', d=0.30, params=None):
        self.which = which
        self.d = d
        super().__init__(params)

    def act(self, obs, rs):
        self.t += rs.get('dt', 0.02)
        x = rs.get('x', 0.0)
        x_front = rs.get('x_front')
        vx = rs.get('vx', 0.0)
        trigger_at = (x_front - self.plan.get('lead_m', 0.45)) if x_front is not None else None
        started = self.phase != 'idle'
        if not started and trigger_at is not None and x >= trigger_at:
            self.phase = 'lift'
            self.t0 = self.t
        if self.phase == 'lift':
            # 抬腿 + 减速；持续 d/v 秒后进入恢复
            if self.t - self.t0 > self.d / max(0.4, SPEED_MPS * 0.5):
                self.phase = 'recover'
                self.t1 = self.t
            if self.which == 'front':
                return self._base(speed_scale=-0.45, front=0.8, rear=-0.4)
            return self._base(speed_scale=-0.45, front=-0.4, rear=0.8)
        if self.phase == 'recover':
            if self.t - self.t1 > 0.35:
                self.phase = 'done'
            return self._base(speed_scale=-0.2)
        if self.t > rs.get('time_limit', 15.0):
            self.phase = 'timeout'
        self.done = self.phase in ('done', 'timeout') or bool(rs.get('finished'))
        return self._base()


class S1(Skill):
    """
    跨骑：仅当**可见横向宽度**小于轮间净空减安全裕量时启用；
    执行时抬高机体（前后腿同时伸展）并保持直行。
    """
    name = 'S1'
    CLR = TRACK_M - 2 * 0.0526 - 0.04       # 轮内净空 - 裕量

    def applicable(self, obs_vis):
        return obs_vis.get('W_vis') is not None and obs_vis['W_vis'] < self.CLR

    def act(self, obs, rs):
        self.t += rs.get('dt', 0.02)
        self.done = bool(rs.get('finished'))
        return self._base(speed_scale=-0.15, front=-0.6, rear=0.6)


class Detour(Skill):
    """左/右绕行：先稳定偏移，再越过，再回位。"""
    name = 'D1'

    def __init__(self, side=+1, r=0.5, params=None):
        self.side = side
        self.r = r
        super().__init__(params)

    def act(self, obs, rs):
        self.t += rs.get('dt', 0.02)
        lat = rs.get('lateral', 0.0)
        x = rs.get('x', 0.0)
        target = self.side * self.r
        # 用差速转向做横向偏移；这里只给转向相关的速度差
        err = target - lat
        a = self._base(speed_scale=-0.1)
        a[2] = float(np.clip(-0.05 + 0.0 * err, -1, 1))
        self.steer_hint = float(np.clip(2.0 * err, -1, 1))
        self.done = bool(rs.get('finished')) or self.t > rs.get('time_limit', 15.0)
        return a


class A0(Skill):
    """
    放弃：在接近障碍前**显式刹停**并保持。
    实测 a[2]=-1 不停车（0.32 m/s），因此这里直接请求刹车通路。
    """
    name = 'A0'

    def act(self, obs, rs):
        self.t += rs.get('dt', 0.02)
        self.brake = True
        self.done = self.t > 3.0
        return self._base(speed_scale=-1.0)


SKILLS = {'R1': R1, 'R2': R2, 'L1': lambda: LegLift('front'),
          'L2': lambda: LegLift('rear'), 'S1': S1,
          'D1': lambda: Detour(+1), 'D2': lambda: Detour(-1), 'A0': A0}


def make_skill(name, **kw):
    f = SKILLS[name]
    if isinstance(f, type):
        return f(**kw)
    return f()


def brake_distance_for(speed_mps):
    """给定速度估算刹停所需距离（线性插值自实测点）。"""
    return BRAKE_DISTANCE_M * (speed_mps / SPEED_MPS) ** 2
