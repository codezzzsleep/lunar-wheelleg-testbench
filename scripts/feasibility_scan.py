"""
任务可行性诊断 + 奖励账本核算。

  .venv/bin/python scripts/feasibility_scan.py --scenes scenes/train_P.json \
      --config configs/R_low.json --out runs/feasibility

做三件事（任务书第八、九节）：
  1. 常数动作扫描：确认动作空间里存在可执行解。这是**诊断**，不是学习策略。
  2. 三类轨迹的奖励账本：减速稳定通过 / 快速冲过倾覆 / 停住超时。
     比较非折扣 episode return 与按 gamma 的折扣回报，确认排序符合任务目标。
  3. 报告未训练均值策略（a=0）在各场景的成败，用来判断任务是否有学习空间。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ppo
import train
import wheelleg_env


def rollout(spec, cfg, action, max_steps=1200):
    env = wheelleg_env.WheelLegEnv(
        spec, control_hz=cfg['control_hz'], max_seconds=cfg['max_seconds'],
        v_ref=cfg['v_ref'], tip_deg=cfg['tip_deg'])
    obs, _ = env.reset(seed=cfg.get('seeds', [0])[0])
    total, disc, info, t = 0.0, 0.0, {}, 0
    gamma = cfg['gamma']
    obs_b, rew_b = [], []
    done = False
    while not done and t < max_steps:
        obs, r, te, tr, info = env.step(action)
        total += r
        disc += gamma ** t * r
        rew_b.append(r)
        obs_b.append(obs)
        t += 1
        done = te or tr
    return {'reason': info.get('reason'), 'x': info.get('x'),
            'min_wheel_x': info.get('min_wheel_x'), 'pass_x': info.get('pass_x'),
            'passed_at': info.get('passed_at'), 'tilt_deg': info.get('tilt_deg'),
            't': info.get('t'), 'undiscounted_return': round(total, 3),
            'discounted_return': round(disc, 3),
            'ledger': info.get('episode_return_ledger'),
            'last_reward_breakdown': info.get('rewards')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenes', default='scenes/train_P.json')
    ap.add_argument('--config', default='configs/R_low.json')
    ap.add_argument('--out', default='runs/feasibility')
    a = ap.parse_args()

    cfg = json.loads(pathlib.Path(a.config).read_text())
    specs = train.load_scenes(train.ROOT / a.scenes)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    grid = []
    for a0 in (-1.0, -0.5, 0.0, 0.5, 1.0):
        for a1 in (-0.5, 0.0, 0.5):
            for a2 in (-1.0, -0.5, 0.0, 0.5, 1.0):
                grid.append([a0, a1, a2])

    print(f'常数动作扫描：{len(grid)} 个动作 × {len(specs)} 场景')
    scan = []
    for spec in specs:
        wins = []
        for act in grid:
            r = rollout(spec, cfg, act)
            r['action'] = act
            r['scene'] = spec['name']
            scan.append(r)
            if r['reason'] == 'success':
                wins.append(act)
        zero = [r for r in scan if r['scene'] == spec['name']
                and r['action'] == [0.0, 0.0, 0.0]][0]
        print(f"  {spec['name']:16s} 可行动作 {len(wins):2d}/{len(grid)}  "
              f"零动作 -> {zero['reason']}")

    (out / 'constant_action_scan.json').write_text(
        json.dumps(scan, indent=2, ensure_ascii=False))

    # 三类轨迹的账本：按真实结局挑代表，而不是假设某个动作一定对应某种结局
    spec = specs[0]
    rows = [r for r in scan if r['scene'] == spec['name']]
    zero = [r for r in rows if r['action'] == [0.0, 0.0, 0.0]][0]
    succ = sorted([r for r in rows if r['reason'] == 'success'],
                  key=lambda r: -r['undiscounted_return'])
    tips = sorted([r for r in rows if r['reason'] == 'tipped'],
                  key=lambda r: -r['undiscounted_return'])
    tos = [r for r in rows if r['reason'] == 'time_limit']
    best_pass = succ[0] if succ else None
    best_tip = tips[0] if tips else None
    any_to = tos[0] if tos else None
    ledger = {'scene': spec['name'],
              'trajectories': {'zero_action': zero,
                               'best_pass': best_pass,
                               'best_tip': best_tip,
                               'time_limit': any_to}}
    (out / 'reward_ledger.json').write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print('\n奖励账本（同一场景）：')
    print(f"{'轨迹':22s} {'结局':14s} {'非折扣':>9s} {'折扣':>9s}")
    for k, v in ledger['trajectories'].items():
        if v is None:
            print(f"{k:22s} {'（该场景没有此类轨迹）':14s}")
            continue
        print(f"{k:22s} {str(v['reason']):14s} {v['undiscounted_return']:9.2f} "
              f"{v['discounted_return']:9.2f}  动作={v.get('action')}")

    checks = []
    if best_pass and best_tip:
        checks.append(('通过 > 倾覆',
                       best_pass['undiscounted_return'] > best_tip['undiscounted_return']))
    if best_pass and any_to:
        checks.append(('通过 > 超时',
                       best_pass['undiscounted_return'] > any_to['undiscounted_return']))
    ok = bool(checks) and all(v for _, v in checks)
    print('\n排序检查：')
    for k, v in checks:
        print(f'  {k}: {"成立" if v else "不成立"}')
        if not v:
            ok = False
    if not checks:
        print('  无法比较（缺少对照轨迹）')
        ok = False
    (out / 'verdict.json').write_text(json.dumps({
        'feasible_actions_per_scene': {
            s['name']: sum(1 for r in scan
                           if r['scene'] == s['name'] and r['reason'] == 'success')
            for s in specs},
        'zero_action_reasons': {s['name']: next(
            r['reason'] for r in scan
            if r['scene'] == s['name'] and r['action'] == [0.0, 0.0, 0.0])
            for s in specs},
        'reward_ordering_ok': bool(ok),
    }, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
