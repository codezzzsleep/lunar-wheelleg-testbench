#!/usr/bin/env python3
"""候选准入失败归因：每一个被拒绝的候选，究竟卡在哪一条门槛上。

动机（2026-11-11）：V8 的想象车在 look1 只采纳 2/6 + 0/4，look2 采纳 0/3，于是"两眼之后
还不行就停车"。但"0/3"本身不解释原因——是候选太差，还是门槛定得太紧？本脚本离线复算
每份候选的逐项指标与阈值的距离，并做阈值敏感性测试，不需要任何 API 调用、不跑物理。

    python3 scripts/v8/v8_admission_report.py --run runs/v8/main
    python3 scripts/v8/v8_admission_report.py --run runs/v8/main --json out.json
    python3 scripts/v8/v8_admission_report.py --run runs/v8/main --perturb 0.10

指标方向（来自 v5-admission/v1 阈值）：
  scale_ratio 要落在 [min,max]；hidden_frac / shell_contact / contour_iou 要 ≥ min；
  free_intrusion_frac 要 ≤ max。`ratio = 实测/阈值`，≥1 表示过线（方向已统一）。
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _rules(th):
    """返回 [(指标名, 比较方向, 阈值)]；方向 'ge' 表示实测应 ≥ 阈值。"""
    rules = [('hidden_frac', 'ge', th['hidden_frac_min']),
             ('shell_contact', 'ge', th['shell_contact_min']),
             ('free_intrusion_frac', 'le', th['free_intrusion_max']),
             ('contour_iou', 'ge', th['contour_iou_min'])]
    sr = th['scale_ratio']
    rules.append(('scale_ratio', 'ge', sr['min']))
    rules.append(('scale_ratio', 'le', sr['max']))
    return rules


def normalized(metric, direction, value, threshold):
    """统一成"实测相对阈值"的比值：≥1 = 过线。le 方向取反。"""
    if threshold in (None, 0):
        return None
    if direction == 'ge':
        return value / threshold
    return (threshold / value) if value > 0 else float('inf')


def analyse(run):
    run = pathlib.Path(run)
    out = []
    for dec in sorted(run.glob('*/looks/look*/T*/decide/target_decision.json')):
        d = json.loads(dec.read_text())
        th = d['thresholds']
        robot = dec.parts[-6] if len(dec.parts) >= 6 else '?'
        look = dec.parts[-4]
        target = dec.parts[-3]
        for c in d['candidates']:
            fails = []
            ratios = {}
            for metric, direction, threshold in _rules(th):
                v = c.get(metric)
                if v is None:
                    continue
                r = normalized(metric, direction, float(v), float(threshold))
                if r is None:
                    continue
                ratios[metric + ('_min' if direction == 'ge' else '_max')] = round(r, 4)
                if r < 1.0:
                    fails.append({'metric': metric, 'direction': direction,
                                  'value': round(float(v), 4), 'threshold': round(float(threshold), 4),
                                  'ratio': round(r, 4),
                                  'shortfall_pct': round((1 - r) * 100, 1)})
            fails.sort(key=lambda f: f['ratio'])
            out.append({'robot': robot, 'look': look, 'target': target, 'candidate': c['id'],
                        'admitted': bool(c['admitted']), 'fails': fails,
                        'blocking': fails[0]['metric'] if fails else None,
                        'ratios': ratios,
                        'footprint_cells': c.get('footprint_cells')})
    return out


def perturb(rows, run, delta):
    """把每条阈值整体放宽/收紧 delta（相对量），重新判准入，看结论稳不稳。"""
    decs = sorted(pathlib.Path(run).glob('*/looks/look*/T*/decide/target_decision.json'))
    res = {}
    for sign, tag in ((1, f'放宽 {int(delta*100)}%'), (-1, f'收紧 {int(delta*100)}%')):
        n_adm = 0
        detail = []
        for dec in decs:
            d = json.loads(dec.read_text()); th = d['thresholds']
            for c in d['candidates']:
                ok = True
                for metric, direction, threshold in _rules(th):
                    v = c.get(metric)
                    if v is None:
                        continue
                    # 放宽：ge 阈值下调、le 阈值上调；收紧反之
                    k = (1 - sign * delta) if direction == 'ge' else (1 + sign * delta)
                    t = float(threshold) * k
                    if direction == 'ge' and float(v) < t:
                        ok = False
                    if direction == 'le' and float(v) > t:
                        ok = False
                if ok:
                    n_adm += 1
                    detail.append(f"{dec.parts[-4]}/{dec.parts[-3]}/{c['id']}")
        res[tag] = {'admitted': n_adm, 'ids': detail}
    return res


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--json', default=None)
    ap.add_argument('--perturb', type=float, default=0.10,
                    help='阈值敏感性：整体放宽/收紧的相对幅度（默认 10%%）')
    a = ap.parse_args(argv[1:])

    rows = analyse(a.run)
    if not rows:
        raise SystemExit(f'{a.run} 下没有 target_decision.json')

    print(f'候选 {len(rows)} 份：采纳 {sum(r["admitted"] for r in rows)}，'
          f'拒绝 {sum(not r["admitted"] for r in rows)}')
    print()
    print('| 眼 | 目标 | 候选 | 采纳 | 卡在 | 差距 | 其余未过项 |')
    print('| --- | --- | --- | --- | --- | --- | --- |')
    for r in rows:
        if r['admitted']:
            print(f"| {r['look']} | {r['target']} | {r['candidate']} | ✅ | — | — | — |")
            continue
        b = r['fails'][0] if r['fails'] else None
        others = '、'.join(f"{f['metric']} {f['ratio']:.3f}" for f in r['fails'][1:]) or '—'
        gap = (f"{b['value']} vs {b['threshold']}（差 {b['shortfall_pct']}%）" if b else '—')
        print(f"| {r['look']} | {r['target']} | {r['candidate']} | ❌ | "
              f"{b['metric'] if b else '—'} | {gap} | {others} |")

    # 归因汇总：哪条门槛最常是"第一张拒签"
    from collections import Counter
    cnt = Counter(r['blocking'] for r in rows if not r['admitted'])
    print()
    print('**否决原因分布（按最严重的那条计）**：' +
          '、'.join(f'{k} {v} 次' for k, v in cnt.most_common()))

    sens = perturb(rows, a.run, a.perturb)
    print()
    print(f'**阈值敏感性（整体放宽/收紧 {int(a.perturb*100)}%）**：')
    for tag, v in sens.items():
        ids = '、'.join(v['ids']) if v['ids'] else '（无）'
        print(f'- {tag}: 采纳 {v["admitted"]} 份 {ids}')

    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(
            {'run': a.run, 'candidates': rows, 'sensitivity': sens}, indent=2, ensure_ascii=False))
        print(f'\n已写 {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
