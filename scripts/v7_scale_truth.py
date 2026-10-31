"""为扫描准备"真值实体 × 尺寸档"资产：等比缩放真实石头网格（保持贴地）。

不缩放机器人、地形与终点。缩放围绕案例锚点 a=(obstacle_x, 0, 0)，缩放后再把底面贴回 z=0。
输出 <out>/<CASE>_s<scale>/body.stl，并打印/断言三个方向的包围盒比例。

  .venv/bin/python scripts/v7_scale_truth.py --out runs/.../scan_assets
"""
import argparse, json, pathlib
import numpy as np, trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', default='R01,R02,R03,R04')
    ap.add_argument('--scales', default='0.9,1.0,1.1')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = ROOT / a.out
    report = []
    for c in a.cases.split(','):
        case = json.loads((ROOT / f'cases/unseen_v1/{c}.json').read_text())
        src = ROOT / case['mesh']
        base = trimesh.load(str(src), force='mesh', process=False)
        b0 = base.bounds
        # 案例网格是**局部坐标**（由案例里的 obstacle_x 负责摆放），
        # 因此缩放要围绕局部原点，围绕世界锚点会把石头移出路径。
        anchor = np.array([0.0, 0.0, 0.0])
        for s in [float(x) for x in a.scales.split(',')]:
            m = base.copy()
            v = np.asarray(m.vertices, dtype=float)
            v = anchor + s * (v - anchor)
            # 贴地：缩放后把最低点放回 0（不改变 x/y）
            v[:, 2] -= v[:, 2].min()
            m.vertices = v
            d = out / f'{c}_s{s:g}'
            d.mkdir(parents=True, exist_ok=True)
            m.export(d / 'body.stl')
            # posed_dir 资产按**世界坐标**使用（identity 放置），
            # 所以还要导出一份已经摆到 obstacle_x 的世界网格，否则石头会落在原点、压住机器人。
            w = m.copy()
            vv = np.asarray(w.vertices, dtype=float).copy()
            vv[:, 0] += float(case['obstacle_x'])
            w.vertices = vv
            w.export(d / 'body_world.stl')
            b1 = m.bounds
            ratio = (b1[1] - b1[0]) / np.maximum(b0[1] - b0[0], 1e-9)
            ok = np.allclose(ratio, s, atol=2e-3)
            rec = {'case': c, 'scale': s, 'dir': str(d.relative_to(ROOT)),
                   'bbox_before': b0.round(6).tolist(), 'bbox_after': b1.round(6).tolist(),
                   'ratio': ratio.round(5).tolist(), 'ratio_ok': bool(ok),
                   'anchor': anchor.tolist(),
                   'world_x_center_after': float(case['obstacle_x'] + (b1[0][0] + b1[1][0]) / 2),
                   'world_mesh': str((d / 'body_world.stl').relative_to(ROOT))}
            report.append(rec)
            print(json.dumps(rec, ensure_ascii=False))
    (out / 'scale_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    bad = [r for r in report if not r['ratio_ok']]
    if bad:
        raise SystemExit(f'包围盒比例不符：{[(r["case"], r["scale"], r["ratio"]) for r in bad]}')


if __name__ == '__main__':
    main()
