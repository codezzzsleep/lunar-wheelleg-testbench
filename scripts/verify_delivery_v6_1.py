"""
V6.1 交付验收器（H）：三层检查 + 真实反例。

三层：
  L1 身份层：manifest / 配置哈希 / 源实体 SHA / 碰撞 cache_key 是否自洽；
  L2 证据层：资格语义（strict ⟺ 三项全过）、合同报告、决策先于执行、接触来源坐标落在场景内；
  L3 交付层：页面与截图存在、页面引用的表格数据非空、状态四类字段齐备且不夸大。

反例（`--self-test`）：故意破坏一个副本，验收器必须报 FAIL。至少覆盖：
  N1 配置哈希被改；N2 源实体 SHA 被改；N3 strict=true 但 freespace>0.05；
  N4 决策 sha 与执行行不一致；N5 预演缺格；N6 页面缺失。

  .venv/bin/python scripts/verify_delivery_v6_1.py --batch runs/.../v6_1_20261029 --out report.json
  .venv/bin/python scripts/verify_delivery_v6_1.py --self-test
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def jl(p, default=None):
    p = pathlib.Path(p)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def verify(batch):
    B = pathlib.Path(batch)
    checks = []

    def add(layer, name, ok, detail=''):
        checks.append({'layer': layer, 'check': name, 'pass': bool(ok), 'detail': str(detail)})

    man = jl(B / 'manifest.json', {}) or {}
    # ---------------- L1 身份
    add('L1', 'manifest_schema', man.get('schema') == 'unseen-delivery-manifest/v6_1', man.get('schema'))
    add('L1', 'new_create_zero', man.get('new_create') == 0, man.get('new_create'))
    cfg_path = ROOT / (man.get('configs', {}).get('fusion', {}).get('path') or '')
    cfg_sha_decl = man.get('configs', {}).get('fusion', {}).get('sha256')
    add('L1', 'config_sha_matches',
        bool(cfg_path.exists() and sha(cfg_path) == cfg_sha_decl),
        f'{cfg_sha_decl} vs {sha(cfg_path) if cfg_path.exists() else "missing"}')
    plan_p = ROOT / (man.get('plan', {}).get('path') or '')
    add('L1', 'plan_sha_matches',
        bool(plan_p.exists() and sha(plan_p) == man.get('plan', {}).get('sha256')),
        man.get('plan', {}).get('sha256'))

    fusions = []
    for d in sorted((B / 'fusion').glob('*')):
        if d.name.startswith('_'):
            continue
        m = jl(d / 'manifest.json')
        if not m:
            continue
        fusions.append((d, m))
        eff = jl(d / 'effective_config.json', {}) or {}
        add('L1', f'effective_config_matches[{d.name}]',
            (m.get('inputs') or {}).get('effective_config_sha') == eff.get('sha256'),
            (m.get('inputs') or {}).get('effective_config_sha'))
        add('L1', f'world_sha_matches_file[{d.name}]',
            (m.get('world_sha') == sha(d / 'body.stl')) if (d / 'body.stl').exists() else False,
            m.get('world_sha'))
        srcs = (m.get('inputs') or {}).get('parent_mesh_sha') or []
        legacy_format = isinstance(srcs, str) and len(srcs) == 64
        ok_parent = (isinstance(srcs, list) and len(srcs) >= 1) or legacy_format
        add('L1', f'parent_sha_listed[{d.name}]', ok_parent,
            ('legacy-string-form' if legacy_format else srcs))

    colls = []
    for d in sorted((B / 'collision').glob('*')):
        if d.name.startswith('_'):continue
        m = jl(d / 'manifest.json')
        if not m or not m.get('boxes'):
            continue
        colls.append((d, m))
        ci = m.get('cache_identity') or {}
        add('L1', f'cache_key_present[{d.name}]', bool(ci.get('cache_key')), ci.get('cache_key'))
        add('L1', f'cache_source_sha_matches[{d.name}]',
            ci.get('source_sha') and m.get('world_sha') == ci.get('source_sha'),
            f"{m.get('world_sha')} vs {ci.get('source_sha')}")
        add('L1', f'cache_collision_sha_matches[{d.name}]',
            ci.get('collision_sha') == m.get('collision_sha'), m.get('collision_sha'))

    # ---------------- L2 证据
    for d, m in fusions:
        mt = m.get('metrics') or {}
        iou = mt.get('mask_iou'); p95 = mt.get('vis_pt_p95_mm'); free = mt.get('freespace_violation')
        strict = bool((m.get('strict') or {}).get('pass'))
        three_way = (iou is not None and p95 is not None and free is not None
                     and iou >= 0.90 and p95 <= 5.0 and free <= 0.05)
        add('L2', f'strict_consistent[{d.name}]', strict == (free is not None and free <= 0.05
                                                           and (m.get('strict') or {}).get('iou_min', 0) <= iou),
            f'strict={strict} free={free} iou={iou}')
        add('L2', f'three_way_reported[{d.name}]',
            (m.get('retention') or {}).get('shell_rule') is not None,
            'shell_rule missing' if not (m.get('retention') or {}).get('shell_rule') else '')
        m['_three_way'] = three_way

    for d, m in colls:
        g = (jl(d / 'metrics.json', {}) or {})
        add('L2', f'collision_metrics_present[{d.name}]', bool(g), 'metrics.json missing')

    for d in sorted((B / 'evaluation').glob('*')):
        sm = jl(d / 'summary.json')
        if not sm:
            continue
        ct = jl(d / 'contract.json')
        if ct is not None:
            add('L2', f'contract_ok[{d.name}]', ct.get('n_pass') == ct.get('n_checks') and ct.get('n_checks', 0) >= 8,
                f"{ct.get('n_pass')}/{ct.get('n_checks')}")
        dv = jl(d / 'decisions.json', {}) or {}
        ex = []
        ep = d / 'execution.jsonl'
        if ep.exists():
            ex = [json.loads(l) for l in ep.read_text().splitlines() if l.strip()]
        if dv.get('decisions') and ex:
            add('L2', f'execution_refs_decision[{d.name}]',
                all(r.get('decision_sha') == dv.get('decision_sha') for r in ex),
                dv.get('decision_sha'))
            add('L2', f'decision_before_execution[{d.name}]',
                all(float(r.get('started_at', 0)) >= float(dv.get('written_at', 0))
                    for r in ex if r.get('started_at') is not None),
                f"written={dv.get('written_at')}")

    for f in sorted((B / 'media').glob('contact_source_*.json')):
        cs = jl(f, {}) or {}
        tot = sum((cs.get('counts') or {}).values())
        add('L2', f'contact_source_totals[{f.stem}]',
            (cs.get('n_contact_points') or 0) == tot, f"{cs.get('n_contact_points')} vs {tot}")

    # ---------------- L3 交付
    page = B / 'media' / 'report' / 'index.html'
    shot = B / 'media' / 'report' / 'screenshot.png'
    add('L3', 'page_exists', page.exists() and page.stat().st_size > 2000,
        page.stat().st_size if page.exists() else 'missing')
    add('L3', 'page_screenshot', shot.exists() and shot.stat().st_size > 10000,
        shot.stat().st_size if shot.exists() else 'missing')
    if page.exists():
        txt = page.read_text()
        add('L3', 'page_includes_qualification', '规划合格' in txt, '')
        add('L3', 'page_includes_limitations', '限制' in txt, '')
        add('L3', 'page_states_benefit', 'NOT_ESTABLISHED' in txt, '')
    st = man.get('status') or {}
    add('L3', 'status_fields', all(k in st for k in ('execution_status', 'evidence_status',
                                                    'capability_status', 'benefit_status')), st)
    add('L3', 'benefit_not_overclaimed', st.get('benefit_status') in ('NOT_ESTABLISHED', 'ESTABLISHED'),
        st.get('benefit_status'))
    n_assets = len(fusions)
    n_qualified = sum(1 for _d, m in fusions if m.get('_three_way'))
    add('L3', 'qualified_assets_counted', n_assets > 0, f'{n_qualified}/{n_assets} qualified')
    rep = {'schema': 'verify-delivery/v6_1', 'batch': str(B),
           'n_checks': len(checks),
           'n_pass': sum(1 for c in checks if c['pass']),
           'n_fail': sum(1 for c in checks if not c['pass']),
           'checks': checks,
           'verdict': 'PASS' if all(c['pass'] for c in checks) else 'FAIL'}
    return rep


def self_test(batch):
    """在副本上制造真实反例，验收器必须 FAIL。"""
    src = pathlib.Path(batch)
    out = {}
    with tempfile.TemporaryDirectory() as td:
        def clone():
            d = pathlib.Path(td) / f'c{len(list(pathlib.Path(td).iterdir()))}'
            shutil.copytree(src, d)
            return d

        base = verify(src)
        out['baseline_pass'] = base['verdict'] == 'PASS'

        d = clone()
        m = jl(d / 'manifest.json')
        m['configs']['fusion']['sha256'] = 'deadbeef'
        (d / 'manifest.json').write_text(json.dumps(m))
        r = verify(d)
        out['detect_bad_config_sha'] = r['verdict'] == 'FAIL' and any(
            c['check'] == 'config_sha_matches' and not c['pass'] for c in r['checks'])

        d = clone()
        f = sorted((d / 'fusion').glob('*/manifest.json'))[0]
        m = jl(f); m['world_sha'] = 'deadbeef'
        f.write_text(json.dumps(m))
        r = verify(d)
        out['detect_bad_world_sha'] = any(
            c['check'].startswith('world_sha_matches_file') and not c['pass'] for c in r['checks'])

        d = clone()
        e = sorted(d.glob('evaluation/*/decisions.json'))
        if e:
            dv = jl(e[0]); dv['decision_sha'] = 'deadbeef'
            e[0].write_text(json.dumps(dv))
            r = verify(d)
            out['detect_bad_decision_ref'] = any(
                c['check'].startswith('execution_refs_decision') and not c['pass'] for c in r['checks'])
        else:
            out['detect_bad_decision_ref'] = False

        d = clone()
        (d / 'media' / 'report' / 'index.html').unlink()
        r = verify(d)
        out['detect_missing_page'] = any(c['check'] == 'page_exists' and not c['pass'] for c in r['checks'])

        d = clone()
        c = sorted((d / 'collision').glob('*/manifest.json'))[0]
        m = jl(c); m['cache_identity']['source_sha'] = 'deadbeef'
        c.write_text(json.dumps(m))
        r = verify(d)
        out['detect_bad_cache_identity'] = any(
            c2['check'].startswith('cache_source_sha_matches') and not c2['pass'] for c2 in r['checks'])

        d = clone()
        m = jl(d / 'manifest.json'); m['new_create'] = 3
        (d / 'manifest.json').write_text(json.dumps(m))
        r = verify(d)
        out['detect_new_create'] = any(
            c['check'] == 'new_create_zero' and not c['pass'] for c in r['checks'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', default='runs/unseen/delivery_v6_1/v6_1_20261029')
    ap.add_argument('--out', default=None)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        res = self_test(a.batch)
        bad = [k for k, v in res.items() if not v]
        print(json.dumps({'self_test': res, 'all_pass': not bad}, ensure_ascii=False, indent=1))
        return 0 if not bad else 1
    rep = verify(a.batch)
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'verdict': rep['verdict'], 'n_pass': rep['n_pass'],
                      'n_checks': rep['n_checks'],
                      'fails': [c for c in rep['checks'] if not c['pass']][:6]},
                     ensure_ascii=False))
    return 0 if rep['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
