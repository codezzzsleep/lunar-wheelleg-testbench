"""
分析器：只读显式指定的本批 results.jsonl，输出主表（E2 / F）。

  .venv/bin/python scripts/analyze_unseen.py --input runs/unseen/eval/<id>/results.jsonl \
      --protocol plans/unseen_v2_protocol.json --out runs/unseen/eval/<id>

规则：
  · 重复键、非法行、缺失键 -> 明确诊断；partial 必须显式 --allow-partial 并标注；
  · 全 ERROR 不生成成功报告；
  · 成功/刹停(abort)/翻覆/卡住/越界/超时/ERROR 分开计数；
  · 完成率与安全停止分开报告；同时给全部回合代价与成功回合用时。
"""
import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
C_FAIL, C_ABORT = 60.0, 40.0


def load(path):
    rows, bad = [], []
    for i, line in enumerate(pathlib.Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            bad.append({'line': i, 'error': str(e)})
            continue
        need = ('case_id', 'method', 'seed', 'reason')
        if not all(k in r for k in need):
            bad.append({'line': i, 'error': f'缺字段 {[k for k in need if k not in r]}'})
            continue
        rows.append(r)
    return rows, bad


def cost_of(r):
    if r['reason'] == 'success':
        return float(r.get('t_end') or C_FAIL)
    if r['reason'] == 'abort':
        return C_ABORT
    return C_FAIL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--protocol', default=None)
    ap.add_argument('--out', required=True)
    ap.add_argument('--allow-partial', action='store_true')
    a = ap.parse_args()

    rows, bad = load(a.input)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    diag = {'n_rows': len(rows), 'n_bad_lines': len(bad),
            'bad': bad[:20], 'partial': False, 'missing': []}

    keys = Counter((r['case_id'], r['method'], r['seed']) for r in rows)
    dup = [list(k) for k, v in keys.items() if v > 1]
    diag['duplicate_keys'] = dup

    if a.protocol and pathlib.Path(a.protocol).exists():
        proto = json.loads(pathlib.Path(a.protocol).read_text())
        want = {(c['case_id'], m['name'], int(s))
                for c in proto['cases'] for m in proto['methods']
                for s in proto['seeds']}
        miss = sorted(want - set(keys))
        diag['missing'] = [list(k) for k in miss[:50]]
        diag['n_missing'] = len(miss)
        diag['partial'] = bool(miss) or bool(dup)

    if not rows:
        diag['status'] = 'NO_DATA'
        (out / 'analysis.json').write_text(json.dumps(diag, indent=2, ensure_ascii=False))
        print('无有效结果行：不生成成功报告')
        return 2
    if diag['partial'] and not a.allow_partial:
        diag['status'] = 'PARTIAL_REQUIRES_FLAG'
        (out / 'analysis.json').write_text(json.dumps(diag, indent=2, ensure_ascii=False))
        print(f"批次不完整（缺 {diag.get('n_missing', 0)}，重复 {len(dup)}），"
              f'需 --allow-partial')
        return 1

    by_method = defaultdict(list)
    for r in rows:
        by_method[r['method']].append(r)

    table = []
    for m, rs in sorted(by_method.items()):
        n = len(rs)
        cnt = Counter(r['reason'] for r in rs)
        succ = [r for r in rs if r['reason'] == 'success']
        times = [float(r['t_end']) for r in succ if r.get('t_end')]
        table.append({
            'method': m, 'n': n,
            'success': cnt.get('success', 0),
            'abort': cnt.get('abort', 0),
            'tipped': cnt.get('tipped', 0),
            'stuck': cnt.get('stuck', 0),
            'out_of_bounds': cnt.get('out_of_bounds', 0),
            'out_of_field': cnt.get('out_of_field', 0),
            'time_limit': cnt.get('time_limit', 0),
            'success_rate': round(cnt.get('success', 0) / n, 4) if n else None,
            'safe_stop_rate': round(cnt.get('abort', 0) / n, 4) if n else None,
            'mean_cost_s': round(sum(cost_of(r) for r in rs) / n, 3) if n else None,
            'mean_success_time_s': round(sum(times) / len(times), 3) if times else None,
        })

    by_group = defaultdict(lambda: Counter())
    for r in rows:
        by_group[(r['case_id'], r['method'])][r['reason']] += 1
    grouped = [{'case_id': k[0], 'method': k[1], 'reasons': dict(v)}
               for k, v in sorted(by_group.items())]

    analysis = {'diagnostics': diag, 'main_table': table, 'by_case': grouped,
                'n_independent_observations': len({r['case_id'] for r in rows}),
                'note': '相关案例（同一观测的多背面/通道）不作为独立样本'}
    (out / 'analysis.json').write_text(json.dumps(analysis, indent=2, ensure_ascii=False))

    hdr = f"{'方法':<10}{'n':>4}{'成功':>6}{'刹停':>6}{'翻覆':>6}{'越界':>6}{'成功率':>9}{'均代价':>9}"
    print(hdr)
    for t in table:
        print(f"{t['method']:<10}{t['n']:>4}{t['success']:>6}{t['abort']:>6}"
              f"{t['tipped']:>6}{t['out_of_bounds']:>6}"
              f"{(t['success_rate'] or 0):>9.3f}{(t['mean_cost_s'] or 0):>9.1f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
