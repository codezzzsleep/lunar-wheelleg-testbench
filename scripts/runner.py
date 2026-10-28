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
    def __init__(self, env, skill, visible=None, params=None, max_steps=2000, seed=0):
        self.env = env
        self.skill = skill if not isinstance(skill, str) else __import__('skills').make_skill(skill)
        self.visible = visible or {}
        self.max_steps = max_steps
        env.plan_visible = dict(self.visible)      # 关键：动作需要它才能触发
        env.nav_target_y = env.channel_center      # 每次 reset 清空导航横向目标
        self.seed = seed
        self.skill.reset(params or {})

    def run(self):
        env, sk = self.env, self.skill
        obs, _ = env.reset(seed=self.seed)
        q0 = [round(float(env.data.qpos[0]), 4), round(float(env.data.qpos[1]), 4)]
        actions, phases = [], []
        info, done, steps, braked = {}, False, 0, 0
        last_phase = getattr(sk, 'phase', None)
        while not done and steps < self.max_steps:
            rs = env.robot_state()
            a = sk.act(obs, rs)
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
            'max_tilt': info.get('tilt_deg'),
            'contact': info.get('contact_style'),
            'belly_contact': info.get('contact_style') == 'body',
            'q0': q0, 'steps': steps, 'brake_steps': braked,
            'skill': getattr(sk, 'name', type(sk).__name__),
            'phases': phases,
            'triggered': len([p for p in phases if p['phase'] not in (None, 'idle')]) > 0,
            'action_fingerprint': action_fingerprint(actions),
            'n_actions': len(actions),
        }

    def run_with_seed(self, seed):
        self.seed = seed
        return self.run()
