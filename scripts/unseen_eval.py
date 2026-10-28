"""
固定对照评测器（E2 / 工作包 F 的执行端）。

  .venv/bin/python scripts/unseen_eval.py --protocol plans/unseen_v2_protocol.json \
      --out runs/unseen/eval/<run_id> --workers 1

要点：
  · 期望键集合由协议给出：method × case × seed，缺一项就记录 missing，不按实际行数推断；
  · 同键多条 -> 记为 duplicate 并拒绝；
  · 每行记录初态、结局、动作指纹、候选身份、耗时、异常 traceback；
  · 结果可为负，不做筛选。
"""
import argparse
import json
import pathlib
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import hypotheses as HYP
import runner
import skills
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def build_spec(case, posed_dir, seed):
    # 目标点要留出"稳定保持 1 s"的行驶距离（约 0.85 m），否则越过目标就 out_of_field
    spec = terrain.make_spec(kind='flat', seed=int(seed), objects=[], goal_x=2.6,
                             name=f"eval_{case['case_id']}")
    spec['channel'] = {'center_y': 0.0, 'half_width': float(case.get('channel_half', 1.2))}
    spec['init_perturbation'] = case.get('init_perturbation',
                                         {'lateral_m': 0.05, 'yaw_rad': 0.03})
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(posed_dir), 'x': float(case['obstacle_x']),
                        'y': 0.0, 'yaw_deg': 0.0, 'target_height_m': None}]
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.20], 'pitch_deg': -12.0, 'fovy': 70.0}
    return spec


def run_one(case, posed_dir, method, option, seed, visible, time_limit=15.0):
    spec = build_spec(case, posed_dir, seed)
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                   v_ref=1.0, tip_deg=60.0)
    r = runner.EpisodeRunner(env, skills.make_skill(option),
                             visible=visible or {}, seed=seed)
    return r.run_with_seed(seed)


def expected_keys(protocol):
    keys = set()
    for case in protocol['cases']:
        for m in protocol['methods']:
            for s in protocol['seeds']:
                keys.add((case['case_id'], m['name'], int(s)))
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--allow-partial', action='store_true')
    a = ap.parse_args()

    proto = json.loads(pathlib.Path(a.protocol).read_text())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows, errors = [], []
    want = expected_keys(proto)

    for case in proto['cases']:
        obs_dir = ROOT / case['observations'] if not pathlib.Path(case['observations']).is_absolute() \
            else pathlib.Path(case['observations'])
        obs = json.loads((pathlib.Path(obs_dir) / 'observation.json').read_text())
        visible = obs['visible']
        for m in proto['methods']:
            posed_dir = case.get('hypotheses', {}).get(m['name']) or case.get('truth_posed')
            if not posed_dir:
                for s in proto['seeds']:
                    errors.append({'case': case['case_id'], 'method': m['name'],
                                   'seed': int(s), 'error': 'no_candidate_dir',
                                   'traceback': ''})
                continue
            for s in proto['seeds']:
                t0 = time.time()
                try:
                    r = run_one(case, pathlib.Path(posed_dir), m['name'],
                                m['option'], int(s), visible)
                    rows.append({'case_id': case['case_id'], 'method': m['name'],
                                 'seed': int(s), 'option': m['option'],
                                 'hypothesis': m.get('hypothesis'),
                                 'reason': r['reason'], 'success': r['success'],
                                 'abort': r.get('abort', False),
                                 't_end': r['t_end'], 'x': r['final_x'],
                                 'contact': r['contact'],
                                 'belly_contact': r['belly_contact'],
                                 'triggered': r['triggered'],
                                 'brake_steps': r['brake_steps'],
                                 'q0': r['q0'],
                                 'action_fingerprint': r['action_fingerprint'],
                                 'wall_s': round(time.time() - t0, 3),
                                 'candidate_dir': str(posed_dir)})
                except Exception as e:
                    errors.append({'case': case['case_id'], 'method': m['name'],
                                   'seed': int(s), 'error': f'{type(e).__name__}: {e}',
                                   'traceback': traceback.format_exc()[-800:]})

    # ---- 完整性检查：按**协议期望键**，不从实际行反推 ----
    got = {}
    for r in rows:
        k = (r['case_id'], r['method'], r['seed'])
        got.setdefault(k, []).append(r)
    missing = sorted(want - set(got))
    dup = sorted(k for k, v in got.items() if len(v) > 1)
    unexpected = sorted(set(got) - want)
    complete = not missing and not dup

    (out / 'results.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
    (out / 'errors.jsonl').write_text(
        '\n'.join(json.dumps(e, ensure_ascii=False) for e in errors) + '\n')
    summary = {'protocol': str(a.protocol),
               'n_expected': len(want), 'n_rows': len(rows),
               'n_missing': len(missing), 'n_duplicate': len(dup),
               'n_unexpected': len(unexpected), 'n_errors': len(errors),
               'complete': complete,
               'missing_keys': [list(k) for k in missing[:50]],
               'duplicate_keys': [list(k) for k in dup[:50]],
               'unexpected_keys': [list(k) for k in unexpected[:20]]}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False))
    if not complete and not a.allow_partial:
        return 1
    return 0 if len(rows) else 2


if __name__ == '__main__':
    sys.exit(main())
