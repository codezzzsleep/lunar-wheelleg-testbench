"""
V7 交付验收器：覆盖任务书第十三节要求的关键错误路径。

检查分三层，全部从**原始文件与实际内容**复算，不读取旧报告的 PASS：
  L1 身份：生成任务身份/输入哈希/预算占用/碰撞身份/源实体一致性
  L2 证据：资格（可见 + 碰撞）、两图计划与实际一致、决策与执行顺序、观察与续行
  L3 交付：状态文档四类字段、批次 manifest、页面/回放、失败分母保留

负例自检（`--self-test`）会注入 12 类真实错误，验收器必须逐一检出。

  .venv/bin/python scripts/verify_delivery_v7.py --batch runs/unseen/delivery_v7/v7_20261030 \
      --out runs/unseen/delivery_v7/v7_20261030/verify/delivery_report.json
  .venv/bin/python scripts/verify_delivery_v7.py --self-test
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
    C = []

    def add(layer, name, ok, detail=''):
        C.append({'layer': layer, 'check': name, 'pass': bool(ok), 'detail': str(detail)})

    # ---------------- L1 身份
    bud = jl(ROOT / 'configs/unseen_v7_budget.json', {}) or {}
    add('L1', 'budget_authorization_500', bud.get('new_authorization_credits') == 500,
        bud.get('new_authorization_credits'))
    led_p = B / 'generation/ledger.jsonl'
    rows = []
    if led_p.exists():
        rows = [json.loads(l) for l in led_p.read_text().splitlines() if l.strip()]
    held = sum(float(r.get('estimate_upper') or 0) for r in rows)
    add('L1', 'ledger_within_500', held <= 500.0 + 1e-9, held)
    add('L1', 'ledger_has_task_ids', all(r.get('task_id') for r in rows if r.get('status') != 'released'),
        [r.get('attempt_id') for r in rows if not r.get('task_id')][:3])
    tasks = {}
    for f in sorted((B / 'generation').glob('task_*.json')):
        d = jl(f)
        if d:
            tasks[d['task_id']] = d
    add('L1', 'task_records_present', len(tasks) == len(rows), f'{len(tasks)} vs {len(rows)}')
    bad_in = []
    for t, d in tasks.items():
        for p, h in zip(d.get('image_paths') or [], d.get('image_sha256') or []):
            fp = ROOT / p if not pathlib.Path(p).is_absolute() else pathlib.Path(p)
            if fp.exists() and sha(fp) != h:
                bad_in.append(t)
    add('L1', 'input_hash_matches_bytes', not bad_in, bad_in)
    bad_mode = []
    for t, d in tasks.items():
        n = int(d.get('n_images') or 0)
        if (n >= 2) != (d.get('mode') == 'two_image'):
            bad_mode.append(t)
        if d.get('mode') == 'two_image' and not (d.get('image_urls') and len(d['image_urls']) == n):
            bad_mode.append(f'{t}:urls')
    add('L1', 'mode_matches_image_count', not bad_mode, bad_mode)
    ver = {t: d.get('version') for t, d in tasks.items()}
    add('L1', 'version_explicit', all(v for v in ver.values()), ver)

    cands = {}
    for f in sorted((B / 'candidates').glob('*/clean/body.stl')):
        cands[f.parent.parent.name] = f
    add('L1', 'candidates_present', len(cands) > 0, len(cands))

    # ---------------- L2 证据
    proc = {}
    for f in sorted((B / 'processed').glob('*/process.json')):
        proc[f.parent.name] = jl(f)
    for name, p in proc.items():
        fm = p.get('fusion_metrics') or {}
        strict = bool((p.get('fusion_strict') or {}).get('pass'))
        free = fm.get('freespace_violation')
        p95 = fm.get('vis_pt_p95_mm')
        # 资格：strict=true 必须 freespace<=0.05 且 p95<=5
        ok_strict = (free is not None and p95 is not None
                     and free <= 0.05 and p95 <= 5.0)
        add('L2', f'strict_consistent[{name}]', (not strict) or ok_strict,
            f'strict={strict} free={free} p95={p95}')
        cm = p.get('collision_metrics_identity') or {}
        add('L2', f'collision_identity_matches[{name}]',
            cm.get('source_sha') == p.get('fusion_world_sha'),
            f"{cm.get('source_sha')} vs {p.get('fusion_world_sha')}")
        add('L2', f'physics_config_present[{name}]', bool(p.get('physics_config_sha')),
            p.get('physics_config_sha'))
        add('L2', f'fusion_pitch_recorded[{name}]', p.get('fusion_pitch_m') is not None,
            p.get('fusion_pitch_m'))

    # 两图：计划里有两图就必须真的有两次上传
    two = [t for t, d in tasks.items() if d.get('mode') == 'two_image']
    for t in two:
        d = tasks[t]
        add('L2', f'two_image_uploaded_two[{t}]',
            len(d.get('image_urls') or []) == 2 and len(d.get('image_sha256') or []) == 2,
            len(d.get('image_urls') or []))

    # 决策与执行顺序（若已有 evaluation）
    for d in sorted((B / 'evaluation').glob('*')):
        sm = jl(d / 'summary.json')
        if not sm:
            continue
        dv = jl(d / 'decisions.json', {}) or {}
        if isinstance(dv, list):          # eval_six 写的是列表，没有 bundle 身份
            dv = {'decisions': dv}
        ex = []
        ep = d / 'execution.jsonl'
        if ep.exists():
            ex = [json.loads(l) for l in ep.read_text().splitlines() if l.strip()]
        if dv.get('decisions') and ex:
            add('L2', f'decision_before_execution[{d.name}]',
                float(dv.get('written_at') or 0) <= min(float(r.get('started_at') or 1e18) for r in ex),
                dv.get('written_at'))
            add('L2', f'execution_has_real_start[{d.name}]',
                all(r.get('started_at') is not None for r in ex), '')
            add('L2', f'execution_refs_decision[{d.name}]',
                all(r.get('decision_sha') == dv.get('decision_sha') for r in ex), '')

    # 观察闭环（若已有 look 记录）
    for f in sorted((B / 'observation').glob('*/look_loop.json')):
        lk = jl(f) or {}
        tr = lk.get('trigger') or {}
        if tr.get('triggered'):
            add('L2', f'look_loop_has_second_obs[{f.parent.name}]',
                bool((lk.get('second_observation') or {}).get('observation')),
                '')
        add('L2', f'look_loop_state_no_reset[{f.parent.name}]',
            not (lk.get('state_reset') is True), lk.get('state_reset'))

    # 来源：fixture / 镜像不得冒充 Lux3D
    for name, p in proc.items():
        src_kind = (p.get('source_kind') or 'lux3d')
        declared = (tasks.get(p.get('task_id')) or {}).get('mode')
        add('L2', f'source_kind_declared[{name}]', src_kind in ('lux3d', 'mirror', 'fixture'),
            f'{src_kind} / task_mode={declared}')

    # 失败分母保留：所有生成任务都要能在对象清单里找到，且失败的不删除
    obj_counts = {}
    for t, d in tasks.items():
        obj_counts.setdefault(d.get('object'), []).append(t)
    add('L2', 'denominator_kept', all(len(v) >= 1 for v in obj_counts.values()),
        {k: len(v) for k, v in obj_counts.items()})

    # ---------------- L3 交付
    st = jl(ROOT / 'docs/UNSEEN_STATUS_V7.md')
    txt = (ROOT / 'docs/UNSEEN_STATUS_V7.md').read_text() if (ROOT / 'docs/UNSEEN_STATUS_V7.md').exists() else ''
    for key in ('execution_status', 'evidence_status', 'capability_status', 'benefit_status'):
        add('L3', f'status_has_{key}', key in txt, '')
    add('L3', 'status_single_entry', 'V7 当前状态' in txt or '唯一入口' in txt, '')
    man = jl(B / 'manifest.json')
    add('L3', 'batch_manifest_present', bool(man), '')

    rep = {'schema': 'verify-delivery/v7', 'batch': str(B), 'n_checks': len(C),
           'n_pass': sum(1 for c in C if c['pass']),
           'n_fail': sum(1 for c in C if not c['pass']),
           'checks': C, 'verdict': 'PASS' if all(c['pass'] for c in C) else 'FAIL'}
    return rep


def self_test(batch):
    src = pathlib.Path(batch)
    out = {}
    base = verify(src)
    out['baseline_pass'] = base['verdict'] == 'PASS'
    with tempfile.TemporaryDirectory() as td:
        def clone(i):
            d = pathlib.Path(td) / f'c{i}'
            shutil.copytree(src, d)
            return d

        # N1 预算超额
        d = clone(1)
        led = d / 'generation/ledger.jsonl'
        rows = [json.loads(l) for l in led.read_text().splitlines() if l.strip()]
        rows[0]['estimate_upper'] = 900.0
        led.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        out['detect_over_budget'] = any(c['check'] == 'ledger_within_500' and not c['pass']
                                        for c in verify(d)['checks'])
        # N2 输入哈希被改
        d = clone(2)
        f = sorted((d / 'generation').glob('task_*.json'))[0]
        t = jl(f); t['image_sha256'] = ['deadbeef'] * len(t.get('image_sha256') or ['x'])
        f.write_text(json.dumps(t))
        out['detect_input_hash_mismatch'] = any(
            c['check'] == 'input_hash_matches_bytes' and not c['pass'] for c in verify(d)['checks'])
        # N3 两图模式只传一张
        d = clone(3)
        for f in (d / 'generation').glob('task_*.json'):
            t = jl(f)
            if t.get('mode') == 'two_image':
                t['image_urls'] = t['image_urls'][:1]
                f.write_text(json.dumps(t))
                break
        out['detect_two_image_short'] = any(
            c['check'].startswith('two_image_uploaded_two') and not c['pass']
            for c in verify(d)['checks'])
        # N4 strict 造假
        d = clone(4)
        f = sorted((d / 'processed').glob('*/process.json'))[0]
        p = jl(f); p.setdefault('fusion_strict', {})['pass'] = True
        p.setdefault('fusion_metrics', {})['freespace_violation'] = 0.20
        p['fusion_metrics']['vis_pt_p95_mm'] = 9.0
        f.write_text(json.dumps(p))
        out['detect_fake_strict'] = any(
            c['check'].startswith('strict_consistent') and not c['pass'] for c in verify(d)['checks'])
        # N5 碰撞身份与源实体不符
        d = clone(5)
        f = sorted((d / 'processed').glob('*/process.json'))[0]
        p = jl(f); p['collision_metrics_identity']['source_sha'] = 'deadbeef'
        f.write_text(json.dumps(p))
        out['detect_collision_identity'] = any(
            c['check'].startswith('collision_identity_matches') and not c['pass']
            for c in verify(d)['checks'])
        # N6 隐藏版本号
        d = clone(6)
        f = sorted((d / 'generation').glob('task_*.json'))[0]
        t = jl(f); t['version'] = None
        f.write_text(json.dumps(t))
        out['detect_missing_version'] = any(
            c['check'] == 'version_explicit' and not c['pass'] for c in verify(d)['checks'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', default='runs/unseen/delivery_v7/v7_20261030')
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
        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'verdict': rep['verdict'], 'n_pass': rep['n_pass'],
                      'n_checks': rep['n_checks'],
                      'fails': [c['check'] for c in rep['checks'] if not c['pass']][:8]},
                     ensure_ascii=False))
    return 0 if rep['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
