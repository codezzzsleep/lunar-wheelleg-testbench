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
    raise ValueError(name)
