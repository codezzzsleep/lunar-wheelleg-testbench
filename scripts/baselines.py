"""
任务基准对照：零残差 / 未训练策略 / 简单可行控制器 / 学习后策略。

  .venv/bin/python scripts/baselines.py --split validation --out runs/baselines_val

四个对照（任务书第六节要求）：
  1. zero_residual : 动作恒为 0，等价于底层 PD 保持站姿 + 轮速伺服
  2. untrained     : 同一学习器的未训练初始化（多种子）
  3. simple_ctrl   : 比例通道跟随控制器（只用导航状态，不用学习）
  4. learned       : 指定 checkpoint

全部用同一份清单、同一组初态 seed，逐场景记录。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ppo
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def simple_controller(env, k_lat=1.0, k_head=0.5):
    """
    通道跟随：横向偏差与朝向误差做比例控制到差速转向。
    这是"有代表性的简单可行控制器"，作为任务可行性与实际价值参照。
    符号由开环标定确定：a3>0 朝 -y 转。
    """
    lat, head = env._nav_state()
    a = np.zeros(wheelleg_env.ACT_DIM)
    a[3] = float(np.clip(k_lat * lat + k_head * head, -1.0, 1.0))
    return a


def run_episode(env, policy, seed):
    obs, _ = env.reset(seed=seed)
    total, info, done = 0.0, {}, False
    while not done:
        if policy == 'zero':
            a = np.zeros(wheelleg_env.ACT_DIM)
        elif policy == 'simple':
            a = simple_controller(env)
        else:
            a = ppo.deterministic_action(policy, obs)
        obs, r, te, tr, info = env.step(a)
        total += r
        done = te or tr
    return {'reason': info['reason'], 'success': info['reason'] == 'success',
            'contact_style': info.get('contact_style'),
            'contact_any': info.get('contact_any'),
            'first_contact_s': info.get('first_contact_s'),
            'x': info.get('x'), 'lateral_offset': info.get('lateral_offset'),
            'return': round(total, 2)}


def evaluate(policy, specs, seeds, label, cfg):
    rows = []
    for spec in specs:
        env = wheelleg_env.WheelLegEnv(spec, control_hz=cfg['control_hz'],
                                       max_seconds=cfg['max_seconds'],
                                       v_ref=cfg['v_ref'], tip_deg=cfg['tip_deg'])
        for sd in seeds:
            r = run_episode(env, policy, sd)
            r.update({'scene': spec['name'], 'family': spec.get('family'),
                      'episode_seed': sd})
            rows.append(r)
    # 确定性口径按场景统计（每个场景用 seed 0），多初态另列
    per_scene = [r for r in rows if r['episode_seed'] == 0]
    succ = sum(1 for r in per_scene if r['success'])
    contact_succ = sum(1 for r in per_scene if r['success'] and r['contact_any'])
    return {'label': label, 'n_scenes': len(per_scene),
            'per_scene_success': succ,
            'per_scene_rate': round(succ / len(per_scene), 4) if per_scene else None,
            'per_scene_contact_success': contact_succ,
            'across_seeds': {'n': len(rows),
                             'rate': round(sum(1 for r in rows if r['success']) / len(rows), 4)},
            'rows': rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='validation')
    ap.add_argument('--config', default='configs/skill_ppo.json')
    ap.add_argument('--checkpoints', nargs='*', default=[])
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    cfg = json.loads((ROOT / a.config).read_text())
    specs = json.loads((ROOT / f'scenes/skill_{a.split}.json').read_text())
    seeds = cfg.get('eval_episode_seeds', [0, 1, 2])

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    results.append(evaluate('zero', specs, seeds, 'zero_residual', cfg))
    results.append(evaluate('simple', specs, seeds, 'simple_ctrl', cfg))
    for s in (0, 1, 2):
        results.append(evaluate(ppo.init_params(np.random.default_rng(s)), specs, seeds,
                                f'untrained_s{s}', cfg))
    for ck in a.checkpoints:
        params = dict(np.load(ck))
        results.append(evaluate(params, specs, seeds, pathlib.Path(ck).stem, cfg))

    (out / 'baselines.json').write_text(json.dumps(
        {'split': a.split, 'seeds': seeds, 'config': a.config, 'results': results},
        indent=2, ensure_ascii=False))

    print(f"{'策略':16s} {'按场景成功':>10s} {'接触成功':>8s} {'多初态':>8s}")
    for r in results:
        print(f"{r['label']:16s} {r['per_scene_success']:>5d}/{r['n_scenes']:<4d} "
              f"{r['per_scene_contact_success']:>8d} {r['across_seeds']['rate']:>8.3f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
