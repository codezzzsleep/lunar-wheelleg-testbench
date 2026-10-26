"""
小型 PPO（纯 numpy，无深度学习框架依赖）。

修复的两个关键实现错误（e57d281 基线，已复现）：
  1. Adam 调用位于参数循环外 —— 每个 minibatch 只更新了最后一个键（bv1），
     actor 全部参数从未被优化器碰过。
  2. `act` 用**未裁剪**的采样计算 logp，却返回**裁剪后**的动作；train 把裁剪后的
     动作存进 batch，更新时又用它重算概率 —— 前后不是同一个动作。

本文件的约定（"高斯潜在动作 + 环境裁剪"）：
  raw   = mean + std * eps            # 潜在动作，logp 按它算
  exec  = clip(raw, -1, 1)            # 环境真正执行的动作
  batch 保存 raw；更新时用同一个 raw 重算 logp。
  mean 的 tanh 与整条动作的 tanh 不是一回事，所以不给裁剪后的动作套普通高斯密度。
"""
import hashlib

import numpy as np

OBS_DIM = 41   # 本体感觉 39 + 导航状态 2   # 本体感觉 40 + 导航状态 2（横向偏差、朝向误差）
ACT_DIM = 3   # 学习器只管 3 维；转向由共享导航底座产生
H = 64
LOG2PI = float(np.log(2 * np.pi))


# ------------------------------------------------------------------ 参数

def init_params(rng, obs_dim=OBS_DIM, act_dim=ACT_DIM, hidden=H):
    def layer(n_in, n_out, scale=1.0):
        return rng.normal(0, scale / np.sqrt(n_in), size=(n_in, n_out))
    return {
        'W1': layer(obs_dim, hidden), 'b1': np.zeros(hidden),
        'W2': layer(hidden, hidden), 'b2': np.zeros(hidden),
        'Wm': layer(hidden, act_dim, 0.1), 'bm': np.zeros(act_dim),
        'log_std': np.full(act_dim, -1.5),   # std≈0.22：成功动作区间只有 ±0.3，噪声过大会让策略靠噪声过关
        'V1': layer(obs_dim, hidden), 'bv1': np.zeros(hidden),
        'V2': layer(hidden, hidden), 'bv2': np.zeros(hidden),
        'Vv': layer(hidden, 1), 'bvv': np.zeros(1),
    }


ACTOR_KEYS = ('W1', 'b1', 'W2', 'b2', 'Wm', 'bm', 'log_std')
CRITIC_KEYS = ('V1', 'bv1', 'V2', 'bv2', 'Vv', 'bvv')


def _checksum(subset):
    h = hashlib.sha256()
    for k in sorted(subset):
        h.update(k.encode())
        h.update(np.ascontiguousarray(subset[k], dtype=np.float64).tobytes())
    return h.hexdigest()[:32]


def actor_checksum(params):
    return _checksum({k: params[k] for k in ACTOR_KEYS})


def critic_checksum(params):
    return _checksum({k: params[k] for k in CRITIC_KEYS})


def params_checksum(params):
    return _checksum(params)


# ------------------------------------------------------------------ 前向

def forward(params, obs):
    z1 = obs @ params['W1'] + params['b1']
    h1 = np.tanh(z1)
    z2 = h1 @ params['W2'] + params['b2']
    h2 = np.tanh(z2)
    mean = np.tanh(h2 @ params['Wm'] + params['bm'])
    v1 = np.tanh(obs @ params['V1'] + params['bv1'])
    v2 = np.tanh(v1 @ params['V2'] + params['bv2'])
    value = (v2 @ params['Vv'] + params['bvv'])[..., 0]
    return {'z1': z1, 'h1': h1, 'z2': z2, 'h2': h2, 'mean': mean,
            'v1': v1, 'v2': v2, 'value': value}


def sample(params, obs, rng):
    """返回 (exec_action, raw_action, logp_raw, mean)。"""
    f = forward(params, obs[None, :])
    mean = f['mean'][0]
    std = np.exp(params['log_std'])
    raw = mean + std * rng.standard_normal(ACT_DIM)
    logp = gaussian_logp(params, raw[None, :], mean[None, :])[0]
    return np.clip(raw, -1.0, 1.0), raw, float(logp), mean


def deterministic_action(params, obs):
    return np.clip(forward(params, obs[None, :])['mean'][0], -1.0, 1.0)


def gaussian_logp(params, raw, mean):
    std = np.exp(params['log_std'])
    z = (raw - mean) / std
    return -0.5 * np.sum(z ** 2 + 2 * params['log_std'] + LOG2PI, axis=1)


# ------------------------------------------------------------------ 损失与梯度

def ppo_loss(params, batch, clip=0.2, ent_coef=0.005, vf_coef=0.5):
    """标量损失。前向与数值差分必须用同一个函数。"""
    f = forward(params, batch['obs'])
    logp = gaussian_logp(params, batch['raw'], f['mean'])
    ratio = np.exp(logp - batch['logp_old'])
    surr = np.minimum(ratio * batch['adv'],
                      np.clip(ratio, 1 - clip, 1 + clip) * batch['adv'])
    policy_loss = -surr.mean()
    value_loss = 0.5 * np.mean((f['value'] - batch['ret']) ** 2)
    entropy = np.sum(params['log_std'] + 0.5 * (1.0 + LOG2PI))
    total = policy_loss + vf_coef * value_loss - ent_coef * entropy
    return total, {'policy_loss': float(policy_loss), 'value_loss': float(value_loss),
                   'entropy': float(entropy), 'ratio': ratio, 'mean': f['mean'],
                   'value': f['value']}


def ppo_grads(params, batch, clip=0.2, ent_coef=0.005, vf_coef=0.5):
    """解析梯度。返回 (grads, diag)。"""
    f = forward(params, batch['obs'])
    n = batch['obs'].shape[0]
    std = np.exp(params['log_std'])
    logp = gaussian_logp(params, batch['raw'], f['mean'])
    ratio = np.exp(logp - batch['logp_old'])
    adv = batch['adv']
    surr_u = ratio * adv
    surr_c = np.clip(ratio, 1 - clip, 1 + clip) * adv
    use_u = surr_u <= surr_c                 # 与 np.minimum 的选择一致
    dlogp = np.where(use_u, -ratio * adv, 0.0) / n

    z = (batch['raw'] - f['mean']) / std
    dmean = dlogp[:, None] * (z / std)
    dlog_std = dlogp[:, None] * (z ** 2 - 1.0) - ent_coef / n

    g = {}
    dpre = dmean * (1 - f['mean'] ** 2)
    g['Wm'] = f['h2'].T @ dpre
    g['bm'] = dpre.sum(0)
    dz2 = (dpre @ params['Wm'].T) * (1 - f['h2'] ** 2)
    g['W2'] = f['h1'].T @ dz2
    g['b2'] = dz2.sum(0)
    dz1 = (dz2 @ params['W2'].T) * (1 - f['h1'] ** 2)
    g['W1'] = batch['obs'].T @ dz1
    g['b1'] = dz1.sum(0)
    g['log_std'] = dlog_std.sum(0)

    dv = vf_coef * (f['value'] - batch['ret']) / n
    g['Vv'] = f['v2'].T @ dv[:, None]
    g['bvv'] = np.array([dv.sum()])
    dvz2 = (dv[:, None] @ params['Vv'].T) * (1 - f['v2'] ** 2)
    g['V2'] = f['v1'].T @ dvz2
    g['bv2'] = dvz2.sum(0)
    dvz1 = (dvz2 @ params['V2'].T) * (1 - f['v1'] ** 2)
    g['V1'] = batch['obs'].T @ dvz1
    g['bv1'] = dvz1.sum(0)

    diag = {'ratio': ratio, 'clip_fraction': float(np.mean(~use_u)),
            'kl': float(np.mean(batch['logp_old'] - logp)),
            'policy_loss': float(-surr_u.mean()),
            'value_loss': float(0.5 * np.mean((f['value'] - batch['ret']) ** 2)),
            'entropy': float(np.sum(params['log_std'] + 0.5 * (1.0 + LOG2PI)))}
    return g, diag


# ------------------------------------------------------------------ 优化器

class Adam:
    """
    状态绑定到实例。旧实现用模块级 _ADAM，同一进程里的第二个训练会继承旧动量。
    """

    def __init__(self, params, lr=3e-4, b1=0.9, b2=0.999, eps=1e-8):
        self.lr, self.b1, self.b2, self.eps = lr, b1, b2, eps
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}
        self.t = 0
        self.last_update_norm = 0.0

    def step(self, params, grads):
        self.t += 1
        sq = 0.0
        for k in params:                       # 每个参数都要更新
            g = grads[k]
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * g ** 2
            mhat = self.m[k] / (1 - self.b1 ** self.t)
            vhat = self.v[k] / (1 - self.b2 ** self.t)
            upd = self.lr * mhat / (np.sqrt(vhat) + self.eps)
            params[k] = params[k] - upd
            sq += float(np.sum(upd ** 2))
        self.last_update_norm = float(np.sqrt(sq))
        return self.last_update_norm

    def state_checksum(self):
        h = hashlib.sha256()
        for k in sorted(self.m):
            h.update(k.encode())
            h.update(np.ascontiguousarray(self.m[k]).tobytes())
            h.update(np.ascontiguousarray(self.v[k]).tobytes())
        return h.hexdigest()[:32]


def clip_grads(grads, max_norm):
    total = float(np.sqrt(sum(float(np.sum(g ** 2)) for g in grads.values())))
    scale = 1.0 if total <= max_norm or total == 0 else max_norm / total
    return {k: g * scale for k, g in grads.items()}, total


def ppo_update(params, batch, opt, rng, epochs=4, minibatch=256, clip=0.2,
               ent_coef=0.005, vf_coef=0.5, max_grad=0.5):
    n = batch['obs'].shape[0]
    hist = []
    for _ in range(epochs):
        idx = rng.permutation(n)
        for s in range(0, n, minibatch):
            b = {k: v[idx[s:s + minibatch]] for k, v in batch.items()}
            g, diag = ppo_grads(params, b, clip, ent_coef, vf_coef)
            g, gnorm = clip_grads(g, max_grad)
            unorm = opt.step(params, g)
            hist.append({**diag, 'grad_norm': gnorm, 'update_norm': unorm})
    return params, hist


# ------------------------------------------------------------------ GAE

def gae(rewards, values, next_values, bootstrap_mask, continuation_mask,
        gamma=0.99, lam=0.95):
    """
    delta_t = r_t + gamma * bootstrap_mask_t * V(s_{t+1}) - V(s_t)
    adv_t   = delta_t + gamma * lambda * continuation_mask_t * adv_{t+1}

    旧实现用 values[t+1] 充当 V(s_{t+1})，只在 rollout **末尾**替换成 last_value。
    一旦回合在 rollout 中途因时间限制截断并 reset，values[t+1] 就是**新回合**的价值，
    中间位置的 bootstrap 全部污染。现在要求调用方提供每个转移真实后继状态的
    next_values（长度与 T 相同），由采集器在 reset 之前取 V(s_{t+1})。

    bootstrap_mask_t：真实终止(成功/倾覆/出界)=0，外部时间截断=1
    continuation_mask_t：同回合内=1，回合结束（下一步来自 reset）=0
    """
    T = len(rewards)
    rewards = np.asarray(rewards, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    next_values = np.asarray(next_values, dtype=np.float64)
    bootstrap_mask = np.asarray(bootstrap_mask, dtype=np.float64)
    continuation_mask = np.asarray(continuation_mask, dtype=np.float64)
    assert next_values.shape[0] == T, 'next_values 必须与 T 等长'
    adv = np.zeros(T, dtype=np.float64)
    last = 0.0
    for t in reversed(range(T)):
        delta = rewards[t] + gamma * bootstrap_mask[t] * next_values[t] - values[t]
        last = delta + gamma * lam * continuation_mask[t] * last
        adv[t] = last
    return adv, adv + values
