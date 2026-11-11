#!/usr/bin/env python3
"""V7 影子实验的门槛工作点：自检的"误拒率"与 5 cm 余量的留一检验。

动机（2026-11-11）：`docs/v8/SPEC_V8.md` 用"被采纳想象背面误差最大 5.0 cm"直接当规划余量。
这句话只说明**样本内最大值**，没有回答两个更要紧的问题：
  (1) 自检的门槛在这 64 份样本上是偏严还是偏松？
  (2) 换一组条件（留一太阳方位）时，5 cm 还盖得住吗？

    python3 scripts/v7/v7_gate_report.py
    python3 scripts/v7/v7_gate_report.py --json out.json

判据沿用数据自带的字段：`admitted`（自检结论）、`hidden_iou`（背面与真值的重合度）、
`rear_err_m`（背面误差，正=想长了、负=想短了）。离线、不跑物理、不调 API。
"""
import argparse
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'runs/v7/shadow_exp/eval_rows.json'


def pct(v, q):
    v = sorted(v)
    if not v:
        return None
    i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[i]


def analyse(path):
    rows = [r for r in json.loads(pathlib.Path(path).read_text()) if r.get('status') == 'ok']
    bad = [r for r in rows if (r.get('hidden_iou') or 0) < 0.5]
    good = [r for r in rows if (r.get('hidden_iou') or 0) >= 0.6]
    adm = [r for r in rows if r.get('admitted')]
    rep = {'n': len(rows), 'bad': len(bad), 'good': len(good), 'admitted': len(adm),
           'bad_rejected': sum(1 for r in bad if not r.get('admitted')),
           'good_admitted': sum(1 for r in good if r.get('admitted')),
           'good_wrongly_rejected': sum(1 for r in good if not r.get('admitted'))}
    for name, grp in (('admitted', adm),
                      ('good_rejected', [r for r in good if not r.get('admitted')]),
                      ('bad_rejected', bad)):
        v = [r['contour_iou'] for r in grp if r.get('contour_iou') is not None]
        rep[f'contour_{name}'] = {'n': len(v), 'p25': pct(v, .25), 'p50': pct(v, .5), 'p75': pct(v, .75)}
    err = [abs(r['rear_err_m']) for r in adm if r.get('rear_err_m') is not None]
    rep['admitted_abs_rear_err'] = {'n': len(err), 'p50': pct(err, .5),
                                    'p90': pct(err, .9), 'max': max(err) if err else None}
    # 留一太阳条件：用其余条件的最大误差去预测被留出条件，看是否被超出
    loo = {}
    suns = sorted({r.get('sun') for r in rows if r.get('sun')})
    for s in suns:
        rest = [abs(r['rear_err_m']) for r in adm
                if r.get('sun') != s and r.get('rear_err_m') is not None]
        held = [abs(r['rear_err_m']) for r in adm
                if r.get('sun') == s and r.get('rear_err_m') is not None]
        if rest and held:
            loo[s] = {'predicted_max_m': max(rest), 'held_max_m': max(held),
                      'exceeded': max(held) > max(rest)}
    rep['leave_one_sun_out'] = loo
    return rep


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--rows', default=str(DEFAULT))
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv[1:])
    r = analyse(a.rows)

    print(f"样本 {r['n']} 份（ok）：坏(隐藏 IoU<0.5) {r['bad']}、好(≥0.6) {r['good']}、采纳 {r['admitted']}")
    print(f"  · 坏的全被拒：{r['bad_rejected']}/{r['bad']}")
    print(f"  · 好的被采纳：{r['good_admitted']}/{r['good']}"
          f"（误拒 {r['good_wrongly_rejected']} 份 = {100*r['good_wrongly_rejected']/max(1,r['good']):.0f}%）")
    print()
    print('contour_iou 分位（p25/p50/p75）：')
    for k in ('admitted', 'good_rejected', 'bad_rejected'):
        d = r[f'contour_{k}']
        if d['n']:
            print(f"  {k:14s} n={d['n']:2d}  {d['p25']:.3f} / {d['p50']:.3f} / {d['p75']:.3f}")
    e = r['admitted_abs_rear_err']
    print()
    print(f"被采纳样本的 |背面误差|：n={e['n']}  p50={e['p50']:.3f}  p90={e['p90']:.3f}  max={e['max']:.3f} m")
    print('留一太阳条件（其余条件 max 预测被留出条件的 max）：')
    for s, d in r['leave_one_sun_out'].items():
        flag = '超出' if d['exceeded'] else '未超出'
        print(f"  {s:10s} 预测 {d['predicted_max_m']:.3f} m → 实际 {d['held_max_m']:.3f} m  {flag}")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(r, indent=2, ensure_ascii=False))
        print(f'\n已写 {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
