"""Stage004：在真实扫描资产里筛"可站双前轮"的宽顶岩石（顶带 y 宽 >= 0.40 m）。"""
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent


def top_metrics(mesh):
    v = np.asarray(mesh.vertices)
    zmax = float(v[:, 2].max())
    band = v[v[:, 2] >= zmax - 0.015]
    return {'top_z': round(zmax, 4),
            'top_y_span': round(float(band[:, 1].max() - band[:, 1].min()), 4),
            'top_x_span': round(float(band[:, 0].max() - band[:, 0].min()), 4),
            'n_top': int(len(band))}


def main():
    roots = [ROOT / 'assets/v3/rocks', ROOT / 'assets/posed']
    rows = []
    for root in roots:
        for p in sorted(root.rglob('*')):
            if p.suffix.lower() not in ('.stl', '.obj', '.glb'):
                continue
            if 'vis' in p.name.lower():
                continue
            try:
                m = trimesh.load(str(p), force='mesh')
            except Exception:  # noqa: BLE001
                continue
            if len(m.vertices) == 0:
                continue
            tm = top_metrics(m)
            tm.update({'mesh': str(p.relative_to(ROOT)), 'root': root.name})
            rows.append(tm)
    # posed 多部件合成
    for d in sorted((ROOT / 'assets/posed').glob('s0_*')):
        parts = sorted((d / 'parts').glob('*.stl'))
        if not parts:
            continue
        try:
            m = trimesh.util.concatenate([trimesh.load(str(q), force='mesh') for q in parts])
        except Exception:  # noqa: BLE001
            continue
        tm = top_metrics(m)
        tm.update({'mesh': str(d.relative_to(ROOT)) + ' (parts merged)', 'root': 'posed'})
        rows.append(tm)
    rows.sort(key=lambda r: -r['top_y_span'])
    out = ROOT / 'runs/v3/stage004/wide_rock_scan.json'
    out.write_text(json.dumps({'schema': 'stage4-wide-rock-scan/v1',
                               'criterion': 'top band (within 15 mm of top) y span',
                               'rows': rows}, ensure_ascii=False, indent=2))
    print(json.dumps(rows[:12], ensure_ascii=False, indent=1))
    wide = [r for r in rows if r['top_y_span'] >= 0.40]
    print('wide_count', len(wide), 'of', len(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
