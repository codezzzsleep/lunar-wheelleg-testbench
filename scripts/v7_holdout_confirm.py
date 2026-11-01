"""三初态确认（下一批任务书：扫描初态修正）。

对指定石头，用**预先冻结的非零扰动**生成三组不同起始位姿：
  seed 7  : lateral  0.04 m, yaw  0.03 rad
  seed 11 : lateral -0.05 m, yaw -0.04 rad
  seed 13 : lateral  0.06 m, yaw  0.05 rad
保存起始 qpos/qvel 与哈希，确认三组互不相同；每组各自采集可见量。

  python scripts/v7_holdout_confirm.py --rocks P04,P06 --out <dir>
"""
import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np

import observe
import runner
import skills
import v7_holdout_scan as HS

FROZEN_POSES = {
    7: {'lateral_m': 0.04, 'yaw_rad': 0.03},
    11: {'lateral_m': -0.05, 'yaw_rad': -0.04},
    13: {'lateral_m': 0.06, 'yaw_rad': 0.05},
}


def state_hash(env):
    q = np.concatenate([env.data.qpos, env.data.qvel]).round(9)
    return hashlib.sha256(q.tobytes()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rocks', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--actions', default='R1,L2,D1,D2,L1,R2,S1')
    a = ap.parse_args()
    pool = {r['id']: r for r in
            json.loads((ROOT / 'assets/procedural_rocks/index.json').read_text())['rocks']}
    case = json.loads((ROOT / 'cases/unseen_v1/R02.json').read_text())
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    summary = {'schema': 'holdout-confirm/v1', 'poses': FROZEN_POSES, 'rocks': {}}
    for rid in a.rocks.split(','):
        rock = pool[rid]
        rec = {'height_m': rock['height_m'], 'sha256': rock['sha256'], 'seeds': {}}
        for seed, pose in FROZEN_POSES.items():
            env = HS.make_env_for_rock(rock, case)
            # 扰动在 __init__ 里读进 self.init_perturbation，必须直接改它
            env.init_perturbation = {'lateral': abs(float(pose['lateral_m'])),
                                     'yaw': abs(float(pose['yaw_rad']))}
            env.reset(seed=seed)
            sh = state_hash(env)
            d = out / rid / f'seed{seed}'
            observe.capture_observation(env, d, case_id=rid)
            oj = json.loads((d / 'observation.json').read_text())
            vis = oj.get('visible') or {}
            acts = {}
            for act in a.actions.split(','):
                env2 = HS.make_env_for_rock(rock, case)
                env2.init_perturbation = {'lateral': abs(float(pose['lateral_m'])),
                                          'yaw': abs(float(pose['yaw_rad']))}
                env2.reset(seed=seed)
                r = runner.EpisodeRunner(env2, skills.make_skill(act), visible=vis,
                                         seed=seed).run_current()
                acts[act] = {'success': bool(r.get('success')), 'reason': r.get('reason'),
                             'final_x': r.get('final_x')}
            rec['seeds'][seed] = {'pose': pose, 'state_hash': sh,
                                  'qpos0': [round(float(v), 6) for v in env.data.qpos[:7]],
                                  'visible': vis, 'actions': acts}
            print(json.dumps({'rock': rid, 'seed': seed, 'state_hash': sh,
                              'x_front': vis.get('x_front'),
                              'ok': sum(1 for v in acts.values() if v['success'])},
                             ensure_ascii=False), flush=True)
        hashes = [v['state_hash'] for v in rec['seeds'].values()]
        rec['distinct'] = len(set(hashes)) == len(hashes)
        summary['rocks'][rid] = rec
    (out / 'confirm.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v['distinct'] for k, v in summary['rocks'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
