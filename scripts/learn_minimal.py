"""
极简连续动作学习任务：验证 PPO/Adam 生产实现是否真的具备基本学习能力。

  .venv/bin/python scripts/learn_minimal.py --seeds 0 1 --steps 8000

任务（一次决策）：
  · 观测固定为常量向量；
  · 目标动作 TARGET = [0.3, -0.25, 0.1]（在动作范围内部）；
  · reward = -||a - TARGET||²；
  · 每回合一步即终止（真实终止，不 bootstrap）。

这里刻意去掉了机器人动力学、长时信用分配和复杂奖励。
如果这个小任务都学不会，问题在训练器，不能拿地形或奖励去掩盖。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ppo

TARGET = np.array([0.3, -0.25, 0.1])
FIXED_OBS = np.concatenate([np.array([0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.5]),
                           np.zeros(ppo.OBS_DIM - 7)])


class OneStepTarget:
    """一次决策的小任务；terminated=True，无 truncated。"""

    def __init__(self, target=TARGET):
        self.target = np.asarray(target, dtype=np.float64)

    def reset(self, rng=None):
        return FIXED_OBS.copy()

    def step(self, exec_action):
        dist = float(np.sum((exec_action - self.target) ** 2))
        return FIXED_OBS.copy(), -dist, True, False, {'dist': dist,
                                                      'action': exec_action.tolist()}


def train_one(seed, total_steps, horizon=64, epochs=4, minibatch=64, lr=1e-3):
    rng = np.random.default_rng(seed)
    shuf_rng = np.random.default_rng(seed + 10_000)
    params = ppo.init_params(rng)
    opt = ppo.Adam(params, lr=lr)
    env = OneStepTarget()

    def evalm():
        a = ppo.deterministic_action(params, FIXED_OBS)
        return {'action': [round(float(x), 4) for x in a],
                'dist': round(float(np.sum((a - env.target) ** 2)), 5)}

    init = evalm()
    curve = [{'step': 0, **init}]
    steps = 0
    updates = 0
    while steps < total_steps:
        obs_b, raw_b, logp_b, rew_b, val_b, bm_b, cm_b = [], [], [], [], [], [], []
        last_v = 0.0
        for _ in range(horizon):
            f = ppo.forward(params, FIXED_OBS[None, :])
            v = float(f['value'][0])
            e, raw, lp, _ = ppo.sample(params, FIXED_OBS, rng)
            _, r, te, tr, _ = env.step(e)
            obs_b.append(FIXED_OBS); raw_b.append(raw); logp_b.append(lp)
            rew_b.append(r); val_b.append(v)
            bm_b.append(0.0 if te else 1.0)     # 真实终止 -> 不 bootstrap
            cm_b.append(0.0)                    # 一步一回合，无后续
            steps += 1
        adv, ret = ppo.gae(rew_b, val_b, bm_b, cm_b, last_v, gamma=0.99, lam=0.95)
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        batch = {'obs': np.array(obs_b), 'raw': np.array(raw_b),
                 'logp_old': np.array(logp_b), 'adv': adv, 'ret': ret}
        params, hist = ppo.ppo_update(params, batch, opt, shuf_rng, epochs=epochs,
                                      minibatch=minibatch)
        updates += 1
        if updates % 15 == 0:
            curve.append({'step': steps, 'update': updates, **evalm()})
    final = evalm()
    return {
        'seed': seed, 'updates': updates, 'control_steps': steps,
        'init': init, 'final': final, 'curve': curve,
        'actor_checksum_init_note': '见 run 目录 checksums',
        'success': final['dist'] < 0.01,
        'final_log_std': [round(float(x), 4) for x in params['log_std']],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1])
    ap.add_argument('--steps', type=int, default=8000)
    ap.add_argument('--out', default='runs/minimal_learn')
    a = ap.parse_args()

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for s in a.seeds:
        r = train_one(s, a.steps)
        results.append(r)
        print(f"seed {s}: init {r['init']['action']} dist={r['init']['dist']:.4f} "
              f"-> final {r['final']['action']} dist={r['final']['dist']:.5f} "
              f"({'学会' if r['success'] else '未达标'})", flush=True)

    (out / 'results.json').write_text(json.dumps({
        'target': TARGET.tolist(), 'total_steps': a.steps,
        'runs': results,
        'verdict': {
            'all_learned': all(r['success'] for r in results),
            'max_init_dist': max(r['init']['dist'] for r in results),
            'max_final_dist': max(r['final']['dist'] for r in results),
        },
    }, indent=2, ensure_ascii=False))
    print(json.dumps({'all_learned': all(r['success'] for r in results),
                      'final_dists': [r['final']['dist'] for r in results]}, indent=2))
    return 0 if all(r['success'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
