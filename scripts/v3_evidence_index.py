"""G6：把主要 run 的 result.json 汇总成证据索引（run -> 指标 -> 复现）。"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
GROUPS = ['basic_cycle', 'climb', 'wheel_probe', 'rock_actions', 'route', 'e_cases']
rows = []
for group in GROUPS:
    base = ROOT / 'runs/v3' / group
    if not base.exists():
        continue
    for res in sorted(base.glob('*/result.json')):
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
lines = ['# 证据索引（自动生成）', '',
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
