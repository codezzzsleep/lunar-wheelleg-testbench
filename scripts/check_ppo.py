"""
PPO 训练器的数值验证：解析梯度 vs 中心差分，以及 Adam / 裁剪 / GAE 的单点检查。

  .venv/bin/python scripts/check_ppo.py

设计（对应任务书第三节与第五节）：
  · 固定小 batch、float64、固定 advantages/returns/logp_old，构造明确的标量 loss；
  · 差分**不经过** Adam 与梯度裁剪，避免把优化器混进反传公式；
  · 避开 min/clip 的不可导边界：构造 ratio 落在 (1-clip, 1+clip) 内且 adv>0/adv<0 两种情况；
  · 同时报告绝对误差与相对误差（接近零的梯度只看相对误差没有意义）；
  · GAE 用可手算的小序列，分别覆盖真实终止 / 时间截断 / rollout 截断 / 跨回合 reset。
"""
import sys
import pathlib

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ppo

FAILS = []


def check(name, ok, detail):
    print(f'{"PASS" if ok else "FAIL"}  {name}: {detail}')
    if not ok:
        FAILS.append(name)


def make_batch(rng, n=8, adv_sign=1.0):
    obs = rng.normal(0, 0.5, size=(n, ppo.OBS_DIM))
    params = ppo.init_params(rng)
    f = ppo.forward(params, obs)
    std = np.exp(params['log_std'])
    raw = f['mean'] + 0.3 * std * rng.standard_normal(f['mean'].shape)
    logp_old = ppo.gaussian_logp(params, raw, f['mean'])
    return params, {
        'obs': obs, 'raw': raw, 'logp_old': logp_old,
        'adv': adv_sign * rng.uniform(0.5, 1.5, size=n),
        'ret': rng.normal(0, 1.0, size=n),
    }


def fd_gradients():
    rng = np.random.default_rng(0)
    for adv_sign, tag in ((1.0, 'adv>0'), (-1.0, 'adv<0')):
        params, batch = make_batch(rng, adv_sign=adv_sign)
        g, diag = ppo.ppo_grads(params, batch)
        ratio = diag['ratio']
        ok_range = bool(np.all(ratio > 0.2) and np.all(ratio < 1.8))
        check(f'差分前提 {tag}：ratio 在裁剪区间内', ok_range,
              f'ratio ∈ [{ratio.min():.3f}, {ratio.max():.3f}]')

        eps = 1e-6
        worst = {'abs': 0.0, 'rel': 0.0, 'key': None}
        for key in params:
            flat = params[key].reshape(-1)
            picked = np.linspace(0, flat.size - 1, min(5, flat.size)).astype(int)
            for idx in picked:
                base = params[key].copy()
                up = {k: v.copy() for k, v in params.items()}
                dn = {k: v.copy() for k, v in params.items()}
                up[key].reshape(-1)[idx] += eps
                dn[key].reshape(-1)[idx] -= eps
                lu, _ = ppo.ppo_loss(up, batch)
                ld, _ = ppo.ppo_loss(dn, batch)
                num = (lu - ld) / (2 * eps)
                ana = float(g[key].reshape(-1)[idx])
                abserr = abs(num - ana)
                denom = max(abs(num), abs(ana), 1e-8)
                relerr = abserr / denom
                if abserr > worst['abs']:
                    worst = {'abs': abserr, 'rel': relerr, 'key': f'{key}[{idx}]',
                             'num': num, 'ana': ana}
        check(f'中心差分 {tag}', worst['abs'] < 1e-5,
              f"最大绝对误差 {worst['abs']:.2e}（{worst['key']}：解析 {worst.get('ana'):.6f} "
              f"vs 数值 {worst.get('num'):.6f}，相对 {worst['rel']:.2e}）")


def adam_updates_all_params():
    rng = np.random.default_rng(1)
    params, batch = make_batch(rng)
    before = {k: v.copy() for k, v in params.items()}
    g, _ = ppo.ppo_grads(params, batch)
    opt = ppo.Adam(params, lr=1e-3)
    opt.step(params, g)
    changed = [k for k in params if not np.allclose(params[k], before[k])]
    expect = [k for k in params if np.any(np.abs(g[k]) > 0)]
    check('Adam 更新了每个有非零梯度的参数', set(changed) == set(expect),
          f'有梯度 {len(expect)} 个，被更新 {len(changed)} 个；缺 {sorted(set(expect)-set(changed))}')
    actor_changed = [k for k in ppo.ACTOR_KEYS if k in changed]
    critic_changed = [k for k in ppo.CRITIC_KEYS if k in changed]
    check('actor 与 critic 都发生更新', len(actor_changed) >= 5 and len(critic_changed) >= 5,
          f'actor {len(actor_changed)}/{len(ppo.ACTOR_KEYS)}，'
          f'critic {len(critic_changed)}/{len(ppo.CRITIC_KEYS)}')


def adam_zero_grad_does_nothing():
    rng = np.random.default_rng(2)
    params = ppo.init_params(rng)
    before = {k: v.copy() for k, v in params.items()}
    opt = ppo.Adam(params, lr=1e-2)
    opt.step(params, {k: np.zeros_like(v) for k, v in params.items()})
    same = all(np.allclose(params[k], before[k]) for k in params)
    check('零梯度 + 无历史动量时参数不变', same, f'最大变化 {max(float(np.max(np.abs(params[k]-before[k]))) for k in params):.2e}')


def adam_state_isolated():
    rng = np.random.default_rng(3)
    p1, b1 = make_batch(rng)
    p2, b2 = make_batch(rng)
    o1, o2 = ppo.Adam(p1), ppo.Adam(p2)
    g1, _ = ppo.ppo_grads(p1, b1)
    o1.step(p1, g1)
    before2 = {k: v.copy() for k, v in p2.items()}
    g2, _ = ppo.ppo_grads(p2, b2)
    o2.step(p2, g2)
    check('两个独立优化器互不影响', o1.t == 1 and o2.t == 1,
          f'时刻计数 {o1.t}/{o2.t}，状态校验和 {o1.state_checksum()[:8]}/{o2.state_checksum()[:8]}')


def policy_output_moves():
    rng = np.random.default_rng(4)
    params, batch = make_batch(rng)
    obs = batch['obs'][:1]
    before = ppo.forward(params, obs)['mean'].copy()
    opt = ppo.Adam(params, lr=1e-2)
    for _ in range(20):
        g, _ = ppo.ppo_grads(params, batch)
        opt.step(params, g)
    after = ppo.forward(params, obs)['mean']
    finite = bool(np.all(np.isfinite(after)))
    moved = float(np.max(np.abs(after - before)))
    check('有效更新后策略输出发生变化且有限', finite and moved > 1e-4,
          f'max|Δmean| = {moved:.4e}, finite={finite}')


def action_probability_consistency():
    """任务 B：参数未更新时，用保存的 raw 重算 logp 必须等于 old，包含边界样本。"""
    rng = np.random.default_rng(5)
    params = ppo.init_params(rng)
    params['bm'] = np.array([3.0, -3.0, 0.0])      # 让部分样本必然被环境裁剪
    obs = rng.normal(0, 0.5, size=(64, ppo.OBS_DIM))
    raws, execs, logps = [], [], []
    for i in range(64):
        e, r, lp, _ = ppo.sample(params, obs[i], rng)
        execs.append(e); raws.append(r); logps.append(lp)
    raws = np.array(raws); execs = np.array(execs)
    f = ppo.forward(params, obs)
    recomputed = ppo.gaussian_logp(params, raws, f['mean'])
    diff = float(np.max(np.abs(recomputed - np.array(logps))))
    ratio = np.exp(recomputed - np.array(logps))
    clipped = int(np.sum(np.any(np.abs(raws) > 1.0, axis=1)))
    check('未更新时 ratio == 1（含边界裁剪样本）',
          diff < 1e-12 and float(np.max(np.abs(ratio - 1))) < 1e-9,
          f'max|Δlogp| = {diff:.2e}，max|ratio-1| = {float(np.max(np.abs(ratio-1))):.2e}，'
          f'其中 {clipped}/64 个样本被环境裁剪')
    check('执行动作始终在 [-1,1]', bool(np.all(np.abs(execs) <= 1.0)),
          f'范围 [{execs.min():.3f}, {execs.max():.3f}]；raw 范围 [{raws.min():.3f}, {raws.max():.3f}]')
    return params, obs


def reproducibility():
    p1 = ppo.init_params(np.random.default_rng(7))
    p2 = ppo.init_params(np.random.default_rng(7))
    obs = np.zeros(ppo.OBS_DIM)
    e1 = ppo.deterministic_action(p1, obs)
    e2 = ppo.deterministic_action(p2, obs)
    r1 = ppo.sample(p1, obs, np.random.default_rng(9))
    r2 = ppo.sample(p2, obs, np.random.default_rng(9))
    check('固定种子可复现', np.allclose(e1, e2) and np.allclose(r1[1], r2[1]) and
          abs(r1[2] - r2[2]) < 1e-15,
          f'确定性动作差 {np.max(np.abs(e1-e2)):.1e}，raw 差 {np.max(np.abs(r1[1]-r2[1])):.1e}')


def gae_handcheck():
    """任务 C：可手算的小序列。"""
    gamma, lam = 0.5, 1.0

    # 情形 1：真实终止（t=1 终止），不 bootstrap
    r = [1.0, 2.0]
    v = [0.5, 0.8]
    bm = [1.0, 0.0]
    cm = [1.0, 0.0]
    adv, ret = ppo.gae(r, v, bm, cm, last_value=99.0, gamma=gamma, lam=lam)
    # delta1 = 2 + 0.5*0*99 - 0.8 = 1.2 ; adv1 = 1.2
    # delta0 = 1 + 0.5*1*0.8 - 0.5 = 0.9 ; adv0 = 0.9 + 0.5*1*1.2 = 1.5
    ok = np.allclose(adv, [1.5, 1.2]) and np.allclose(ret, [2.0, 2.0])
    check('GAE 真实终止不 bootstrap', ok, f'adv={np.round(adv,4)} 期望 [1.5 1.2]')

    # 情形 2：外部时间截断，用 last_value bootstrap
    bm2 = [1.0, 1.0]
    cm2 = [1.0, 0.0]
    adv2, _ = ppo.gae([1.0, 2.0], [0.5, 0.8], bm2, cm2, last_value=4.0,
                      gamma=gamma, lam=lam)
    # delta1 = 2 + 0.5*1*4 - 0.8 = 3.2 ; adv1 = 3.2
    # delta0 = 1 + 0.5*1*0.8 - 0.5 = 0.9 ; adv0 = 0.9 + 0.5*1*3.2 = 2.5
    ok = np.allclose(adv2, [2.5, 3.2])
    check('GAE 时间截断要 bootstrap', ok, f'adv={np.round(adv2,4)} 期望 [2.5 3.2]')

    # 情形 3：跨回合 reset —— t=0 的下一状态来自新回合，不能串回
    bm3 = [1.0, 0.0]
    cm3 = [1.0, 0.0]          # t=1 之后是新回合，advantage 不得回传
    adv3, _ = ppo.gae([1.0, 2.0], [0.5, 0.8], bm3, cm3, last_value=7.0,
                      gamma=gamma, lam=lam)
    # delta1 = 2 + 0.5*0*7 - 0.8 = 1.2 ; adv1 = 1.2
    # delta0 = 1 + 0.5*1*0.8 - 0.5 = 0.9 ; adv0 = 0.9 + 0.5*1*1.2 = 1.5
    ok = np.allclose(adv3, [1.5, 1.2])
    check('GAE 跨回合不串接', ok, f'adv={np.round(adv3,4)} 期望 [1.5 1.2]')


def main():
    print('=== 反传与优化器 ===')
    fd_gradients()
    adam_updates_all_params()
    adam_zero_grad_does_nothing()
    adam_state_isolated()
    policy_output_moves()
    print('\n=== 动作与概率 ===')
    action_probability_consistency()
    reproducibility()
    print('\n=== GAE ===')
    gae_handcheck()
    print(f'\n{"全部通过" if not FAILS else "失败项：" + ", ".join(FAILS)}')
    return 0 if not FAILS else 1


if __name__ == '__main__':
    sys.exit(main())
