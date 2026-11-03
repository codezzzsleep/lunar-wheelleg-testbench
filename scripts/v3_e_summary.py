"""E 准备：汇总已有 FULL / OBS_ONLY 决策与执行，挑三个有限案例。"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
rows = []
for sd in sorted((ROOT / 'runs/v3/states').iterdir()):
    d = sd / 'decision'
    f = d / 'decision_FULL.json'
    o = d / 'decision_OBS_ONLY.json'
    if not (f.exists() and o.exists()):
        continue
    try:
        fj, oj = json.loads(f.read_text()), json.loads(o.read_text())
    except Exception:  # noqa: BLE001
        continue
    fd, od = (fj.get('decision') or {}), (oj.get('decision') or {})
    fa = fd.get('chosen') or fd.get('action')
    oa = od.get('chosen') or od.get('action')
    ef = d / 'execution_FULL.json'
    eo = d / 'execution_OBS_ONLY.json'
    fe = json.loads(ef.read_text()) if ef.exists() else {}
    oe = json.loads(eo.read_text()) if eo.exists() else {}
    rows.append({'state': sd.name, 'full_action': fa, 'obs_action': oa,
                 'same_action': fa == oa,
                 'full_success': fe.get('success'), 'full_cost': fe.get('cost'),
                 'obs_success': oe.get('success'), 'obs_cost': oe.get('cost'),
                 'full_reason': fe.get('reason'), 'obs_reason': oe.get('reason'),
                 'full_votes': fd.get('votes'), 'obs_votes': od.get('votes')})
out = ROOT / 'runs/v3/e_cases/index.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({'schema': 'v3-e-cases/v1', 'n': len(rows), 'rows': rows},
                          ensure_ascii=False, indent=2))
print(json.dumps({'n': len(rows),
                  'both_success': sum(1 for r in rows if r['full_success'] and r['obs_success']),
                  'full_only': sum(1 for r in rows if r['full_success'] and not r['obs_success']),
                  'obs_only': sum(1 for r in rows if r['obs_success'] and not r['full_success']),
                  'differ_action': sum(1 for r in rows if not r['same_action'])},
                 ensure_ascii=False))
