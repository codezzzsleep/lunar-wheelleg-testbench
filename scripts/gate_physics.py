"""
Gate P：同正面、不同背面的物理见证。

  .venv/bin/python scripts/gate_physics.py --twins runs/unseen/gate_p/p1 \
      --out runs/unseen/gate_p/w1 --workers 3

重要约定（写进每条记录，不事后含糊）：
  · 碰撞体 = 双胞胎 STL 的**凸包**（MuJoCo 对闭合网格按凸包碰撞）。
    因此 cleft/ledge 的凹部在碰撞里**不表现**；它们的差异只能来自凸包外形。
  · 本脚本只回答一个问题：在同样的正面、同样的任务、同样的初态下，
    不同背面是否导致**不同的动作结果**。不回答"凹槽是否被正确表示"。
"""
import argparse
import json
import pathlib
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
WHEEL_R = 0.08595


def build_spec(mesh_path, H, W, kind, seed, channel_half=1.2):
    """把双胞胎 STL 作为障碍放进干净场景（碰撞为凸包）。"""
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=3.0,
                             name=f'gateP_{kind}_{seed}')
    spec['channel'] = {'center_y': 0.0, 'half_width': channel_half}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    # 直接指定网格文件（跳过 manifest 路径），放在脊线 x=0 处
    spec['objects'] = [{'mesh_file': str(mesh_path), 'x': 0.0, 'y': 0.0,
                        'yaw_deg': 0.0, 'target_height_m': H}]
    return spec


def run_episode(spec, action_kind, seed):
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=15.0,
                                   v_ref=1.0, tip_deg=60.0)
    obs, _ = env.reset(seed=seed)
    info = {}
    done = False
    steps = 0
    while not done:
        if action_kind == 'R1':          # 直行
            a = np.zeros(wheelleg_env.ACT_DIM)
        elif action_kind == 'R2':        # 慢压：轮速倍率 -0.55
            a = np.array([0.0, 0.0, -0.55])
        elif action_kind == 'L1':        # 抬前腿慢过
            a = np.array([0.8, -0.3, -0.4])
        else:
            raise ValueError(action_kind)
        obs, r, te, tr, info = env.step(a)
        done = te or tr
        steps += 1
    return {'reason': info.get('reason'), 'success': info.get('reason') == 'success',
            't_end': info.get('t'), 'max_tilt': info.get('tilt_deg'),
            'x': info.get('x'), 'contact': info.get('contact_style'),
            'belly_contact': (info.get('contact_style') == 'body'),
            'steps': steps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--twins', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--actions', default='R1,R2,L1')
    ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--limit-fronts', type=int, default=0)
    a = ap.parse_args()

    meta = json.loads((pathlib.Path(a.twins) / 'twins_meta.json').read_text())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    actions = a.actions.split(',')
    seeds = [int(x) for x in a.seeds.split(',')]

    groups = defaultdict(list)
    for m in meta:
        groups[(m['front_seed'], round(m['H'], 4), round(m['W'], 4))].append(m)
    keys = sorted(groups)
    if a.limit_fronts:
        keys = keys[:a.limit_fronts]

    rows = []
    for key in keys:
        for m in sorted(groups[key], key=lambda z: z['type']):
            spec = build_spec(pathlib.Path(a.twins) / 'mesh' / f"{m['case_id']}.stl",
                              m['H'], m['W'], m['type'], key[0])
            for act in actions:
                for sd in seeds:
                    r = run_episode(spec, act, sd)
                    rows.append({'front': key, 'back': m['type'], 'H': m['H'],
                                 'W': m['W'], 'option': act, 'seed': sd,
                                 'L_back': m['L_back'], **r})
    (out / 'results.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')

    # 汇总：每个 (front, option) 下，各背面的成功数
    agg = defaultdict(lambda: defaultdict(int))
    for r in rows:
        agg[(r['front'], r['option'])][r['back']] += int(r['success'])
    total = len(seeds)

    flips = []
    for (front, option), per_back in agg.items():
        vals = set(per_back.values())
        if len(vals) > 1:
            flips.append({'front': front, 'option': option,
                          'per_back': dict(per_back), 'n_per_back': total})
    summary = {'n_fronts': len(keys), 'n_rows': len(rows),
               'n_actions': len(actions), 'n_seeds': len(seeds),
               'fronts_with_different_outcomes': len({f['front'] for f in flips}),
               'flipping_cells': len(flips)}
    (out / 'summary.json').write_text(json.dumps(
        {'summary': summary, 'flips': flips[:40]}, indent=2, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False))
    print(f'-> {out/"results.jsonl"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
