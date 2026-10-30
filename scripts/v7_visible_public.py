"""从某次观测导出**公开可见量**（供规划/复核），避免跨案例借用别对象的可见量。

  .venv/bin/python scripts/v7_visible_public.py --observation runs/unseen/recovery_r3/obs_R03 \
      --out runs/unseen/delivery_v7/v7_20261030_r1/observations/R03_visible_public.json
"""
import argparse
import json
import pathlib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--observation', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    src = pathlib.Path(a.observation)
    obs = json.loads((src / 'observation.json').read_text())
    vis = dict(obs.get('visible') or {})
    vis['case_id'] = obs.get('case_id')
    vis['observation_id'] = obs.get('observation_id')
    vis['source'] = str(src)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(vis, ensure_ascii=False, indent=2))
    print(json.dumps({'out': str(out), 'case_id': vis.get('case_id'),
                      'x_front': vis.get('x_front'), 'W_vis': vis.get('W_vis'),
                      'H_vis': vis.get('H_vis')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
