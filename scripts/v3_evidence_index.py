"""G6：把主要 run 的 result.json 汇总成证据索引（run -> 指标 -> 复现）。"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 2026-11-11：原实现只写死 7 个组，而仓库里实际有 12 个组（stage004..stage008、control 等），
# 导致本文件长期"自称自动生成、实则无法由脚本复现"（旧版本 130 行里 42 行指向不存在的目录、
# 磁盘上另有 55 个 run 没进索引）。改为按磁盘扫描，顺序稳定，重生成结果与仓库一致。
rows = []
_all_results = sorted((ROOT / 'runs/v3').glob('*/*/result.json'))
for res in _all_results:
    if True:
        try:
            d = json.loads(res.read_text())
        except Exception:  # noqa: BLE001
            continue
        rel = res.relative_to(ROOT)
        st = res.parent / 'status.json'
        status = json.loads(st.read_text()).get('status') if st.exists() else None
        metrics = {}
        for k in ('soil', 'speed_mps', 'step_h_m', 'final_x', 'tilt_max_deg',
                  'robot_mass_kg', 'robot_weight_n', 'blocked_at', 'terminated'):
            if k in d:
                metrics[k] = d[k]
        if 'phases' in d and isinstance(d['phases'], list):
            metrics['phases'] = len(d['phases'])
            metrics['ok_phases'] = sum(1 for p in d['phases'] if p.get('ok'))
        if 'rows' in d:
            metrics['actions'] = len(d['rows'])
            metrics['ok_actions'] = sum(1 for r in d['rows'] if r.get('success'))
            metrics['unified_actions'] = sum(1 for r in d['rows'] if r.get('unified'))
        rows.append({'run': str(rel.parent),
                     'schema': d.get('schema'), 'status': status,
                     'all_ok': d.get('all_ok', d.get('passed')),
                     'metrics': metrics})
out = ROOT / 'runs/v3/evidence_index.json'
out.write_text(json.dumps({'schema': 'v3-evidence-index/v1', 'n': len(rows),
                           'rows': rows}, ensure_ascii=False, indent=2))
# 范围声明写进生成物：本索引只覆盖 runs/v3/*；v4–v8 的证据见 docs/DELIVERY.md。
NOTE = ('> 本文件由 `scripts/v3_evidence_index.py` 生成，**只覆盖 v3 批次**（`runs/v3/*`）。'
        'v4–v8 的证据与结论矩阵见 `docs/DELIVERY.md`；本文件不要当全项目证据索引引用。')
lines = ['# 证据索引（自动生成）', '', NOTE, '',
         '| run | schema | 结果 | 关键指标 |', '| --- | --- | --- | --- |']
for r in rows:
    ok = r['all_ok']
    verdict = '通过' if ok is True else ('失败' if ok is False else '—')
    if r['status']:
        verdict += f" / {r['status']}"
    m = ', '.join(f'{k}={v}' for k, v in r['metrics'].items()
                  if k in ('final_x', 'tilt_max_deg', 'blocked_at', 'ok_phases',
                           'phases', 'ok_actions', 'actions', 'unified_actions'))
    lines.append(f"| `{r['run']}` | {r['schema']} | {verdict} | {m} |")
(ROOT / 'docs/EVIDENCE_INDEX.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'n': len(rows), 'out': 'docs/EVIDENCE_INDEX.md'}, ensure_ascii=False))
