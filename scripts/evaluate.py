"""
用固定清单评估一个 checkpoint（可跨 P/G 共用同一清单）。

  .venv/bin/python scripts/evaluate.py --checkpoint runs/pg_v2/P_s0/checkpoints/final.npz \
      --manifest scenes/test_common.json --config configs/P_frozen.json --out runs/eval_x

约定：
  · 评估不更新参数、不更新任何统计；每个 (scene, episode_seed) 重新播种。
  · 两种口径分别报告并标注：deterministic（策略均值）与 stochastic（固定种子采样）。
  · 逐场景逐种子结果全部保存，不只给平均。
  · test 清单在协议冻结后才使用。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ppo
import terrain
import train


def load_manifest(path, episode_seeds):
    specs = [dict(s, objects=s.get('objects', []))
             for s in json.loads(pathlib.Path(path).read_text())]
    return [{'scene': s['name'], 'scene_id': terrain.scene_identity(s),
             'episode_seed': int(e), 'spec': s}
            for s in specs for e in episode_seeds]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--checkpoint', required=True)
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--config', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', default=None)
    a = ap.parse_args()

    cfg = json.loads(pathlib.Path(a.config).read_text())
    params = dict(np.load(a.checkpoint))
    manifest = load_manifest(a.manifest, cfg.get('eval_episode_seeds', [0]))

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    det = train.evaluate(params, manifest, cfg, True)
    sto = train.evaluate(params, manifest, cfg, False)

    # 确定性口径按**场景**统计（每个场景只用 episode_seed=0），
    # 多初态另列，避免把同一场景的重复当成独立样本。
    per_scene = [e for e in det['per_episode'] if e['episode_seed'] == 0]
    scene_succ = sum(1 for e in per_scene if e['success'])
    per_seed = {}
    for e in det['per_episode']:
        per_seed.setdefault(e['episode_seed'], []).append(1 if e['success'] else 0)

    res = {'label': a.label or pathlib.Path(a.checkpoint).stem,
           'deterministic_per_scene': {
               'n_scenes': len(per_scene), 'success': scene_succ,
               'success_rate': round(scene_succ / len(per_scene), 4) if per_scene else None},
           'deterministic_across_init_seeds': {
               'n_init_seeds': len(per_seed),
               'per_seed_rate': {k: round(sum(v) / len(v), 4)
                                 for k, v in sorted(per_seed.items())}},
           'checkpoint': a.checkpoint,
           'checkpoint_actor_checksum': ppo.actor_checksum(params),
           'manifest': a.manifest, 'n_episodes': len(manifest),
           'deterministic': det, 'stochastic': sto}
    (out / 'eval.json').write_text(json.dumps(res, indent=2, ensure_ascii=False))

    from collections import Counter
    ps = res['deterministic_per_scene']
    print(f"{res['label']:26s} det 按场景 {ps['success']}/{ps['n_scenes']}="
          f"{ps['success_rate']} | det 多初态 {det['success_rate']} | "
          f"stoch {sto['success_rate']} (n={sto['n']}) | 回报 {sto['mean_return']:.1f}")
    print('  det 结局:', dict(Counter(e['reason'] for e in det['per_episode'])))
    print('  stoch 结局:', dict(Counter(e['reason'] for e in sto['per_episode'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
