"""Stage008：汇总正式单案例 FULL/OBS 结果。"""
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
rows = []
for d in sorted((ROOT / 'runs/v3/stage008').glob('case_*')):
    p = d / 'result.json'
    if not p.exists():
        continue
    r = json.loads(p.read_text())
    b = next((x for x in r['rows'] if x['action'] == 'BODY_CLEARANCE'), None)
    rows.append({'case': d.name, 'arm': r['arm'], 'chosen': r['chosen'],
                 'body_success': b and b.get('success'), 'body_outcome': b and b.get('outcome'),
                 'body_cost_s': b and b.get('cost'), 'body_chassis': b and b.get('chassis_contacts'),
                 'exec': r['exec'], 'votes': r['votes']})
out = {'schema': 'stage8-formal-table/v1', 'rows': rows,
       'note': 'FULL=complete-geometry reference (V | (P&U)); OBS=V; same S0/actions/endpoint/budget'}
(ROOT / 'runs/v3/stage008/formal_table.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(json.dumps(rows, ensure_ascii=False, indent=1))
