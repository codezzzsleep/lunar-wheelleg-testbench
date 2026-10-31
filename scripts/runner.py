"""
统一动作执行器：Gate P、候选预演、真值执行共用同一套行为。

  from runner import EpisodeRunner
  r = EpisodeRunner(env, 'L1', visible={'x_front':1.64,'W_vis':0.57}, params={'lead_m':0.45})
  out = r.run()

为什么需要它（复核意见）：
  · 旧代码里 Gate P 用**常数动作**、闭环用**状态机**，名字相同但行为不同；
  · `L1/L2` 依赖 `plan_visible`，但预演时没人注入 -> 永远停在 idle，与 R1 无法区分；
  · `A0` 设了 `brake=True`，但执行器仍调用 `env.step(a)` -> 根本没刹车。

本执行器负责：
  1. 把可见量注入环境（`env.plan_visible`），让动作能真正触发；
  2. 读取 `skill.brake` 并走**显式刹车** `env.brake_step()`；
  3. 记录**动作是否实际触发**（状态机相位变化、触发时刻、动作指纹）；
  4. 终止判据只认环境的 `terminated/truncated`，外加"驶出有效地形"这一失败。
"""
import hashlib
import numpy as np

import wheelleg_env as WE

FIELD_X_MAX = 3.95          # 地形覆盖 [-4,4]，留 5 cm 余量


def action_fingerprint(actions):
    a = np.asarray(actions, dtype=np.float64)
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


class EpisodeRunner:
    def __init__(self, env, skill, visible=None, params=None, max_steps=2000, seed=0,
                 record_trajectory=False):
        self.env = env
        self.skill = skill if not isinstance(skill, str) else __import__('skills').make_skill(skill)
        self.visible = visible or {}
        self.max_steps = max_steps
        env.plan_visible = dict(self.visible)      # 关键：动作需要它才能触发
        # 动作自己的参数也拿到公开可见量（Detour 需要 W_vis 计算绕行目标）
        for k in ('W_vis', 'H_vis', 'x_front'):
            if k in self.visible:
                self.skill.params.setdefault(k, self.visible[k])
        env.nav_target_y = env.channel_center      # 每次 reset 清空导航横向目标
        self.seed = seed
        self.record_trajectory = bool(record_trajectory)
        self.trajectory = []
        self.initial_full_hash = None
        self.skill.reset(params or {})

    def run_from_state(self, snapshot, mode='same_scene'):
        """
        从给定状态**继续**执行：不 reset，保留观察移动的时间与内部状态。

        snapshot 至少包含 qpos/qvel；可选 time。返回结构与 run() 一致，
        额外带 continuing_from / t_start，便于核对"没有偷偷 reset"。
        """
        env, sk = self.env, self.skill
        # 完整状态恢复：走 env.restore_state（含 mj_getState 全量物理状态、
        # ctrl/外力/计数/导航/土壤），不是只设 qpos/qvel
        if snapshot.get('schema') == 'env-state/v1':
            info = env.restore_state(snapshot, mode=mode)
        else:
            raise ValueError('run_from_state 需要 env-state/v1 完整快照 '
                             '（位姿/速度续接请用 env.restore_state 的旧格式适配器）')
        if getattr(env, 'plan_visible', None) is None:
            env.plan_visible = dict(self.visible)
        obs = env._obs() if hasattr(env, '_obs') else None
        t_start = float(env.t)
        self._restored = info
        self._capture_initial()
        out = self._loop(obs, t_start)
        out['continuing_from'] = 'snapshot'
        out['state_mode'] = mode
        out['restore_info'] = info
        out['t_start'] = round(t_start, 4)
        return out

    def run(self):
        env, sk = self.env, self.skill
        obs, _ = env.reset(seed=self.seed)
        self._capture_initial()
        return self._loop(obs, 0.0)

    def run_current(self):
        """从**当前环境状态**继续跑，不 reset、不恢复状态。

        与 run() 共用 _loop()，因此成功/倾覆/出界/超时/制动规则完全一致；
        用于"同一环境实例内直接继续"，与 restore_state 后的继续做逐帧对照。
        """
        env = self.env
        obs = None
        try:
            obs = env.observation()
        except Exception:
            obs = None
        self._capture_initial()
        return self._loop(obs, float(getattr(env, 't', 0.0)))

    def _capture_initial(self):
        import hashlib
        h = hashlib.sha256()
        h.update(np.asarray(self.env.data.qpos, dtype=np.float64).tobytes())
        h.update(np.asarray(self.env.data.qvel, dtype=np.float64).tobytes())
        self.initial_full_hash = h.hexdigest()
        self.initial_qpos = [float(x) for x in self.env.data.qpos]
        self.initial_qvel = [float(x) for x in self.env.data.qvel]

    def _loop(self, obs, t_start):
        env, sk = self.env, self.skill
        q0 = [round(float(env.data.qpos[0]), 4), round(float(env.data.qpos[1]), 4)]
        actions, phases = [], []
        info, done, steps, braked = {}, False, 0, 0
        last_phase = getattr(sk, 'phase', None)
        while not done and steps < self.max_steps:
            rs = env.robot_state()
            a = sk.act(obs, rs)
            _frame = None
            if self.record_trajectory:
                _frame = {'i': steps, 't': round(float(env.t), 5),
                          'qpos': [float(x) for x in env.data.qpos],
                          'qvel': [float(x) for x in env.data.qvel],
                          'action': [float(x) for x in np.asarray(a).reshape(-1)]}
            # 动作可以让导航底座改横向目标（D1/D2 靠这个真正绕行）
            hint = getattr(sk, 'nav_target_hint', None)
            if hint is not None and callable(hint):
                tgt = hint()
                if tgt is not None:
                    env.nav_target_y = env.channel_center + float(tgt)
            actions.append(np.asarray(a, dtype=np.float64))
            if getattr(sk, 'brake', False):
                env.brake_step()                   # 显式刹车，不是普通 step
                braked += 1
                # 刹车期间仍然完整判失效：倾覆优先于"停住了"
                tilt = env._tilt()
                vx = abs(float(env.data.qvel[0]))
                lat = float(env.data.qpos[1]) - env.channel_center
                if tilt > env.tip_deg:
                    info = {'reason': 'tipped', 't': env.t,
                            'x': float(env.data.qpos[0]), 'tilt_deg': tilt,
                            'contact_style': None, 'contact_any': False}
                    done = True
                elif abs(lat) > env.channel_half_width:
                    info = {'reason': 'out_of_bounds', 't': env.t,
                            'x': float(env.data.qpos[0]), 'tilt_deg': tilt,
                            'contact_style': None, 'contact_any': False}
                    done = True
                elif bool(getattr(sk, 'done', False)) and vx < 0.05:
                    # 停车完成：实际速度阈值 + 稳定保持，不能只等步数
                    info = {'reason': 'abort', 't': env.t,
                            'x': float(env.data.qpos[0]), 'tilt_deg': tilt,
                            'contact_style': None, 'contact_any': False}
                    done = True
                else:
                    info = {'reason': 'braking', 't': env.t,
                            'x': float(env.data.qpos[0]), 'tilt_deg': tilt,
                            'contact_style': None, 'contact_any': False}
                    done = False
            else:
                obs, r, te, tr, info = env.step(a)
                done = te or tr
            steps += 1
            if _frame is not None:
                _frame['contacts'] = self._contacts()
                self.trajectory.append(_frame)
            ph = getattr(sk, 'phase', None)
            if ph != last_phase:
                phases.append({'t': round(float(env.t), 3), 'phase': ph})
                last_phase = ph
            if float(env.data.qpos[0]) > FIELD_X_MAX:
                info = dict(info, reason='out_of_field')
                done = True

        return {
            'reason': info.get('reason'), 'success': info.get('reason') == 'success',
            'abort': info.get('reason') == 'abort',
            't_end': info.get('t'), 'x': info.get('x'),
            'final_x': round(float(env.data.qpos[0]), 3),
            'start_x': round(float(q0[0]), 3),
            'displacement_x': round(float(env.data.qpos[0]) - float(q0[0]), 3),
            'max_tilt': info.get('tilt_deg'),
            'contact': info.get('contact_style'),
            'belly_contact': info.get('contact_style') == 'body',
            'q0': q0, 'steps': steps, 'brake_steps': braked,
            'skill': getattr(sk, 'name', type(sk).__name__),
            'phases': phases,
            'triggered': len([p for p in phases if p['phase'] not in (None, 'idle')]) > 0,
            'action_fingerprint': action_fingerprint(actions),
            'n_actions': len(actions),
            'initial_full_hash': self.initial_full_hash,
            'initial_qpos': getattr(self, 'initial_qpos', None),
            'initial_qvel': getattr(self, 'initial_qvel', None),
            'trajectory': self.trajectory if self.record_trajectory else None,
        }

    def _contacts(self):
        import mujoco
        out = []
        d, m = self.env.data, self.env.model
        for c in d.contact[:d.ncon]:
            row = {'dist': round(float(c.dist), 6),
                   'pos': [round(float(x), 5) for x in c.pos]}
            for k, gid in (('g1', int(c.geom1)), ('g2', int(c.geom2))):
                row[k] = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, gid) or str(gid)
                bid = int(m.geom_bodyid[gid])
                row[k + '_body'] = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, bid) or str(bid)
            out.append(row)
        return out

    def run_with_seed(self, seed):
        self.seed = seed
        return self.run()
