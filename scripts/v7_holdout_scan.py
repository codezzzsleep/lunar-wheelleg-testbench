"""新留出集真值扫描（程序化岩石池）。

每个（石头, 确认初态, 动作）真实执行一次，记录结局；观测在出生点采集一次，
用于计算简单基线（高度规则/宽度规则）在这一块石头上的决策。
不做任何缩放：石头的目标高度就是它自身高度。

  python scripts/v7_holdout_scan.py --pool assets/procedural_rocks --out runs/.../holdout_scan
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import actions as ACT
import eval_six
import runner
import skills
import v7_common_matrix as MX

HEIGHT_RULE = {'climb_direct': 1.0, 'climb_leg': 1.6, 'wheel_r': 0.08595}
SEEDS = (7, 11, 13)


def make_env_for_rock(rock, case):
    import terrain
    import wheelleg_env
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=case['goal_x'],
                             name=f"rock_{rock['id']}")
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    spec['objects'] = [{'mesh_file': str(ROOT / rock['body']), 'x': case['obstacle_x'],
                        'y': 0.0, 'yaw_deg': 0.0,
                        'target_height_m': float(rock['height_m'])}]
    import v7_soil
    r = v7_soil.resolve('nominal')
    spec['soil'] = {'mode': 'soil', 'label': r.get('label'), 'params': r['params']}
    return wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pool', default='assets/procedural_rocks')
    ap.add_argument('--case', default='cases/unseen_v1/R02.json')
    ap.add_argument('--out', required=True)
    ap.add_argument('--rocks', default=None, help='逗号分隔的石头 id；默认全部')
    ap.add_argument('--shard', default='0/1', help='i/n 分片')
    a = ap.parse_args()
    pool = json.loads((ROOT / a.pool / 'index.json').read_text())
    rocks = pool['rocks']
    if a.rocks:
        want = set(a.rocks.split(','))
        rocks = [r for r in rocks if r['id'] in want]
    i, n = (int(x) for x in a.shard.split('/'))
    rocks = [r for k, r in enumerate(rocks) if k % n == i]
    case = json.loads((ROOT / a.case).read_text())
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    path = out / f'scan_shard{i}of{n}.jsonl'
    rows = []
    with path.open('w') as f:
        for rock in rocks:
            env0 = make_env_for_rock(rock, case)
            vis = {}
            try:
                import observe
                import tempfile
                env0.reset(seed=SEEDS[0])
                tmp = pathlib.Path(tempfile.mkdtemp()) / 'obs'
                observe.capture_observation(env0, tmp, case_id=rock['id'])
                oj = json.loads((tmp / 'observation.json').read_text())
                vis = oj.get('visible') or {}
            except Exception as e:
                vis = {'error': f'{type(e).__name__}: {e}'[:200]}
            simple = {}
            if vis and 'error' not in vis:
                h_act, h_why = eval_six.plan_height(vis, HEIGHT_RULE)
                w_act, w_why = eval_six.plan_width_rule(vis, HEIGHT_RULE, ACT)
                simple = {'height': h_act, 'width': w_act}
            for seed in SEEDS:
                for act in ACT.OPTIONS:
                    env = make_env_for_rock(rock, case)
                    env.reset(seed=seed)
                    r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis,
                                             seed=seed, record_trajectory=False).run_current()
                    row = {'rock': rock['id'], 'seed': seed, 'action': act,
                           'visible': vis, 'simple': simple,
                           'outcome': ('success' if r.get('success') else
                                       ('abort' if r.get('abort') else 'failure')),
                           'reason': r.get('reason'), 'final_x': r.get('final_x'),
                           'height_m': rock['height_m'], 'target_h_m': rock['target_h_m']}
                    rows.append(row)
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
            f.flush()
            print(json.dumps({'rock': rock['id'], 'rows': len(rows),
                              'simple': simple}, ensure_ascii=False), flush=True)
    print(json.dumps({'shard': a.shard, 'rocks': len(rocks), 'rows': len(rows)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
