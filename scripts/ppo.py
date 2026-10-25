"""
小型 PPO（纯 numpy，无深度学习框架依赖）。

为什么不用 SB3/PyTorch：本机从 PyPI 拉 187 MB 的 torch 轮子不现实，而策略只有
39→64→64→3 的 MLP，手写前向/反向完全够用，且每一步都可审计。

明确边界：
  · 学习的是**高层残差策略**（前腿偏移 / 后腿偏移 / 轮速倍率），底层 PD 与轮速伺服固定。
  · 观测为仿真真值本体感觉，不含像素视觉。
  · 这不是"从零学会全身控制"。
"""
import json
import pathlib

import numpy as np

OBS_DIM = 39
ACT_DIM = 3
H = 64


def _tanh(x):
    return np.tanh(x)


def init_params(rng, obs_dim=OBS_DIM, act_dim=ACT_DIM, hidden=H):
    def layer(n_in, n_out):
        # orthogonal-ish 初始化，缩放 1/sqrt(n_in)
        return rng.normal(0, 1.0 / np.sqrt(n_in), size=(n_in, n_out))
    return {
        'W1': layer(obs_dim, hidden), 'b1': np.zeros(hidden),
        'W2': layer(hidden, hidden), 'b2': np.zeros(hidden),
        'Wm': layer(hidden, act_dim) * 0.1, 'bm': np.zeros(act_dim),
        'log_std': np.full(act_dim, -0.7),
        'V1': layer(obs_dim, hidden), 'bv1': np.zeros(hidden),
        'V2': layer(hidden, hidden), 'bv2': np.zeros(hidden),
        'Vv': layer(hidden, 1), 'bvv': np.zeros(1),
    }


def params_checksum(params):
    import hashlib
    h = hashlib.sha256()
    for k in sorted(params):
        h.update(k.encode())
        h.update(np.ascontiguousarray(params[k], dtype=np.float64).tobytes())
    return h.hexdigest()[:32]


def forward(params, obs):
    z1 = obs @ params['W1'] + params['b1']
    h1 = _tanh(z1)
    z2 = h1 @ params['W2'] + params['b2']
    h2 = _tanh(z2)
    mean = _tanh(h2 @ params['Wm'] + params['bm'])
    v1 = _tanh(obs @ params['V1'] + params['bv1'])
    v2 = _tanh(v1 @ params['V2'] + params['bv2'])
    value = (v2 @ params['Vv'] + params['bvv'])[..., 0]
    return {'z1': z1, 'h1': h1, 'z2': z2, 'h2': h2, 'mean': mean,
            'v1': v1, 'v2': v2, 'value': value}


def act(params, obs, rng, deterministic=False):
    out = forward(params, obs[None, :])
    mean = out['mean'][0]
    std = np.exp(params['log_std'])
    if deterministic:
        return np.clip(mean, -1, 1), 0.0, mean
    eps = rng.standard_normal(ACT_DIM)
    a = mean + std * eps
    logp = -0.5 * np.sum(((a - mean) / std) ** 2 + 2 * params['log_std'] + np.log(2 * np.pi))
    return np.clip(a, -1, 1), float(logp), mean


def gaussian_logp(params, obs, actions, means):
    std = np.exp(params['log_std'])
    z = (actions - means) / std
    return -0.5 * np.sum(z ** 2 + 2 * params['log_std'] + np.log(2 * np.pi), axis=1)


def ppo_update(params, batch, rng, epochs=4, minibatch=256, clip=0.2,
               lr=3e-4, ent_coef=0.005, vf_coef=0.5, max_grad=0.5):
    """返回 (params, stats)。所有梯度手写，便于核对。"""
    obs = batch['obs']
    act_ = batch['act']
    logp_old = batch['logp']
    adv = batch['adv']
    ret = batch['ret']
    n = obs.shape[0]
    lr_means = []
    lr_values = []

    for _ in range(epochs):
        idx = rng.permutation(n)
        for s in range(0, n, minibatch):
            b = idx[s:s + minibatch]
            o, a_, lo, ad, rt = obs[b], act_[b], logp_old[b], adv[b], ret[b]
            f = forward(params, o)
            std = np.exp(params['log_std'])
            logp = gaussian_logp(params, o, a_, f['mean'])
            ratio = np.exp(logp - lo)
            surr1 = ratio * ad
            surr2 = np.clip(ratio, 1 - clip, 1 + clip) * ad
            # 只有未被裁剪且占优的那支产生梯度
            use_unclipped = surr1 <= surr2
            dlogp = np.where(use_unclipped, -ratio * ad, 0.0) / len(b)

            # ---- policy 反向 ----
            g = {}
            z = (a_ - f['mean']) / std
            dmean = dlogp[:, None] * (z / std)                      # dL/dmean
            dlog_std = dlogp[:, None] * (z ** 2 - 1.0) - ent_coef / len(b)
            dpre = dmean * (1 - f['mean'] ** 2)                     # tanh'
            g['Wm'] = f['h2'].T @ dpre
            g['bm'] = dpre.sum(0)
            dh2 = dpre @ params['Wm'].T
            dz2 = dh2 * (1 - f['h2'] ** 2)
            g['W2'] = f['h1'].T @ dz2
            g['b2'] = dz2.sum(0)
            dh1 = dz2 @ params['W2'].T
            dz1 = dh1 * (1 - f['h1'] ** 2)
            g['W1'] = o.T @ dz1
            g['b1'] = dz1.sum(0)
            g['log_std'] = dlog_std.sum(0)

            # ---- value 反向 ----
            dv = (f['value'] - rt) * vf_coef / len(b)
            dvv = dv[:, None]
            g['Vv'] = f['v2'].T @ dvv
            g['bvv'] = dvv.sum(0)
            dv2 = dvv @ params['Vv'].T
            dvz2 = dv2 * (1 - f['v2'] ** 2)
            g['V2'] = f['v1'].T @ dvz2
            g['bv2'] = dvz2.sum(0)
            dv1 = dvz2 @ params['V2'].T
            dvz1 = dv1 * (1 - f['v1'] ** 2)
            g['V1'] = o.T @ dvz1
            g['bv1'] = dvz1.sum(0)

            # 梯度裁剪 + Adam
            total = np.sqrt(sum(float(np.sum(v ** 2)) for v in g.values()))
            scale = min(1.0, max_grad / (total + 1e-8))
            for k in g:
                g[k] = g[k] * scale
            _adam(params, g, k=k, lr=lr)
            lr_means.append(float(np.mean(np.abs(ratio - 1))))

    stats = {'ratio_dev_mean': float(np.mean(lr_means)) if lr_means else None}
    return params, stats


_ADAM = {}


def _adam(params, grads, k, lr, b1=0.9, b2=0.999, eps=1e-8):
    st = _ADAM.setdefault(k, {'m': np.zeros_like(params[k]), 'v': np.zeros_like(params[k]),
                              't': 0})
    st['t'] += 1
    st['m'] = b1 * st['m'] + (1 - b1) * grads[k]
    st['v'] = b2 * st['v'] + (1 - b2) * grads[k] ** 2
    mhat = st['m'] / (1 - b1 ** st['t'])
    vhat = st['v'] / (1 - b2 ** st['t'])
    params[k] = params[k] - lr * mhat / (np.sqrt(vhat) + eps)


def gae(rewards, values, dones, last_value, gamma=0.99, lam=0.95):
    T = len(rewards)
    adv = np.zeros(T, dtype=np.float64)
    last = 0.0
    for t in reversed(range(T)):
        nextv = last_value if t == T - 1 else values[t + 1]
        nonterminal = 0.0 if dones[t] else 1.0
        delta = rewards[t] + gamma * nextv * nonterminal - values[t]
        last = delta + gamma * lam * nonterminal * last
        adv[t] = last
    ret = adv + values
    return adv, ret
