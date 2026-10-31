"""为扫描的每个（案例, 尺寸档）真实采集一次观测，并导出公开可见量。

  /opt/lunar/bin/python scripts/v7_scan_observations.py --out <dir>
"""
import argparse, json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', default='R01,R02,R03,R04')
    ap.add_argument('--scales', default='0.9,1.0,1.1')
    ap.add_argument('--assets', default='runs/unseen/delivery_v7/v7_20261030_r1/scan_assets')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = ROOT / a.out; (out / 'cases').mkdir(parents=True, exist_ok=True)
    rows = []
    for c in a.cases.split(','):
        base = json.loads((ROOT / f'cases/unseen_v1/{c}.json').read_text())
        for s in [float(x) for x in a.scales.split(',')]:
            mesh = ROOT / a.assets / f'{c}_s{s:g}' / 'body.stl'
            if not mesh.exists():
                raise SystemExit(f'缺缩放网格：{mesh}')
            case = dict(base)
            case['mesh'] = str(mesh.relative_to(ROOT))
            case['case_id'] = f'{c}_s{s:g}'
            cpath = out / 'cases' / f'{c}_s{s:g}.json'
            cpath.write_text(json.dumps(case, ensure_ascii=False, indent=2))
            obs_dir = out / f'{c}_s{s:g}'
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/observe.py'),
                                '--case', str(cpath), '--out', str(obs_dir),
                                '--observation-id', f'{c}_s{s:g}'],
                               cwd=str(ROOT), capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f'{c}@{s} 观测失败：{r.stderr.strip().splitlines()[-1:]}')
            v = subprocess.run([sys.executable, str(ROOT / 'scripts/v7_visible_public.py'),
                                '--observation', str(obs_dir),
                                '--out', str(out / f'{c}_s{s:g}_visible.json')],
                               cwd=str(ROOT), capture_output=True, text=True)
            if v.returncode != 0:
                raise SystemExit(f'{c}@{s} 可见量导出失败：{v.stderr}')
            vis = json.loads((out / f'{c}_s{s:g}_visible.json').read_text())
            rows.append({'case': c, 'scale': s, 'obs_dir': str(obs_dir.relative_to(ROOT)),
                         'visible': {k: vis.get(k) for k in ('x_front', 'W_vis', 'H_vis', 'case_id')}})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (out / 'observations_index.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(json.dumps({'n': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
