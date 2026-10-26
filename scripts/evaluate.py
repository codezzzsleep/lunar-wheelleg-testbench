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

    res = {'label': a.label or pathlib.Path(a.checkpoint).stem,
           'checkpoint': a.checkpoint,
           'checkpoint_actor_checksum': ppo.actor_checksum(params),
           'manifest': a.manifest, 'n_episodes': len(manifest),
           'deterministic': det, 'stochastic': sto}
    (out / 'eval.json').write_text(json.dumps(res, indent=2, ensure_ascii=False))

    from collections import Counter
    print(f"{res['label']:28s} det {det['success']}/{det['n']}={det['success_rate']:.3f} "
          f"倾覆 {det['tip_rate']:.3f} | stoch {sto['success']}/{sto['n']}="
          f"{sto['success_rate']:.3f} 倾覆 {sto['tip_rate']:.3f} | "
          f"回报 {sto['mean_return']:.1f}")
    print('  det 结局:', dict(Counter(e['reason'] for e in det['per_episode'])))
    print('  stoch 结局:', dict(Counter(e['reason'] for e in sto['per_episode'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
