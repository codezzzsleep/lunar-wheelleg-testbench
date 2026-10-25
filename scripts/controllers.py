"""
考生控制器。

hold  : 固定站姿 + 轮速伺服（原来的四轮小车）
step  : 带腿的状态机 —— 被挡住时抬前轮上台、再抬后轮跟上去

为什么要做 step：hold 从不使用腿自由度，本质是四轮小车，
所以形状细节（凹槽、斜面、可踩踏凸台）在这套考生下天然无从体现。
"""
import numpy as np

LEGS = ['FR', 'FL', 'RR', 'RL']
FRONT = {'FR', 'FL'}
REAR = {'RR', 'RL'}

BASE = {'hip': 0.0, 'thigh': 0.85, 'calf': -1.65}   # 站姿，机身 0.384 m
REACH = {'hip': 0.0, 'thigh': 0.35, 'calf': -1.85}  # 前伸抬高：轮子相对机体上抬 8 cm
CROUCH = {'hip': 0.0, 'thigh': 1.05, 'calf': -1.05} # 收腿：机身压低、轮子内收


def _lerp(a, b, t):
    return {k: a[k] + (b[k] - a[k]) * t for k in a}


class HoldController:
    """基线：四个腿都锁在固定站姿。"""
    name = 'hold'

    def __init__(self, stance=None):
        self.stance = stance or BASE

    def targets(self, t, qpos, qvel, blocked):
        return {leg: self.stance for leg in LEGS}

    def note_outcome(self, outcome):
        pass


class StepController:
    """
    带腿的"抬头迈步"状态机。

    被挡住时执行一次 maneuver：
      前腿 -> REACH  （腿缩短，前轮相对机体上抬 8 cm 并前伸）
      后腿 -> CROUCH （腿伸长，把机身顶高、机头抬起）
    保持约 0.9 s 让前轮落上台面，然后回站姿继续驱动。
    可重复多次；参数全部由考场侧实验标定，不使用任何障碍物先验信息。

    为什么不是"只抬前腿"：前轮离地后机体只剩后轮支撑，会直接前倾砸到障碍物上
    （实测前腿单独抬时 x=0.88 就翻了）。后腿同时伸长才能把机头抬起来。
    """
    name = 'step'

    def __init__(self, stance=None, dwell=0.05, hold=0.80, pull=0.05,
                 slow=0.12, max_cycles=4, arm_after=3.0):
        self.stance = stance or BASE
        self.dwell = dwell
        self.hold_s = hold
        self.pull = pull
        self.slow = slow
        self.max_cycles = max_cycles
        self.arm_after = arm_after
        self.phase = 'drive'
        self.t_phase = 0.0
        self.slow_for = 0.0
        self.cycles = 0
        self._prev_t = None

    def _enter(self, phase):
        self.phase = phase
        self.t_phase = 0.0

    def targets(self, t, qpos, qvel, blocked=False):
        dt = 0.0 if self._prev_t is None else max(0.0, t - self._prev_t)
        self._prev_t = t
        self.t_phase += dt
        vx = float(qvel[0])

        if self.phase == 'drive':
            if t < self.arm_after:
                self.slow_for = 0.0
            else:
                self.slow_for = self.slow_for + dt if vx < self.slow else 0.0
            if self.slow_for > 0.35 and self.cycles < self.max_cycles:
                self.cycles += 1
                self.slow_for = 0.0
                self._enter('maneuver')
        elif self.phase == 'maneuver':
            if self.t_phase > self.dwell + self.hold_s + self.pull:
                self._enter('drive')
                self.slow_for = 0.0

        if self.phase != 'maneuver':
            return {leg: self.stance for leg in LEGS}

        # 三段：抬到位 -> 保持 -> 回站姿
        tp = self.t_phase
        if tp < self.dwell:
            k = tp / self.dwell
        elif tp < self.dwell + self.hold_s:
            k = 1.0
        else:
            k = max(0.0, 1.0 - (tp - self.dwell - self.hold_s) / self.pull)
        out = {}
        for leg in LEGS:
            goal = REACH if leg in FRONT else CROUCH
            out[leg] = _lerp(self.stance, goal, k)
        return out

    def note_outcome(self, outcome):
        pass


def make(name, stance=None):
    if name == 'hold':
        return HoldController(stance)
    if name == 'step':
        return StepController(stance)
    if name == 'adapt':
        return AdaptController(stance)
    raise ValueError(name)


# ---------------------------------------------------------------- 闭环考生

# 抬腿高度分级：thigh 越小、calf 越负 -> 轮子相对机体抬得越高
LIFT_LEVELS = [
    {'hip': 0.0, 'thigh': 0.62, 'calf': -1.72},
    {'hip': 0.0, 'thigh': 0.48, 'calf': -1.79},
    {'hip': 0.0, 'thigh': 0.36, 'calf': -1.85},
    {'hip': 0.0, 'thigh': 0.28, 'calf': -1.92},
]


class AdaptController:
    """
    闭环考生：**用本体感觉判断挡住自己的是什么**，再决定动作。

    只用机器人自己能测到的东西（逐项对应代码）：
      · 机体前进速度  qvel[0]
      · 机体倾角      由 qpos 四元数算出
    注意：**本实现不读轮子关节速度**。判据是"机体速度低不低"，不是"轮子转没转"。
    不使用任何障碍物的真值（位置、高度、形状）。

    决策：
      · 机体几乎不动 且 机体几乎不抬头  -> 竖直面 / 台阶 -> 抬腿
      · 机体几乎不动 但 机体已经抬头     -> 已经在爬坡      -> 只加大轮上力矩，不抬腿
      · 抬腿后仍然不动                     -> 默认**不**升级（escalate=False）。
        实测逐级加高会把机器人送上障碍物顶部、带约 50° 仰角从另一侧翻下去
        （方块 h130：x=2.55 处翻车）。escalate=True 只作为保留的实验开关。

    与 StepController 的区别：Step 是固定一次动作；Adapt 会**根据测到的状态选择动作并升级**，
    这正是"形状能不能影响通行"这个问题的前提。
    """

    name = 'adapt'

    def __init__(self, stance=None, arm_after=3.0,
                 block_speed=0.15, block_time=0.15,
                 dwell=0.05, hold=0.70, pull=0.10,
                 max_attempts=5, pitch_climbing=40.0, escalate=False):
        self.stance = stance or BASE
        self.arm_after = arm_after
        self.block_speed = block_speed
        self.block_time = block_time
        self.dwell, self.hold_s, self.pull = dwell, hold, pull
        self.max_attempts = max_attempts
        self.escalate = escalate
        self.pitch_climbing = pitch_climbing     # 超过这个倾角就认为已经在往上爬

        self.phase = 'drive'
        self.t_phase = 0.0
        self.blocked_for = 0.0
        self.level = 0
        self.attempts = 0
        self.last_action = None
        self._prev_t = None
        self.boosting = 0.0        # 轮上力矩放大剩余时间
        self.settle = 0.0          # 攀爬成功后短暂降速，防止在障碍物顶上翻下去
        self._x_start = 0.0
        self.n_lift = 0
        self.n_boost = 0
        self.n_climbed = 0

    def _enter(self, phase):
        self.phase = phase
        self.t_phase = 0.0

    @staticmethod
    def _tilt_deg(qpos):
        w, x, y, z = qpos[3], qpos[4], qpos[5], qpos[6]
        up = 1.0 - 2.0 * (x * x + y * y)
        return float(np.degrees(np.arccos(np.clip(up, -1.0, 1.0))))

    def targets(self, t, qpos, qvel, blocked_flag):
        dt = 0.0 if self._prev_t is None else max(0.0, t - self._prev_t)
        self._prev_t = t
        self.t_phase += dt
        self.boosting = max(0.0, self.boosting - dt)
        self.settle = max(0.0, self.settle - dt)
        vx = float(qvel[0])
        tilt = self._tilt_deg(qpos)

        if self.phase == 'drive':
            if t < self.arm_after:
                self.blocked_for = 0.0
            else:
                stuck = vx < self.block_speed
                self.blocked_for = self.blocked_for + dt if stuck else 0.0

            if self.blocked_for > self.block_time and self.attempts < self.max_attempts:
                self.attempts += 1
                self.blocked_for = 0.0
                # ---- 决策：是在爬坡，还是撞上了竖直面？----
                if tilt > self.pitch_climbing:
                    self.last_action = 'boost'        # 已在爬升，别抬腿，给足力矩
                    self.boosting = 0.8
                    self.n_boost += 1
                else:
                    self.last_action = f'lift_L{self.level}'
                    self.n_lift += 1
                    self._x_start = float(qpos[0])
                    self._enter('maneuver')
        elif self.phase == 'maneuver':
            if self.t_phase > self.dwell + self.hold_s + self.pull:
                climbed = float(qpos[0]) - self._x_start
                if climbed > 0.15:
                    # 抬腿奏效了：复位级别，并降速一小段把姿态稳下来。
                    # 不做这一步会在障碍物顶上带着 50 度仰角全速冲出去然后翻车（实测 x=2.55）。
                    self.level = 0
                    self.settle = 0.6
                    self.last_action = 'climbed'
                    self.n_climbed += 1
                elif self.escalate:
                    self.level = min(self.level + 1, len(LIFT_LEVELS) - 1)
                self._enter('drive')
                self.blocked_for = 0.0

        if self.phase != 'maneuver':
            return {leg: self.stance for leg in LEGS}

        tp = self.t_phase
        if tp < self.dwell:
            k = tp / self.dwell
        elif tp < self.dwell + self.hold_s:
            k = 1.0
        else:
            k = max(0.0, 1.0 - (tp - self.dwell - self.hold_s) / self.pull)
        reach = LIFT_LEVELS[self.level]
        out = {}
        for leg in LEGS:
            goal = reach if leg in FRONT else CROUCH
            out[leg] = _lerp(self.stance, goal, k)
        return out

    def wheel_boost(self):
        """轮上力矩倍率：判定"已在爬坡"时加大；刚爬上去时收敛。"""
        if self.settle > 0:
            return 0.35
        return 1.25 if self.boosting > 0 else 1.0

    def stats(self):
        return {'lift': self.n_lift, 'boost': self.n_boost, 'climbed': self.n_climbed}

    def note_outcome(self, outcome):
        pass
