"""V8 赛后复盘：跑完之后才拿真实形状来比（机器人在路上从不用真值）。

    python3 scripts/v8/v8_eval.py --run runs/v8/<run>

对想象的车，逐眼、逐块石头、逐份候选：
  - 想象出的占地与真实占地的 IoU
  - 背面误差：沿机器人前进方向（世界 x），想象的最远端 - 真实的最远端（负数 = 想象得太短）
  - 侧面误差：想象的最右端 - 真实的最右端（y 越小越靠右；负数 = 想象得比真实更向右凸）
  - 自检结论（采纳 / 拒绝）
汇总：被采纳的候选背面误差的范围；被拒绝的候选里有多少是"想得太短"（如果信了会撞）。
三台车的结果并列：到达 / 撞 / 停车，看了几眼，用时，离真实石块最近的距离。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import v8_scene as S, v8_nav as N  # noqa: E401,E402


def truth_footprints(run):
    """直接从场景资产算真实占地（与 v8_run.true_footprints 同一方法：凸包）。"""
    from matplotlib.path import Path as MP
    from scipy.spatial import ConvexHull
    out = {}
    for key, r in S.ROCKS.items():
        obj, _ = S.rock_asset_uniform(r['rock'], r['height'])
        V = np.array([[float(t) for t in l.split()[1:3]] for l in open(obj) if l.startswith('v ')])
        th = np.radians(r['yaw']); R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        P = V @ R.T + [r['x'], r['y']]
        h = ConvexHull(P)
        out[key] = MP(P[h.vertices]).contains_points(np.c_[N.GX.ravel(), N.GY.ravel()]).reshape(N.GX.shape)
    return out


def which_rock(cells, truth):
    return max(truth, key=lambda k: int((truth[k] & cells).sum()))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--run', required=True)
    a = ap.parse_args()
    run = pathlib.Path(a.run)
    truth = truth_footprints(run)
    rep = {'schema': 'v8-eval/v1', 'run': str(run), 'robots': {}, 'imagination': []}
    for d in sorted(p for p in run.iterdir() if (p / 'summary.json').exists()):
        s = json.loads((d / 'summary.json').read_text())
        ev = [json.loads(l) for l in (d / 'events.jsonl').read_text().splitlines() if l.strip()]
        z = np.load(d / 'traj.npz'); q = z['qpos']
        clr = N.clearance(truth['A'] | truth['B'])
        i = np.clip(((q[:, 0] - N.X0) / N.RES).astype(int), 0, N.NX - 1); j = np.clip(((q[:, 1] - N.Y0) / N.RES).astype(int), 0, N.NY - 1)
        rep['robots'][d.name] = {'result': s['result'], 'looks': s['looks'], 'sim_time_s': s['sim_time_s'],
                                 'min_center_distance_to_rock_m': round(float(clr[i, j].min()), 3),
                                 'collision': s.get('collision')}
        looks = d / 'looks'
        for ld in sorted(looks.glob('look*')) if looks.exists() else []:
            if not ld.is_dir() or ld.name.endswith('_replay'):
                continue
            for td in sorted(ld.glob('T*')):
                dec = td / 'decide' / 'target_decision.json'
                if not dec.exists():
                    continue
                D = json.loads(dec.read_text()); cells = np.load(td / 'cells.npy'); key = which_rock(cells, truth)
                T = truth[key]
                tx = float(N.GX[T].max()); ty = float(N.GY[T].min())
                for c in D['candidates']:
                    fp = np.load(td / 'decide' / f'footprint_{c["id"]}.npy')
                    row = {'robot': d.name, 'look': ld.name, 'target': td.name, 'rock': key, 'candidate': c['id'], 'admitted': c['admitted'],
                           'footprint_iou': round(float((fp & T).sum() / max(1, (fp | T).sum())), 3),
                           'back_err_m': round(float(N.GX[fp].max()) - tx, 3) if fp.any() else None,
                           'right_err_m': round(float(N.GY[fp].min()) - ty, 3) if fp.any() else None,
                           'metrics': {k: c[k] for k in ('scale_ratio', 'hidden_frac', 'shell_contact', 'free_intrusion_frac', 'contour_iou')}}
                    rep['imagination'].append(row)
    adm = [r for r in rep['imagination'] if r['admitted'] and r['back_err_m'] is not None]
    rej = [r for r in rep['imagination'] if not r['admitted'] and r['back_err_m'] is not None]
    rep['summary'] = {
        'admitted': len(adm), 'rejected': len(rej),
        'admitted_back_err_range_m': [min(r['back_err_m'] for r in adm), max(r['back_err_m'] for r in adm)] if adm else None,
        'admitted_footprint_iou_range': [min(r['footprint_iou'] for r in adm), max(r['footprint_iou'] for r in adm)] if adm else None,
        'rejected_too_short': sum(1 for r in rej if r['back_err_m'] < -0.05),
    }
    (run / 'eval.json').write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print(json.dumps({'robots': rep['robots'], 'summary': rep['summary']}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
