"""
训练入口：PPO（numpy）+ 轮腿环境。

  .venv/bin/python scripts/train.py --config configs/P_flat.json --out runs/train_P
  .venv/bin/python scripts/train.py --config configs/G_mixed.json --out runs/train_G

记录：代码指纹、场景集合与划分、随机种子、超参、奖励、控制频率、累计控制步、
每次更新的参数校验和、以及 checkpoint（含优化器状态）。
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
    specs = json.loads(pathlib.Path(path).read_text())
    out = []
    for s in specs:
        s = dict(s)
        s['objects'] = s.get('objects', [])
        out.append(s)
    return out


def make_env(spec, cfg):
    return wheelleg_env.WheelLegEnv(
        spec, control_hz=cfg['control_hz'], max_seconds=cfg['max_seconds'],
        v_ref=cfg['v_ref'], tip_deg=cfg['tip_deg'])


def evaluate(params, specs, cfg, rng, deterministic=True):
    """deterministic=True 用策略均值；False 用训练同款随机采样（同一个 rng 状态）。"""
    """固定场景上的确定性评估；不更新参数、不更新归一化统计。"""
    res = []
    for spec in specs:
        env = make_env(spec, cfg)
        obs, _ = env.reset()
        done = False
        ep_return = 0.0
        info = {}
        while not done:
            a, _, _ = ppo.act(params, obs, rng, deterministic=deterministic)
            obs, r, te, tr, info = env.step(a)
            ep_return += r
            done = te or tr
        res.append({'scene': spec.get('name'), 'reason': info.get('reason'),
                    'x': info.get('x'), 'tilt_deg': info.get('tilt_deg'),
                    'return': round(ep_return, 3),
                    'n_control': info.get('n_control')})
    succ = sum(1 for r in res if r['reason'] == 'success')
    return {'scenes': res, 'n': len(res), 'success': succ,
            'success_rate': round(succ / len(res), 3) if res else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--seed', type=int, default=None)
    a = ap.parse_args()

    cfg = json.loads(pathlib.Path(a.config).read_text())
    train_specs = load_scenes(ROOT / cfg['scenes']['train'])
    val_specs = load_scenes(ROOT / cfg['scenes']['validation'])
    seed = a.seed if a.seed is not None else cfg.get('seeds', [0])[0]

    rng = np.random.default_rng(seed)
    np.random.seed(seed)

    run_dir = pathlib.Path(a.out).resolve()
    if run_dir.exists() and any(run_dir.iterdir()) and not a.resume:
        raise SystemExit(f'拒绝新建：{run_dir} 非空。换目录或加 --resume')
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'checkpoints').mkdir(exist_ok=True)

    params = ppo.init_params(rng)
    init_ck = ppo.params_checksum(params)
    (run_dir / 'config.json').write_text(json.dumps({
        **cfg, 'run_id': run_dir.name, 'seed': seed,
        'source': runio.source_identity(),
        'model': runio.model_identity(),
        'packages': runio.environment_snapshot()['packages'],
        'train_scenes': [s['name'] for s in train_specs],
        'val_scenes': [s['name'] for s in val_specs],
        'train_scene_ids': [terrain.scene_identity(s) for s in train_specs],
        'val_scene_ids': [terrain.scene_identity(s) for s in val_specs],
        'action_space': {'dim': ppo.ACT_DIM,
                         'meaning': '前腿目标偏移 / 后腿目标偏移 / 轮速倍率',
                         'scale': list(wheelleg_env.ACT_SCALE)},
        'init_params_checksum': init_ck,
    }, indent=2, ensure_ascii=False))

    # 训练前基线（update 0）：没有它就无法说明"学过之后变好了"
    (run_dir / 'eval.jsonl').write_text('')
    base_val = evaluate(params, val_specs, cfg, rng)
    base_st = evaluate(params, val_specs, cfg, rng, deterministic=False)
    (run_dir / 'eval.jsonl').open('a').write(json.dumps({
        'update': 0, 'control_steps': 0, **base_val,
        'stochastic': {'success_rate': base_st['success_rate'],
                       'tip_rate': round(sum(1 for s in base_st['scenes'] if s['reason']=='tipped')/len(base_st['scenes']), 3),
                       'mean_return': round(float(np.mean([s['return'] for s in base_st['scenes']])), 2)},
    }) + '\n')
    print(f"  [u0 基线] val success {base_val['success']}/{base_val['n']}", flush=True)

    total_steps = int(cfg['total_control_steps'])
    horizon = int(cfg['horizon'])
    log_path = run_dir / 'train_log.jsonl'
    t0 = time.time()
    steps = 0
    updates = 0
    best_val = -1e9
    checksums = [{'update': 0, 'params': init_ck, 'control_steps': 0}]

    while steps < total_steps:
        # ---- 采集 ----
        obs_buf, act_buf, logp_buf, rew_buf, val_buf, done_buf = [], [], [], [], [], []
        ep_infos = []
        spec_i = updates % len(train_specs)
        env = make_env(train_specs[spec_i], cfg)
        obs, _ = env.reset()
        steps_this = 0
        while steps_this < horizon:
            f = ppo.forward(params, obs[None, :])
            v = float(f['value'][0])
            a_, logp, _ = ppo.act(params, obs, rng)
            nobs, r, te, tr, info = env.step(a_)
            done = te or tr
            obs_buf.append(obs); act_buf.append(a_); logp_buf.append(logp)
            rew_buf.append(r); val_buf.append(v); done_buf.append(done)
            obs = nobs
            steps += 1
            steps_this += 1
            if done:
                ep_infos.append(info)
                spec_i = (spec_i + 1) % len(train_specs)
                env = make_env(train_specs[spec_i], cfg)
                obs, _ = env.reset()

        last_v = float(ppo.forward(params, obs[None, :])['value'][0])
        adv, ret = ppo.gae(rew_buf, val_buf, done_buf, last_v,
                           gamma=cfg['gamma'], lam=cfg['gae_lambda'])
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        batch = {'obs': np.array(obs_buf), 'act': np.array(act_buf),
                 'logp': np.array(logp_buf), 'adv': adv, 'ret': ret}
        params, pstats = ppo.ppo_update(
            params, batch, rng, epochs=cfg['epochs'], minibatch=cfg['minibatch'],
            clip=cfg['clip'], lr=cfg['lr'], ent_coef=cfg['ent_coef'])
        updates += 1
        ck = ppo.params_checksum(params)
        checksums.append({'update': updates, 'params': ck, 'control_steps': steps})

        rec = {'update': updates, 'control_steps': steps,
               'sampled_reward_mean': round(float(np.mean(rew_buf)), 4),
               'value_loss': None, 'ratio_dev_mean': pstats['ratio_dev_mean'],
               'params_checksum': ck, 'episodes': len(ep_infos),
               'reasons': {k: sum(1 for e in ep_infos if e.get('reason') == k)
                           for k in ('success', 'tipped', 'time_limit', 'out_of_bounds')},
               'wall_s': round(time.time() - t0, 1)}
        with log_path.open('a') as fh:
            fh.write(json.dumps(rec) + '\n')
        print(f"[u{updates:03d}] steps={steps} R={rec['sampled_reward_mean']:+.2f} "
              f"eps={rec['episodes']} reasons={rec['reasons']} "
              f"ck={ck[:8]} {rec['wall_s']}s", flush=True)

        if updates % cfg.get('eval_every_updates', 5) == 0:
            val = evaluate(params, val_specs, cfg, rng)
            stoch = evaluate(params, val_specs, cfg, rng, deterministic=False)
            tip = sum(1 for s in stoch['scenes'] if s['reason'] == 'tipped')
            (run_dir / 'eval.jsonl').open('a').write(json.dumps({
                'update': updates, 'control_steps': steps, **val,
                'stochastic': {'success_rate': stoch['success_rate'],
                               'tip_rate': round(tip / len(stoch['scenes']), 3),
                               'mean_return': round(float(np.mean([s['return'] for s in stoch['scenes']])), 2)},
            }) + '\n')
            print(f"  val success {val['success']}/{val['n']} "
                  f"({val['success_rate']})", flush=True)
            if val['success_rate'] is not None and val['success_rate'] > best_val:
                best_val = val['success_rate']
                np.savez(run_dir / 'checkpoints' / 'best.npz', **params)

    np.savez(run_dir / 'checkpoints' / 'final.npz', **params)
    (run_dir / 'checksums.json').write_text(json.dumps(checksums, indent=2))
    final_ck = ppo.params_checksum(params)
    import resource
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    env_only = None
    try:
        import wheelleg_env as _we
        import time as _t
        _e = make_env(train_specs[0], cfg)
        _e.reset()
        _t0 = _t.time()
        for _ in range(200):
            _e.step(np.zeros(ppo.ACT_DIM))
        el = _t.time() - _t0
        env_only = {'control_per_s': round(200 / el, 1),
                    'physics_per_s': round(_e.n_physics / el, 1)}
    except Exception as exc:
        env_only = {'error': repr(exc)[:100]}

    summary = {
        'run_id': run_dir.name, 'seed': seed, 'updates': updates,
        'baseline_val_success': base_val['success_rate'],
        'throughput': env_only,
        'peak_rss_mb': round(rss_mb, 1),
        'wall_seconds': round(time.time() - t0, 1),
        'control_steps': steps,
        'init_params_checksum': init_ck, 'final_params_checksum': final_ck,
        'params_changed': init_ck != final_ck,
        'checkpoints': ['checkpoints/final.npz',
                        *(['checkpoints/best.npz']
                          if (run_dir / 'checkpoints/best.npz').exists() else [])],
    }
    (run_dir / 'train_summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
