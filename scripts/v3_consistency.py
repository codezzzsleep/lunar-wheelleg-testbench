"""交付一致性检查：文档中的关键数字必须能在 run 数据里复核。"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
checks = []


def check(name, ok, detail):
    checks.append({'name': name, 'ok': bool(ok), 'detail': detail})


def j(p):
    return json.loads((ROOT / p).read_text())


r = j('runs/v3/route/rigid_r2/result.json')
check('route rigid final_x', abs(r['final_x'] - 23.5482) < 1e-3, r['final_x'])
check('route rigid passed', r['passed'] is True, r['passed'])
n = j('runs/v3/route/nominal_r1/result.json')
check('route nominal final_x', abs(n['final_x'] - 23.5375) < 1e-3, n['final_x'])
check('route nominal passed', n['passed'] is True, n['passed'])

bc = [json.loads(p.read_text()) for p in
      sorted((ROOT / 'runs/v3/basic_cycle').glob('*/result.json'))]
check('basic_cycle >= 8 runs', len(bc) >= 8, len(bc))
check('basic_cycle all_ok', all(x.get('all_ok') for x in bc),
      sum(1 for x in bc if x.get('all_ok')))

cf = j('runs/v3/climb/CLIMB_failure_report.json')
check('climb failure status', cf.get('status') == 'not_passed', cf.get('status'))

e = j('runs/v3/e_cases/index.json')
rows = e['rows']
both = sum(1 for x in rows if x['full_success'] and x['obs_success'])
full_only = sum(1 for x in rows if x['full_success'] and not x['obs_success'])
differ = sum(1 for x in rows if not x['same_action'])
check('e cases n=14', len(rows) == 14, len(rows))
check('e both_success=12', both == 12, both)
check('e full_only=0', full_only == 0, full_only)
check('e differ_action=1', differ == 1, differ)

pp = [json.loads(p.read_text()) for p in
      sorted((ROOT / 'runs/v3/rock_actions').glob('pp_*/result.json'))]
pp_rows = [x['rows'][0] for x in pp]
check('perturbed S1 n=3', len(pp_rows) == 3, len(pp_rows))
check('perturbed S1 unified=2',
      sum(1 for r in pp_rows if r.get('unified')) == 2,
      sum(1 for r in pp_rows if r.get('unified')))
check('perturbed hashes distinct',
      len({r.get('init_qpos_sha256') for r in pp_rows}) == len(pp_rows),
      len({r.get('init_qpos_sha256') for r in pp_rows}))

idx = j('runs/v3/evidence_index.json')
check('evidence index present', idx.get('n', 0) > 0, idx.get('n'))

NOTE = ('> **范围（2026-11-11 标注）**：本检查是 **v3 批次**的一致性口径，不覆盖 v4–v8。'
        '全项目当前的边界与证据等级见 `docs/DELIVERY.md`。')
lines = ['# 交付一致性检查', '', NOTE, '',
         '| 检查 | 结果 | 实际值 |', '| --- | --- | --- |']
for c in checks:
    lines.append(f"| {c['name']} | {'通过' if c['ok'] else '**失败**'} | {c['detail']} |")
lines += ['', f"总计：{sum(1 for c in checks if c['ok'])}/{len(checks)} 通过。"]
(ROOT / 'docs/CONSISTENCY.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'ok': all(c['ok'] for c in checks),
                  'passed': sum(1 for c in checks if c['ok']), 'n': len(checks)},
                 ensure_ascii=False))
raise SystemExit(0 if all(c['ok'] for c in checks) else 1)
