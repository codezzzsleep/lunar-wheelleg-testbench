"""
训练入口：PPO（numpy）+ 轮腿环境。

  .venv/bin/python scripts/train.py --config configs/R_low.json --seed 0 --out runs/train_s0

本版修正（对应任务书第六、七、十一节）：
  · 采集时分开 terminated / truncated：真实终止不 bootstrap，时间截断 bootstrap。
  · 四条独立随机流：初始化 / 动作采样 / minibatch 打乱 / 评估。
    评估不再消耗训练随机数 —— 改评估频率不会改变训练轨迹。
  · 验证清单固定为 (scene, episode_seed) 列表并落盘；每个 checkpoint 评估同一清单。
  · 逐场景逐种子结果全部保存，不只存两个场景的平均值。
  · --resume 明确拒绝（方案 A）：本版不支持续训，不假装支持后清空重训。
  · actor / critic 分开记录校验和；诊断项来自真实计算结果，不用 None 占位。
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ppo
import runio
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_scenes(path):
    return [dict(s, objects=s.get('objects', []))
            for s in json.loads(pathlib.Path(path).read_text())]


def make_env(spec, cfg):
    return wheelleg_env.WheelLegEnv(
        spec, control_hz=cfg['control_hz'], max_seconds=cfg['max_seconds'],
        v_ref=cfg['v_ref'], tip_deg=cfg['tip_deg'])


def build_eval_manifest(specs, episode_seeds):
    return [{'scene': s['name'], 'scene_id': terrain.scene_identity(s),
             'episode_seed': int(e), 'spec': s}
            for s in specs for e in episode_seeds]


def evaluate(params, manifest, cfg, deterministic):
    """固定清单评估：每个 (scene, episode_seed) 重新播种，跨 checkpoint 可比。"""
    rows = []
    for item in manifest:
        env = make_env(item['spec'], cfg)
        obs, _ = env.reset(seed=item['episode_seed'])
        rng = np.random.default_rng(item['episode_seed'] * 7919 + 13)
        ret, info, done = 0.0, {}, False
        while not done:
            if deterministic:
                a = ppo.deterministic_action(params, obs)
            else:
                a, _, _, _ = ppo.sample(params, obs, rng)
            obs, r, te, tr, info = env.step(a)
            ret += r
            done = te or tr
        rows.append({'scene': item['scene'], 'scene_id': item['scene_id'],
                     'episode_seed': item['episode_seed'],
                     'reason': info.get('reason'), 'return': round(ret, 3),
                     'x': info.get('x'), 'tilt_deg': info.get('tilt_deg'),
                     'success': info.get('reason') == 'success'})
    n = len(rows)
    succ = sum(1 for r in rows if r['success'])
    tipped = sum(1 for r in rows if r['reason'] == 'tipped')
    return {'n': n, 'success': succ, 'success_rate': round(succ / n, 4),
            'tip_rate': round(tipped / n, 4),
            'mean_return': round(float(np.mean([r['return'] for r in rows])), 3),
            'per_episode': rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()

    if a.resume:
        raise SystemExit(
            '本版不支持续训（任务书第十一节方案 A）。\n'
            '  旧实现的 --resume 会重新初始化参数并清空评估记录，那是在假装支持恢复。\n'
            '  请换一个新的输出目录重跑。')

    cfg = json.loads(pathlib.Path(a.config).read_text())
    train_specs = load_scenes(ROOT / cfg['scenes']['train'])
    val_specs = load_scenes(ROOT / cfg['scenes']['validation'])
    seed = a.seed if a.seed is not None else cfg.get('seeds', [0])[0]

    init_rng = np.random.default_rng(seed)
    act_rng = np.random.default_rng(seed + 1_000)
    shuf_rng = np.random.default_rng(seed + 2_000)

    run_dir = pathlib.Path(a.out).resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        raise SystemExit(f'拒绝新建：{run_dir} 非空。请换一个新目录。')
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'checkpoints').mkdir(exist_ok=True)

    manifest = build_eval_manifest(val_specs, cfg.get('eval_episode_seeds', [0]))
    (run_dir / 'eval_manifest.json').write_text(json.dumps(
        [{k: v for k, v in m.items() if k != 'spec'} for m in manifest],
        indent=2, ensure_ascii=False))

    params = ppo.init_params(init_rng)
    opt = ppo.Adam(params, lr=cfg['lr'])
    init_actor, init_critic = ppo.actor_checksum(params), ppo.critic_checksum(params)

    (run_dir / 'config.json').write_text(json.dumps({
        **cfg, 'run_id': run_dir.name, 'seed': seed,
        'rng_streams': {'init': seed, 'act': seed + 1000, 'shuffle': seed + 2000,
                        'eval': 'per (scene, episode_seed)，与训练流无关'},
        'source': runio.source_identity(), 'model': runio.model_identity(),
        'packages': runio.environment_snapshot()['packages'],
        'train_scenes': [s['name'] for s in train_specs],
        'train_scene_ids': [terrain.scene_identity(s) for s in train_specs],
        'val_scene_ids': [terrain.scene_identity(s) for s in val_specs],
        'eval_manifest_size': len(manifest),
        'action_space': {'dim': ppo.ACT_DIM,
                         'meaning': '前腿目标偏移 / 后腿目标偏移 / 轮速倍率 / 差速转向',
                         'scale': list(wheelleg_env.ACT_SCALE),
                         'convention': 'raw = mean + std*eps；环境执行 clip(raw,-1,1)'},
        'init_actor_checksum': init_actor, 'init_critic_checksum': init_critic,
    }, indent=2, ensure_ascii=False))

    eval_path = run_dir / 'eval.jsonl'
    base = {'update': 0, 'control_steps': 0,
            'det': evaluate(params, manifest, cfg, True),
            'stoch': evaluate(params, manifest, cfg, False),
            'actor_checksum': init_actor, 'critic_checksum': init_critic}
    eval_path.write_text(json.dumps(base, ensure_ascii=False) + '\n')
    print(f"[u0] det {base['det']['success_rate']} stoch {base['stoch']['success_rate']} "
          f"tip {base['stoch']['tip_rate']} ret {base['stoch']['mean_return']}", flush=True)

    total_steps = int(cfg['total_control_steps'])
    horizon = int(cfg['horizon'])
    eval_every = int(cfg.get('eval_every_updates', 20))
    t0 = time.time()
    steps, updates = 0, 0
    spec_i = 0
    env = make_env(train_specs[spec_i], cfg)
    obs, _ = env.reset(seed=seed)

    while steps < total_steps:
        obs_b, raw_b, logp_b, rew_b, val_b, bm_b, cm_b = [], [], [], [], [], [], []
        next_obs_b = []
        for _ in range(horizon):
            v = float(ppo.forward(params, obs[None, :])['value'][0])
            exec_a, raw, logp, _ = ppo.sample(params, obs, act_rng)
            nobs, r, te, tr, info = env.step(exec_a)
            obs_b.append(obs); raw_b.append(raw); logp_b.append(logp)
            # 奖励缩放：只改数值条件，不改排序。回报量级上百会让价值函数欠拟合，
            # 优势被价值误差主导，策略梯度退化成噪声（实测确定性成功率不升反降）。
            rew_b.append(r * cfg.get('reward_scale', 1.0)); val_b.append(v)
            bm_b.append(0.0 if te else 1.0)      # 真实终止不 bootstrap
            cm_b.append(0.0 if (te or tr) else 1.0)
            next_obs_b.append(nobs)              # 每个转移的真实后继状态，reset 前保存
            obs = nobs
            steps += 1
            if te or tr:
                spec_i = (spec_i + 1) % len(train_specs)
                env = make_env(train_specs[spec_i], cfg)
                obs, _ = env.reset(seed=seed + steps)
        # 每个转移的 V(s_{t+1}) 都取真实后继状态（reset 之前记录），
        # 这样 rollout 中途的时间截断也能正确 bootstrap。
        next_val_b = ppo.forward(params, np.array(next_obs_b))['value']

        adv, ret = ppo.gae(rew_b, val_b, next_val_b, bm_b, cm_b,
                           gamma=cfg['gamma'], lam=cfg['gae_lambda'])
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        batch = {'obs': np.array(obs_b), 'raw': np.array(raw_b),
                 'logp_old': np.array(logp_b), 'adv': adv, 'ret': ret}
        params, hist = ppo.ppo_update(
            params, batch, opt, shuf_rng, epochs=cfg['epochs'],
            minibatch=cfg['minibatch'], clip=cfg['clip'],
            ent_coef=cfg['ent_coef'], vf_coef=cfg['vf_coef'])
        updates += 1

        last = hist[-1]
        rec = {'update': updates, 'control_steps': steps,
               'policy_loss': round(float(np.mean([h['policy_loss'] for h in hist])), 6),
               'value_loss': round(float(np.mean([h['value_loss'] for h in hist])), 6),
               'entropy': round(float(last['entropy']), 4),
               'kl': round(float(np.mean([h['kl'] for h in hist])), 6),
               'clip_fraction': round(float(np.mean([h['clip_fraction'] for h in hist])), 4),
               'grad_norm': round(float(np.mean([h['grad_norm'] for h in hist])), 4),
               'update_norm': round(float(np.mean([h['update_norm'] for h in hist])), 6),
               'log_std_mean': round(float(np.mean(params['log_std'])), 4),
               'actor_checksum': ppo.actor_checksum(params),
               'critic_checksum': ppo.critic_checksum(params),
               'sampled_reward_mean': round(float(np.mean(rew_b)), 4),
               'wall_s': round(time.time() - t0, 1)}
        with (run_dir / 'train_log.jsonl').open('a') as fh:
            fh.write(json.dumps(rec) + '\n')
        if updates % 10 == 0:
            print(f"[u{updates:03d}] steps={steps} R={rec['sampled_reward_mean']:+.2f} "
                  f"pl={rec['policy_loss']:+.4f} vl={rec['value_loss']:.4f} "
                  f"kl={rec['kl']:+.5f} clip={rec['clip_fraction']:.2f} "
                  f"gn={rec['grad_norm']:.2f} {rec['wall_s']}s", flush=True)

        if updates % eval_every == 0:
            d = evaluate(params, manifest, cfg, True)
            s = evaluate(params, manifest, cfg, False)
            rec = {'update': updates, 'control_steps': steps, 'det': d, 'stoch': s,
                   'actor_checksum': ppo.actor_checksum(params),
                   'critic_checksum': ppo.critic_checksum(params)}
            with eval_path.open('a') as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            np.savez(run_dir / 'checkpoints' / f'u{updates:04d}.npz', **params)
            print(f"  [eval u{updates}] det {d['success_rate']} stoch {s['success_rate']} "
                  f"tip {s['tip_rate']} ret {s['mean_return']}", flush=True)

    np.savez(run_dir / 'checkpoints' / 'final.npz', **params)
    final = {'update': updates, 'control_steps': steps,
             'det': evaluate(params, manifest, cfg, True),
             'stoch': evaluate(params, manifest, cfg, False),
             'actor_checksum': ppo.actor_checksum(params),
             'critic_checksum': ppo.critic_checksum(params)}
    with eval_path.open('a') as fh:
        fh.write(json.dumps(final, ensure_ascii=False) + '\n')

    import resource
    summary = {
        'run_id': run_dir.name, 'seed': seed, 'updates': updates,
        'control_steps': steps, 'wall_seconds': round(time.time() - t0, 1),
        'peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
        'init_actor_checksum': init_actor, 'final_actor_checksum': final['actor_checksum'],
        'actor_changed': init_actor != final['actor_checksum'],
        'init_critic_checksum': init_critic, 'final_critic_checksum': final['critic_checksum'],
        'baseline_det_success': base['det']['success_rate'],
        'final_det_success': final['det']['success_rate'],
        'baseline_stoch_success': base['stoch']['success_rate'],
        'final_stoch_success': final['stoch']['success_rate'],
        'baseline_stoch_tip': base['stoch']['tip_rate'],
        'final_stoch_tip': final['stoch']['tip_rate'],
        'checkpoints': sorted(p.name for p in (run_dir / 'checkpoints').glob('*.npz')),
    }
    (run_dir / 'train_summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
