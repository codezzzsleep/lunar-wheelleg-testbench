#!/usr/bin/env python3
"""
看不见的那一面 · 统一只读页面（batch manifest + page registry 驱动）。

  .venv/bin/python scripts/app_unseen.py --port 8091
  # http://127.0.0.1:8091/?run=pipeline_H5_R03

只读已落盘的真实产物；打开页面不会调用生成 API、不会新建任务。
V5 批次运行由 manifest 自动发现；缺失 summary/decision 时显示明确状态。
"""
import argparse
import html
import json
import pathlib
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / 'runs/unseen/page_registry.json'
LEGACY_REGISTRY = ROOT / 'runs/unseen/recovery_r3/page_runs.json'
VIEW_DIR = 'runs/unseen/delivery_v5/v5_20261029/media/page/views'
ACTIONS = ['R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2', 'A0']
SIX_ORDER = ['B0_blind', 'B1_height', 'B2_box', 'B3_mirror', 'H5_lux3d', 'U_truth']


# ---------------------------------------------------------------- helpers
def _json(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default


def _jsonl(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding='utf-8', errors='replace').splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                out.append({'__parse_error__': line[:200]})
    return out


def _resolve(rel):
    p = (ROOT / str(rel)).resolve()
    if p != ROOT.resolve() and ROOT.resolve() not in p.parents:
        raise ValueError('path escapes repo: %s' % rel)
    return p


def _rel(p):
    return pathlib.Path(p).resolve().relative_to(ROOT.resolve()).as_posix()


def _exists(rel):
    try:
        return bool(rel) and _resolve(rel).exists()
    except Exception:
        return False


def _short(x, n=12):
    if x is None:
        return '—'
    s = str(x)
    return s if len(s) <= n else s[:n] + '…'


def _f(x, nd=3):
    if x is None:
        return '—'
    if isinstance(x, bool):
        return '是' if x else '否'
    try:
        v = float(x)
        return str(int(round(v))) if abs(v - round(v)) < 1e-12 else ('%.' + str(nd) + 'f') % v
    except Exception:
        return str(x)


def _pct(x):
    try:
        return '%.1f%%' % (float(x) * 100)
    except Exception:
        return '—'


def _esc(x):
    return html.escape('' if x is None else str(x))


def _badge(t, c=''):
    return '<span class="badge %s">%s</span>' % (_esc(c), _esc(t))


def _chip(t, c=''):
    return '<span class="chip %s">%s</span>' % (_esc(c), _esc(t))


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ---------------------------------------------------------------- registry
def _load_registry():
    reg = _json(REGISTRY_PATH, {}) or {}
    if not isinstance(reg, dict):
        reg = {}
    reg.setdefault('runs', [])
    reg.setdefault('batches', [])
    return reg


def _legacy():
    data = _json(LEGACY_REGISTRY, []) or []
    return [r for r in data if isinstance(r, dict) and r.get('run')]


def _detect_kind(d):
    if (d / 'look_loop.json').exists():
        return 'look'
    s = _json(d / 'summary.json')
    if isinstance(s, dict):
        if (d / 'records.jsonl').exists() or 'methods' in s:
            return 'six'
        if (d / 'execution.jsonl').exists() or 'candidates' in s:
            return 'pipeline'
    return 'unknown'


def _batches(reg):
    out, seen = [], set()
    cands = [(b, b.get('manifest')) for b in reg.get('batches', []) if isinstance(b, dict)]
    for p in sorted((ROOT / 'runs/unseen').glob('*/*/manifest.json')):
        try:
            cands.append((None, _rel(p)))
        except Exception:
            pass
    for meta, rel in cands:
        if not rel:
            continue
        try:
            m = _json(_resolve(rel))
        except Exception:
            continue
        if not isinstance(m, dict) or m.get('schema') != 'delivery-manifest/v1':
            continue
        bid = m.get('batch_id') or pathlib.Path(rel).parent.name
        if bid in seen:
            continue
        seen.add(bid)
        out.append({'batch_id': bid, 'manifest': rel,
                    'dir': pathlib.Path(rel).parent.as_posix(),
                    'label': (meta or {}).get('label') or ('批次 · ' + bid), 'data': m})
    return out


def _batch_runs(b):
    d = _resolve(b['dir'])
    found = {}
    for sub in ('evaluation', 'runs', 'observation'):
        root = d / sub
        if not root.exists():
            continue
        for p in root.rglob('summary.json'):
            rd = p.parent
            if (rd / 'records.jsonl').exists() or (rd / 'execution.jsonl').exists():
                found[_rel(rd)] = rd
        for p in root.rglob('look_loop.json'):
            found[_rel(p.parent)] = p.parent
    out = []
    for rel, rd in sorted(found.items()):
        kind = _detect_kind(rd)
        if kind == 'unknown':
            continue
        s = _json(rd / 'summary.json', {}) or {}
        case = s.get('case_id') or s.get('case') or rd.name
        obs_from = None
        truth = s.get('truth_sha')
        look_meta = _json(rd / 'look_loop.json', {}) if kind == 'look' else {}
        kinds = (look_meta or {}).get('candidate_kinds') or {}
        fixture = any(v == 'fixture' for v in kinds.values()) or any(
            str(c).startswith('FX_') for c in ((look_meta or {}).get('candidates_in') or []))
        if not truth:
            truth = ((look_meta.get('truth_assets') or {}).get('world_sha') if look_meta else None)
        kdir = d / 'cases'
        if kdir.exists():
            for cp in kdir.glob('*/summary.json'):
                cs = _json(cp, {}) or {}
                match = ((case and cs.get('case') and str(cs.get('case')).startswith(str(case))) or
                         (truth and cs.get('truth_world_sha') == truth))
                if match:
                    if (not case or case == rd.name) and (cs.get('case') or cs.get('case_id')):
                        case = cs.get('case') or cs.get('case_id')
                    op = cs.get('observation')
                    if op and _exists(op):
                        obs_from = op
                    break
        out.append({'run': rd.name, 'kind': kind, 'dir': rel, 'case_id': case,
                    'batch_id': b['batch_id'], 'mode': 'batch_new',
                    'observation_from': obs_from,
                    'observation_note': ('观测只读复用本批 case 登记：' + obs_from) if obs_from else '',
                    'mode_note': '本批 manifest 下已落盘的真实运行；页面只读',
                    'fixture': fixture, 'role': 'batch_run',
                    'label': '%s · %s' % (case, rd.name)})
    return out


def _entries():
    reg = _load_registry()
    out = []
    for r in reg.get('runs', []):
        if isinstance(r, dict) and r.get('run'):
            e = dict(r)
            e.setdefault('kind', 'unknown')
            out.append(e)
    batches = _batches(reg)
    for b in batches:
        out.append({'run': 'batch:' + b['batch_id'], 'kind': 'batch', 'dir': b['dir'],
                    'batch': b, 'batch_id': b['batch_id'], 'case_id': b['batch_id'],
                    'mode': 'batch', 'mode_note': '批次 manifest 入口；只读，不触发创建',
                    'fixture': False, 'role': 'batch', 'label': b['label']})
        for r in _batch_runs(b):
            if any(x.get('run') == r['run'] or x.get('dir') == r['dir'] for x in out):
                continue
            out.append(r)
    return reg, batches, out


def _status(e):
    if e.get('kind') == 'batch':
        return 'batch'
    try:
        d = _resolve(e['dir'])
    except Exception:
        return 'missing'
    if not d.exists():
        return 'missing'
    if e.get('kind') == 'look':
        return 'ready' if (d / 'look_loop.json').exists() else 'partial'
    if (d / 'summary.json').exists():
        return 'ready' if ((d / 'decision.json').exists() or (d / 'decisions.json').exists()) else 'partial'
    return 'partial'


def list_cases():
    reg, batches, entries = _entries()
    out, seen = [], set()
    for e in entries:
        run = e.get('run')
        if not run or run in seen:
            continue
        seen.add(run)
        label = e.get('label') or run
        if e.get('kind') == 'batch':
            label += ' · 批次状态'
        sup = bool(e.get('superseded'))
        if sup and '[SUPERSEDED]' not in label:
            label = 'SUPERSEDED · ' + label
        out.append({'run': run, 'label': label, 'case_id': e.get('case_id') or '',
                    'kind': e.get('kind'), 'batch_id': e.get('batch_id'),
                    'fixture': bool(e.get('fixture')), 'dev': bool(e.get('dev')),
                    'superseded': sup,
                    'status': _status(e), 'role': e.get('role')})
    return out


def _find(name):
    reg, batches, entries = _entries()
    for e in entries:
        if e.get('run') == name:
            return e
    if name.startswith('batch:'):
        for e in entries:
            if e.get('kind') == 'batch' and e.get('batch_id') == name.split(':', 1)[1]:
                return e
    for row in _legacy():
        if row.get('run') == name:
            d = 'runs/unseen/recovery_r3/' + name
            if _exists(d):
                return {'run': name, 'kind': row.get('kind') or _detect_kind(_resolve(d)),
                        'dir': d, 'case_id': row.get('case_id') or name,
                        'mode': 'legacy', 'mode_note': '旧 page_runs 注册项（只读）',
                        'fixture': False, 'role': 'legacy', 'label': name}
    d = 'runs/unseen/recovery_r3/' + name
    if _exists(d):
        return {'run': name, 'kind': _detect_kind(_resolve(d)), 'dir': d,
                'case_id': name, 'mode': 'legacy', 'mode_note': '按目录发现的旧运行（只读）',
                'fixture': False, 'role': 'legacy', 'label': name}
    raise FileNotFoundError(name)


# ---------------------------------------------------------------- loaders
def _status_rows(path):
    d = _json(path, {}) if path else {}
    if isinstance(d, dict):
        d = d.get('rows') or []
    return [r for r in d if isinstance(r, dict)] if isinstance(d, list) else []


def _status_for(path, cid):
    for r in _status_rows(path):
        if r.get('candidate') == cid:
            return r
    return {}


def _views(cid, view_dir):
    out = []
    if not cid or not view_dir:
        return out
    for stage, label in (('side', '侧视'), ('back', '后侧视'), ('top', '俯视')):
        rel = '%s/%s_%s.png' % (view_dir.rstrip('/'), cid, stage)
        if _exists(rel):
            out.append({'stage': stage, 'label': label, 'path': rel})
    return out


def _truth_views(key, view_dir):
    return _views(key, view_dir)


def _load_obs(d, kind, entry):
    obs_dir = d
    if entry.get('observation_from') and not (d / 'rgb.png').exists():
        try:
            obs_dir = _resolve(entry['observation_from'])
        except Exception:
            obs_dir = d
    obs = _json(obs_dir / 'observation.json', {}) or {}
    direction = _json(obs_dir / 'direction.json', {}) or {}
    look = _json(d / 'look_loop.json', {}) if kind == 'look' else {}
    look_obs = look.get('observation', {}) if isinstance(look, dict) else {}
    specs = ([('view1.png', '第一观察 RGB（真实输入状态）'),
              ('view2.png', '第二观察 RGB（抬高后）'),
              ('FX_R01_view2.png', '候选 FX_R01 在第二视角的轮廓（fixture）')]
             if kind == 'look' else
             [('rgb.png', '机器人原观测 RGB'), ('mask.png', '可见面 mask（深度分割）'),
              ('masked_only.png', '仅可见面'), ('crop_white.png', '真实送生成的图（白底方裁）'),
              ('crop_raw.png', '带背景裁切（参考）')])
    imgs = []
    for fn, label in specs:
        p = obs_dir / fn
        if p.exists():
            imgs.append({'path': _rel(p), 'label': label, 'name': fn})
    usable, reason = bool(imgs), ''
    trigger_only = (kind == 'look' and isinstance(look, dict) and
                    (look.get('outcome') == 'trigger_only'))
    if kind == 'look':
        usable = bool(look_obs.get('usable')) and (obs_dir / 'view1.png').exists()
        if trigger_only and not usable:
            reason = '观察未触发：候选一致，不触发第二次观察；没有第二观察图'
        elif not usable:
            reason = '第二观察不可用（observation.usable=false 或缺 view1）'
    elif not imgs:
        usable = False
        reason = ('观测 JSON 存在但图像缺失' if (d / 'observation.json').exists()
                  else '该评测产物未附带观测图（只读评测记录）')
    return {'attached': bool(imgs), 'usable': usable, 'reason': reason,
            'dir': _rel(obs_dir) if obs_dir.exists() else '', 'note': entry.get('observation_note') or '',
            'images': imgs, 'visible': obs.get('visible') or direction.get('visible') or {},
            'camera': obs.get('camera') or direction.get('camera') or {},
            'direction': direction, 'look': look_obs, 'obs': obs,
            'trigger_only': trigger_only,
            'look_protocol': look.get('observation_protocol', {}) if isinstance(look, dict) else {}}


def _status_world_sha(st):
    wd = st.get('world_dir') if isinstance(st, dict) else None
    if not wd:
        return None
    try:
        m = _json(_resolve(wd) / 'manifest.json', {}) or {}
        return m.get('world_sha') or m.get('world_sha256')
    except Exception:
        return None


def _auto_status(entry, cid):
    """Fill strict/planning metrics from batch candidates/ or prior v4 status."""
    if not cid:
        return {}
    if entry.get('batch_id'):
        try:
            bdir = _resolve(entry['dir']).parent.parent
            ft = _json(bdir / 'evaluation' / 'formal_table_v5.json', {}) or {}
            for case in ft.get('cases') or []:
                if case.get('candidate') == cid:
                    met = case.get('candidate_metrics') or {}
                    return {'task_id': _ledger().get((re.search(r'/cache/[0-9a-f]{2}/([0-9a-f]{64})/',
                                                                  str((_json(bdir / 'candidates' / cid / 'clean' / 'clean.json', {}) or {}).get('candidate') or '')) or [None, None])[1]),
                            'world_sha': _status_world_sha({'world_dir': _rel(bdir / 'candidates' / cid / 'world' / 'align')}),
                            'strict_pass': case.get('candidate_strict_pass'),
                            'planning_eligible': case.get('candidate_planning_eligible'),
                            'planning_status': ('IoU-only' if met.get('hit_part_cap') else 'eligible') if case.get('candidate_planning_eligible') else 'ineligible',
                            'iou': met.get('mask_iou'), 'vis_pt_p95_mm': met.get('vis_pt_p95_mm'),
                            'freespace': met.get('freespace_violation'),
                            'hit_part_cap': met.get('hit_part_cap'),
                            'coacd_parts': met.get('coacd_parts')}
            cdir = bdir / 'candidates' / cid
            align = _json(cdir / 'align.json', {}) or {}
            clean = _json(cdir / 'clean' / 'clean.json', {}) or {}
            if align or clean:
                best = align.get('best') or {}
                native = best.get('native') or {}
                ver = clean.get('verify') or {}
                pre = clean.get('precheck') or {}
                identity = (re.search(r'/cache/[0-9a-f]{2}/([0-9a-f]{64})/',
                                      str(clean.get('candidate') or '')) or [None, None])[1]
                return {'task_id': _ledger().get(identity),
                        'world_sha': _status_world_sha({'world_dir': _rel(cdir / 'world' / 'align')}),
                        'strict_pass': align.get('pass') if align else None,
                        'planning_eligible': None, 'planning_status': 'not_evaluated',
                        'iou': native.get('mask_iou'),
                        'vis_pt_p95_mm': native.get('vis_pt_p95_mm'),
                        'freespace': native.get('freespace_violation'),
                        'thin_ratio': ver.get('thin_ratio'),
                        'clean_verdict': pre.get('verdict'),
                        'generation_verdict': 'ok' if clean else None,
                        'threshold_p95_mm': best.get('threshold_p95_mm')}
        except Exception:
            pass
    if str(cid).startswith('G_'):
        for r in _status_rows('runs/unseen/recovery_r3/v4_status.json'):
            if r.get('candidate') == cid:
                r = dict(r)
                r['world_sha'] = r.get('world_sha') or _status_world_sha(r)
                return r
    return {}


def _load_cands(entry, d, kind, summary, look, decisions=None):
    cid = entry.get('candidate_id')
    sp = entry.get('candidate_status')
    view_dir = entry.get('view_dir') or VIEW_DIR
    raw = []
    if kind == 'pipeline':
        raw = summary.get('candidates') or []
    elif kind == 'six':
        if not cid and isinstance(decisions, list):
            h5 = next((x for x in decisions if isinstance(x, dict) and x.get('method') == 'H5_lux3d'), {})
            cs = h5.get('candidates') or []
            cid = cs[0] if cs else cid
        if cid:
            raw = [{'hypothesis_id': cid}]
    elif kind == 'look':
        kinds = look.get('candidate_kinds') or {}
        raw = [{'hypothesis_id': c, 'source_kind': kinds.get(c) or ('fixture' if entry.get('fixture') else 'lux3d')}
               for c in look.get('candidates_in', []) or []]
    out = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        cid2 = c.get('hypothesis_id') or c.get('candidate_id') or c.get('id')
        st = _status_for(sp, cid2) if sp and cid2 else ({}
              if cid2 != cid else _status_for(sp, cid))
        if not st:
            st = _auto_status(entry, cid2)
        if st and not st.get('world_sha'):
            ws = _status_world_sha(st)
            if ws:
                st = dict(st)
                st['world_sha'] = ws
        fixture = bool(entry.get('fixture')) or c.get('source_kind') == 'fixture'
        out.append({'id': cid2 or '—', 'source_kind': c.get('source_kind') or ('fixture' if fixture else 'lux3d'),
                    'task_id': c.get('task_id') if c.get('task_id') is not None else st.get('task_id'),
                    'world_sha': c.get('world_sha') or c.get('world_sha256') or st.get('world_sha'),
                    'collision_sha': c.get('collision_sha') or st.get('collision_sha'),
                    'coacd_parts': c.get('coacd_parts') if c.get('coacd_parts') is not None else st.get('coacd_parts'),
                    'strict_pass': st.get('strict_pass'), 'planning_eligible': st.get('planning_eligible'),
                    'planning_status': st.get('planning_status') or ('default' if st.get('planning_eligible') is not None else 'not_evaluated'),
                    'hit_part_cap': st.get('hit_part_cap'),
                    'thin_ratio': st.get('thin_ratio'), 'iou': st.get('iou'),
                    'p95_mm': st.get('vis_pt_p95_mm'), 'freespace': st.get('freespace'),
                    'gen_verdict': st.get('generation_verdict'),
                    'clean_verdict': st.get('clean_verdict'), 'fixture': fixture,
                    'views': _views(cid2, view_dir), 'raw': c})
    if entry.get('fixture') and entry.get('candidate_meta'):
        meta = _json(entry['candidate_meta'], []) or []
        by_id = {m.get('candidate_id'): m for m in meta if isinstance(m, dict)}
        for c in out:
            m = by_id.get(c['id'])
            if m:
                c['task_id'] = 'fixture'
                c['source_kind'] = 'fixture'
                c['planning_eligible'] = bool(m.get('planning_eligible'))
                c['planning_status'] = 'fixture'
                c['world_sha'] = c['world_sha'] or m.get('world_sha256')
    return out


def _norm_reh(rows, kind, entry, summary, look):
    out = []
    cid = entry.get('candidate_id')
    if kind == 'pipeline':
        for r in rows:
            if isinstance(r, dict):
                out.append({'method': 'H5_lux3d', 'candidate_id': cid or
                            ((summary.get('candidates') or [{}])[0].get('hypothesis_id')),
                            'option': r.get('option'), 'success': bool(r.get('success')),
                            'abort': bool(r.get('abort')),
                            'reason': r.get('reason') or ('success' if r.get('success') else 'unknown'),
                            'seed': r.get('seed'), 'sim_time': r.get('sim_time_s', r.get('t_end')),
                            't_end': r.get('t_end'), 'final_x': r.get('x', r.get('final_x')),
                            'max_tilt': r.get('max_tilt'), 'contact': r.get('contact'),
                            'wall_s': r.get('wall_s'), 'env': 'candidate'})
    elif kind == 'six':
        for r in rows:
            if isinstance(r, dict):
                out.append({'method': r.get('method') or r.get('hypothesis') or 'unknown',
                            'candidate_id': r.get('candidate_id'), 'option': r.get('option'),
                            'success': bool(r.get('success')), 'abort': bool(r.get('abort')),
                            'reason': r.get('reason') or ('success' if r.get('success') else 'unknown'),
                            'seed': r.get('seed'), 'sim_time': r.get('sim_time_s', r.get('t_end')),
                            't_end': r.get('t_end'), 'final_x': r.get('final_x', r.get('x')),
                            'max_tilt': r.get('max_tilt'), 'contact': r.get('contact'),
                            'wall_s': r.get('wall_s'), 'env': r.get('environment_kind')})
    elif kind == 'look':
        for r in rows:
            if isinstance(r, dict):
                t0, t1 = r.get('t_start'), r.get('t_end')
                out.append({'method': 'fixture_policy', 'candidate_id': r.get('candidate') or cid,
                            'option': r.get('option'), 'success': bool(r.get('success')),
                            'abort': bool(r.get('abort')),
                            'reason': r.get('reason') or ('success' if r.get('success') else 'unknown'),
                            'seed': r.get('seed'),
                            'sim_time': (t1 - t0) if _num(t0) and _num(t1) else None,
                            't_end': t1, 'final_x': None, 'max_tilt': None, 'contact': None,
                            'wall_s': r.get('wall_s'), 'env': 'truth_continuation'})
    return out


def _norm_exec(rows, kind, summary, decision, look):
    out = []
    if kind == 'pipeline':
        chosen = summary.get('chosen')
        for r in rows:
            if not isinstance(r, dict):
                continue
            opt = r.get('option')
            labels = []
            if chosen and opt == chosen:
                labels.append('H5_lux3d')
            if opt == 'R1':
                labels.append('B0_blind')
            if opt == 'A0':
                labels.append('A0')
            for lab in labels or [opt or 'unknown']:
                out.append({'method': lab, 'option': opt, 'success': bool(r.get('success')),
                            'abort': bool(r.get('abort')),
                            'reason': r.get('reason') or ('success' if r.get('success') else 'unknown'),
                            'seed': r.get('seed'), 'sim_time': r.get('sim_time_s', r.get('t_end')),
                            't_end': r.get('t_end'), 'final_x': r.get('x', r.get('final_x')),
                            'max_tilt': r.get('max_tilt'), 'contact': r.get('contact'),
                            'wall_s': r.get('wall_s'), 'reused': len(labels) > 1})
    elif kind == 'six':
        for r in rows:
            if isinstance(r, dict):
                out.append({'method': r.get('method') or 'unknown', 'option': r.get('option'),
                            'success': bool(r.get('success')), 'abort': bool(r.get('abort')),
                            'reason': r.get('reason') or ('success' if r.get('success') else 'unknown'),
                            'seed': r.get('seed'), 'sim_time': r.get('sim_time_s', r.get('t_end')),
                            't_end': r.get('t_end'), 'final_x': r.get('final_x', r.get('x')),
                            'max_tilt': r.get('max_tilt'), 'contact': r.get('contact'),
                            'wall_s': r.get('wall_s'), 'reused': False})
    elif kind == 'look':
        chosen = decision.get('chosen')
        for r in rows:
            if isinstance(r, dict):
                t0, t1 = r.get('t_start'), r.get('t_end')
                opt = r.get('option')
                out.append({'method': ('policy(%s)' % chosen) if chosen and opt == chosen else (opt or 'unknown'),
                            'option': opt, 'success': bool(r.get('success')),
                            'abort': bool(r.get('abort')),
                            'reason': r.get('reason') or ('success' if r.get('success') else 'unknown'),
                            'seed': r.get('seed'),
                            'sim_time': (t1 - t0) if _num(t0) and _num(t1) else None,
                            't_end': t1, 'final_x': r.get('first_frame_x'),
                            'max_tilt': None, 'contact': None, 'wall_s': r.get('wall_s'),
                            'reused': False})
    return out


def _groups_reh(rows):
    g = {}
    for r in rows:
        key = (r.get('method') or 'unknown', r.get('candidate_id') or '')
        x = g.setdefault(key, {'method': key[0], 'candidate_id': key[1], 'n': 0,
                               'success': 0, 'abort': 0, 'fail': 0, 'options': {}, 'reasons': {}})
        x['n'] += 1
        if r.get('success'):
            x['success'] += 1
        elif r.get('abort'):
            x['abort'] += 1
        else:
            x['fail'] += 1
        o = x['options'].setdefault(r.get('option') or '—', {'n': 0, 'success': 0, 'abort': 0, 'fail': 0, 'reasons': {}})
        o['n'] += 1
        if r.get('success'):
            o['success'] += 1
        elif r.get('abort'):
            o['abort'] += 1
        else:
            o['fail'] += 1
        if not r.get('success'):
            rs = r.get('reason') or 'unknown'
            o['reasons'][rs] = o['reasons'].get(rs, 0) + 1
            x['reasons'][rs] = x['reasons'].get(rs, 0) + 1
    out = list(g.values())
    out.sort(key=lambda x: (SIX_ORDER.index(x['method']) if x['method'] in SIX_ORDER else 99,
                            x['method'], x['candidate_id']))
    return out


def _groups_exec(rows):
    g = {}
    for r in rows:
        k = r.get('method') or 'unknown'
        x = g.setdefault(k, {'method': k, 'n': 0, 'success': 0, 'abort': 0, 'fail': 0,
                             'reasons': {}, 'actions': {}, 'rows': [], 'sim': 0.0, 'sim_n': 0,
                             'wall': 0.0, 'wall_n': 0})
        x['n'] += 1
        x['rows'].append(r)
        if r.get('success'):
            x['success'] += 1
        elif r.get('abort'):
            x['abort'] += 1
        else:
            x['fail'] += 1
        if not r.get('success'):
            rs = r.get('reason') or 'unknown'
            x['reasons'][rs] = x['reasons'].get(rs, 0) + 1
        x['actions'][r.get('option') or '—'] = x['actions'].get(r.get('option') or '—', 0) + 1
        if _num(r.get('sim_time')):
            x['sim'] += float(r['sim_time'])
            x['sim_n'] += 1
        if _num(r.get('wall_s')):
            x['wall'] += float(r['wall_s'])
            x['wall_n'] += 1
    out = list(g.values())
    out.sort(key=lambda x: (SIX_ORDER.index(x['method']) if x['method'] in SIX_ORDER else 99, x['method']))
    return out


def _load_run_dir(entry):
    d = _resolve(entry['dir'])
    kind = entry.get('kind') or _detect_kind(d)
    summary_raw = _json(d / 'summary.json')
    summary = summary_raw if isinstance(summary_raw, dict) else {}
    dec_json = _json(d / 'decision.json')
    decisions = _json(d / 'decisions.json')
    look = _json(d / 'look_loop.json') if kind == 'look' else None
    records = _jsonl(d / 'records.jsonl')
    reh_raw = _jsonl(d / 'rehearsal.jsonl')
    reh_state = _jsonl(d / 'rehearsal_from_state.jsonl')
    exec_raw = _jsonl(d / 'execution.jsonl')
    obs = _load_obs(d, kind, entry)
    cands = _load_cands(entry, d, kind, summary, look or {}, decisions)
    if kind == 'six':
        reh_rows = [r for r in records if r.get('phase') == 'rehearsal']
        exec_rows = [r for r in records if r.get('phase') == 'execution']
    elif kind == 'pipeline':
        reh_rows, exec_rows = reh_raw, exec_raw
    elif kind == 'look':
        reh_rows, exec_rows = reh_state, (look or {}).get('execution') or []
    else:
        reh_rows, exec_rows = [], []
    reh = _norm_reh(reh_rows, kind, entry, summary, look or {})
    dec_obj = dec_json if isinstance(dec_json, dict) else {}
    if kind == 'look':
        dec_obj = dict((look or {}).get('decision') or dec_json or {})
        dec_obj['decision_sha256'] = (look or {}).get('decision_sha256')
        if obs.get('trigger_only'):
            dec_obj['trigger'] = (look or {}).get('trigger')
            dec_obj['outcome'] = (look or {}).get('outcome')
            dec_obj['trigger_only'] = True
    exe = _norm_exec(exec_rows, kind, summary, dec_obj, look or {})
    six = None
    if kind == 'six':
        methods = summary.get('methods') or []
        dl = decisions if isinstance(decisions, list) else []
        six = {'methods': methods, 'decisions': dl,
               'dec_by': {x.get('method'): x for x in dl if isinstance(x, dict)},
               'diagnostic': _json(d / 'width_rule_diagnostic.json')}
    chosen = None
    if kind == 'pipeline':
        chosen = summary.get('chosen') or dec_obj.get('chosen')
    elif kind == 'look':
        chosen = (look or {}).get('decision', {}).get('chosen') or dec_obj.get('chosen')
    elif kind == 'six':
        h5 = next((m for m in summary.get('methods', []) if m.get('method') == 'H5_lux3d'), {})
        chosen = h5.get('selected_action')
    c_raw = [c.get('raw') or {} for c in cands]
    truth_sha = summary.get('truth_sha') or dec_obj.get('truth_sha')
    if kind == 'look':
        truth_sha = ((look or {}).get('truth_assets') or {}).get('world_sha')
    cand_world = next((c.get('world_sha') for c in cands if c.get('world_sha')), None)
    independent = None
    if truth_sha and cand_world:
        independent = str(truth_sha) != str(cand_world)
    if entry.get('fixture'):
        independent = None
    trigger_only = bool(obs.get('trigger_only'))
    states = []
    if kind != 'look' and not summary:
        states.append(('bad', '缺少 summary', '未找到 summary.json；不把缺失当成功。'))
    if kind == 'six' and not isinstance(decisions, list):
        states.append(('bad', '缺少 decisions', '未找到 decisions.json。'))
    if kind in ('pipeline', 'look') and not dec_obj and not trigger_only:
        states.append(('bad', '缺少 decision', '未找到 decision.json。'))
    if kind == 'look' and not look:
        states.append(('bad', '缺少 look_loop', '未找到 look_loop.json。'))
    if trigger_only:
        tr = (look or {}).get('trigger') or {}
        if tr.get('triggered'):
            states.append(('warn', '观察已触发但未执行',
                           'trigger/v1 triggered=true（%s）；本产物止于 trigger_only，没有第二观察图、decision 或执行。'
                           % (tr.get('reason') or '候选动作分歧')))
        else:
            states.append(('ok', '观察未触发', tr.get('reason') or '候选一致，不触发第二次观察。'))
    elif not obs['attached']:
        states.append(('warn', '观察不可用/未附带', obs['reason']))
    elif not obs['usable']:
        states.append(('bad', '观察不可用', obs['reason']))
    if not cands:
        states.append(('warn', '无候选', '没有登记真实生成候选；不补造 H5。'))
    if kind == 'pipeline' and exe and cands and any(c.get('strict_pass') is False for c in cands) and not any(c.get('planning_eligible') is True for c in cands):
        states.append(('warn', '探索性 H5：候选 strict fail',
                       '候选未通过 strict，且 planning 未评估；该执行只能作为线索，不是合格候选的正式收益。'))
    if not reh and not trigger_only:
        states.append(('warn', '没有预演记录', '试走矩阵为空；不是全部成功。'))
    if not exe and not trigger_only:
        states.append(('warn', '没有执行记录', '独立真值执行未运行或缺产物。'))
    if kind == 'look' and dec_obj and not trigger_only:
        if dec_obj.get('exec_seconds') is None:
            states.append(('warn', '执行计时缺失', 'decision.exec_seconds 为 null；不填 0。'))
        if dec_obj.get('total_seconds') is None:
            states.append(('warn', '总计时缺失', 'decision.total_seconds 为 null；不填 0。'))
    sims = [r.get('sim_time') for r in exe if _num(r.get('sim_time'))]
    walls = [r.get('wall_s') for r in exe if _num(r.get('wall_s'))]
    changed = []
    if kind == 'pipeline':
        stats = dec_obj.get('stats') or {}
        for opt, st in stats.items():
            try:
                rr = float(st.get('R', 0) or 0)
            except Exception:
                rr = 0
            if rr > 0:
                changed.append('%s 在该候选上失败/风险 R=%s，被排除' % (opt, _f(rr, 2)))
        if chosen:
            ss = stats.get(chosen) or {}
            changed.append('安全集 %s；选中 %s（R=%s，mean cost=%s）' %
                           ('/'.join(dec_obj.get('safe_set') or []) or '—', chosen,
                            _f(ss.get('R'), 2), _f(ss.get('mean_c'), 3)))
    formal_case = None
    formal_note = ''
    if entry.get('batch_id') and cands:
        try:
            bdir = _resolve(entry['dir']).parent.parent
            ft = _json(bdir / 'evaluation' / 'formal_table_v5.json', {}) or {}
            for case in ft.get('cases') or []:
                if case.get('candidate') == cands[0].get('id'):
                    formal_case = case
                    case_rows = [r for r in ft.get('rows') or [] if r.get('case') == case.get('case')]
                    parts = []
                    for mn, cn in (('B3_mirror', 'B3'), ('U_truth', 'U')):
                        rr = next((x for x in case_rows if x.get('method') == mn), None)
                        if rr:
                            parts.append('%s %s %s/%s' % (cn, rr.get('selected_action'), rr.get('success'), rr.get('n_exec')))
                    if case.get('case') == 'R01':
                        parts.append('宽度规则 S1 3/3')
                    if parts:
                        formal_note = '；'.join(parts)
                    break
        except Exception:
            formal_case, formal_note = None, ''
    tv_key = entry.get('truth_view')
    if not tv_key:
        tsha = str(truth_sha or '')
        if tsha.startswith('436b75d2'):
            tv_key = 'truth_R03'
        elif tsha.startswith('ae1837cd'):
            tv_key = 'truth_R01_base'
        elif tsha.startswith('ddeb1722'):
            tv_key = 'truth_R02'
        elif tsha.startswith('fd5a02c9'):
            tv_key = 'truth_R04'
    return {'run': entry['run'], 'kind': kind, 'label': entry.get('label') or entry['run'],
            'case_id': entry.get('case_id') or summary.get('case_id') or '',
            'dir': entry['dir'], 'mode': entry.get('mode') or '', 'mode_note': entry.get('mode_note') or '',
            'fixture': bool(entry.get('fixture')), 'dev': bool(entry.get('dev')),
            'superseded': bool(entry.get('superseded')) or ('init003' in entry.get('run', '')),
            'role': entry.get('role') or '', 'batch_id': entry.get('batch_id'),
            'summary': summary, 'summary_present': isinstance(summary_raw, dict), 'decision': dec_obj,
            'decision_present': bool(dec_obj), 'decisions': decisions if isinstance(decisions, list) else [],
            'look': look, 'look_present': bool(look), 'six': six, 'observation': obs,
            'candidates': cands, 'rehearsal': reh, 'rehearsal_groups': _groups_reh(reh),
            'execution': exe, 'execution_groups': _groups_exec(exe), 'chosen': chosen,
            'sim_total': sum(sims) if sims else None, 'sim_n': len(sims),
            'wall_total': sum(walls) if walls else None, 'wall_n': len(walls),
            'truth_sha': truth_sha, 'candidate_world_sha': cand_world, 'independent_truth': independent,
            'truth_views': _truth_views(tv_key, entry.get('view_dir') or VIEW_DIR),
            'replay_images': [{'path': _rel(p), 'label': p.name}
                              for p in sorted((d / 'replay').glob('*.png'))] if (d / 'replay').exists() else [],
            'states': states, 'changed': changed, 'trigger_only': trigger_only,
            'formal_case': formal_case, 'formal_note': formal_note,
            'trigger': (look or {}).get('trigger') if kind == 'look' else None,
            'targets': {k: (entry['dir'].rstrip('/') + '/' + fn if _exists(entry['dir'].rstrip('/') + '/' + fn) else None)
                        for k, fn in (('summary', 'summary.json'), ('decision', 'decision.json'),
                                      ('records', 'records.jsonl'), ('execution', 'execution.jsonl'))}}


def _ledger():
    out = {}
    for r in _jsonl(ROOT / 'runs/unseen/generation/ledger.jsonl'):
        if isinstance(r, dict) and r.get('identity'):
            out[r['identity']] = r.get('task_id')
    return out


def _load_batch(entry):
    d = _resolve(entry['dir'])
    m = _json(d / 'manifest.json', {}) or {}
    paths = m.get('paths') or {}
    view_dir = (paths.get('media') or _rel(d / 'media')) + '/page/views'
    ledger = _ledger()
    formal = _json(d / 'evaluation' / 'formal_table_v5.json', {}) or {}
    benefit = _json(d / 'evaluation' / 'benefit_summary.json', {}) or {}
    formal_by_cand = {}
    for case in formal.get('cases') or []:
        if case.get('candidate'):
            formal_by_cand[case['candidate']] = case
    cands = []
    cdir = d / 'candidates'
    if cdir.exists():
        for p in sorted(cdir.iterdir()):
            if not p.is_dir():
                continue
            clean = _json(p / 'clean' / 'clean.json', {}) or {}
            align = _json(p / 'align.json', {}) or {}
            if not clean and not align:
                continue
            cid = clean.get('id') or p.name
            identity = (re.search(r'/cache/[0-9a-f]{2}/([0-9a-f]{64})/', str(clean.get('candidate') or '')) or [None, None])[1]
            best = (align.get('best') or {}) if isinstance(align, dict) else {}
            native = best.get('native') or {}
            ver = clean.get('verify') or {}
            pre = clean.get('precheck') or {}
            ap = align.get('pass') if align else None
            fc = formal_by_cand.get(cid) or {}
            fm = fc.get('candidate_metrics') or {}
            if fc:
                planning = fc.get('candidate_planning_eligible')
                strict = fc.get('candidate_strict_pass')
                planning_status = ('IoU-only' if fm.get('hit_part_cap') else 'eligible') if planning else 'ineligible'
            elif align:
                planning = False
                strict = ap
                planning_status = 'ineligible (align fail)'
            else:
                planning, strict, planning_status = None, None, 'not_evaluated'
            cands.append({'id': cid, 'source_kind': 'lux3d', 'task_id': ledger.get(identity),
                          'identity': identity, 'glb': clean.get('candidate'),
                          'raw_sha': clean.get('raw_sha'), 'clean_sha': clean.get('clean_sha'),
                          'clean_verdict': pre.get('verdict'), 'clean_pass': pre.get('verdict') == 'ok',
                          'faces_after': ver.get('faces_after'), 'thin_ratio': ver.get('thin_ratio'),
                          'extents_m': ver.get('extents_m'), 'align_present': bool(align),
                          'align_pass': ap, 'strict_pass': strict if fc else ap,
                          'planning_eligible': planning, 'planning_status': planning_status,
                          'hit_part_cap': fm.get('hit_part_cap'),
                          'formal_case': fc.get('case'),
                          'alignment_status': 'pass' if ap else ('fail' if align else 'not_run'),
                          'iou': fm.get('mask_iou', native.get('mask_iou')),
                          'p95_mm': fm.get('vis_pt_p95_mm', native.get('vis_pt_p95_mm')),
                          'freespace': fm.get('freespace_violation', native.get('freespace_violation')),
                          'threshold_p95_mm': best.get('threshold_p95_mm'),
                          'scale': best.get('scale'), 'yaw_deg': best.get('yaw'),
                          'orientation_ambiguous': align.get('orientation_ambiguous'),
                          'align_wall_s': align.get('wall_s'), 'views': _views(cid, view_dir),
                          'fixture': False})
    obs = []
    odir = d / 'observations'
    if odir.exists():
        for p in sorted(odir.iterdir()):
            if not p.is_dir():
                continue
            direction = _json(p / 'direction.json', {}) or {}
            ob = _json(p / 'observation.json', {}) or {}
            imgs = [{'path': _rel(p / fn), 'label': lab, 'name': fn}
                    for fn, lab in (('rgb.png', '原观测 RGB'), ('mask.png', '可见面 mask'),
                                    ('crop_white.png', '送生成图（白底方裁）')) if (p / fn).exists()]
            missing = [n for n in ('rgb.png', 'mask.png', 'depth.npy') if not (p / n).exists()]
            usable = bool(imgs) and (p / 'depth.npy').exists()
            obs.append({'id': ob.get('observation_id') or direction.get('observation_id') or p.name,
                        'dir': _rel(p), 'azimuth_deg': direction.get('azimuth_deg'),
                        'visible': ob.get('visible') or direction.get('visible') or {},
                        'images': imgs, 'usable': usable,
                        'reason': '' if usable else ('观测包不完整：缺 ' + '、'.join(missing) if missing else '观测图不完整'),
                        'note': direction.get('note') or ''})
    cases = []
    kdir = d / 'cases'
    if kdir.exists():
        for p in sorted(kdir.iterdir()):
            if not p.is_dir():
                continue
            s = _json(p / 'summary.json')
            if not isinstance(s, dict):
                continue
            acts = []
            for a, v in (s.get('by_action') or {}).items():
                if isinstance(v, dict):
                    acts.append({'action': a, 'n': v.get('n_run', 0), 'success': v.get('success', 0),
                                 'outcomes': v.get('outcomes') or [], 'na': v.get('not_applicable')})
            cases.append({'id': p.name, 'case': s.get('case') or p.name,
                          'truth_sha': s.get('truth_world_sha'), 'collision_sha': s.get('truth_collision_sha'),
                          'coacd_parts': s.get('coacd_parts'), 'visible': s.get('visible') or {},
                          'flags': s.get('flags') or {}, 'actions': acts, 'soil_mode': s.get('soil_mode')})
    twins = _json(kdir / 'twins' / 'twins_registry.json', {}) if kdir.exists() else {}
    twin_rows = (twins or {}).get('rows') or []
    scan_root = kdir / 'twins' / 'scans'
    twin_scans = len(list(scan_root.glob('*/summary.json'))) if scan_root.exists() else 0
    soil = _json(d / 'soil' / 'acceptance.json', {}) or {}
    stages = soil.get('stages') or {}
    soil_rows = []
    for k in sorted(stages):
        s = stages[k]
        if isinstance(s, dict):
            soil_rows.append({'key': k, 'stage': s.get('stage') or k, 'summary': s.get('summary') or {},
                              'raw': s,
                              'note': s.get('note') or s.get('limitation') or s.get('rule') or '',
                              'verdict': s.get('verdict'),
                              'geometry_sinkage_implemented': s.get('geometry_sinkage_implemented'),
                              'formula_max_sink_m': s.get('formula_max_sink_m'),
                              'measured_wheel_penetration_m': s.get('measured_wheel_penetration_m'),
                              'wall_s': s.get('wall_s'), 'rows_n': len(s.get('rows') or [])})
    stage_g = next((x for x in soil_rows if x['key'] == 'g'), {})
    sp = d / 'soil' / 'stability_1000.jsonl'
    stability = len(_jsonl(sp)) if sp.exists() else 0
    pf = _json(d / 'verify' / 'preflight.json', {}) or {}
    checks = pf.get('checks') or []
    pf_pass = sum(1 for c in checks if c.get('pass'))
    batch = {'batch_id': m.get('batch_id') or entry.get('batch_id'), 'manifest': _rel(d / 'manifest.json'),
             'dir': entry['dir'], 'data': m, 'label': entry.get('label')}
    runs = _batch_runs(batch)
    n_clean = sum(1 for c in cands if c['clean_pass'])
    n_align_done = sum(1 for c in cands if c['align_present'])
    n_align = sum(1 for c in cands if c['align_pass'])
    n_strict = sum(1 for c in cands if c['strict_pass'] is True)
    n_planning = sum(1 for c in cands if c['planning_eligible'] is True)
    n_ineligible = sum(1 for c in cands if c['planning_eligible'] is False)
    n_obs = sum(1 for o in obs if o['usable'])
    states = []
    if not runs:
        states.append(('bad', '正式比较未运行', 'evaluation/ 下还没有 summary + records/execution；不补造 decision。'))
    if cands:
        states.append(('warn', 'strict %d/%d；planning %d/%d（IoU-only）' % (n_strict, len(cands), n_planning, len(cands)),
                       'C_R01_face12k 仅 IoU 通过（0.8622）；P95 11.0 mm > 9.957、freespace 0.5106、'
                       'hit_part_cap=true；另外 2 个 ineligible。strict 与 planning 分列，不混用。'))
    bad_obs = [o['id'] for o in obs if not o['usable']]
    if bad_obs:
        states.append(('warn', '部分观察不可用', '、'.join(bad_obs) + '：缺 RGB/depth/mask。'))
    if stage_g:
        states.append(('warn', '月壤是受限近似', 'stage G=%s；geometry_sinkage_implemented=%s。' % (stage_g.get('verdict'), stage_g.get('geometry_sinkage_implemented'))))
    if pf:
        states.append(('ok' if pf_pass == len(checks) else 'warn', '预检 %d/%d 通过' % (pf_pass, len(checks)), 'preflight.json；失败项不隐藏。'))
    return {'run': entry['run'], 'kind': 'batch', 'label': entry.get('label') or ('批次 · ' + str(m.get('batch_id'))),
            'batch_id': m.get('batch_id') or entry.get('batch_id'), 'case_id': m.get('batch_id'),
            'dir': entry['dir'], 'mode': 'batch', 'mode_note': '批次 manifest 入口：只读，不触发创建。',
            'fixture': False, 'role': 'batch', 'manifest': m, 'manifest_path': _rel(d / 'manifest.json'),
            'paths': paths, 'candidates': cands, 'observations': obs, 'cases': cases,
            'twins': {'rows': twin_rows, 'n': len(twin_rows), 'scans': twin_scans},
            'soil': {'acceptance': soil, 'rows': soil_rows, 'stage_g': stage_g, 'stability': stability},
            'preflight': {'data': pf, 'checks': checks, 'pass': pf_pass, 'fail': len(checks) - pf_pass},
            'runs': runs, 'n_clean': n_clean, 'n_align': n_align,
            'n_align_done': n_align_done, 'n_strict': n_strict,
            'n_planning': n_planning, 'n_ineligible': n_ineligible,
            'formal': formal, 'benefit': benefit,
            'n_obs_ok': n_obs, 'states': states, 'view_dir': view_dir}


def load_run(name):
    e = _find(name)
    return _load_batch(e) if e.get('kind') == 'batch' else _load_run_dir(e)


# ---------------------------------------------------------------- HTML
CSS = r"""
*{box-sizing:border-box}:root{--bg:#0b0a0d;--panel:#141219;--line:#282431;--ink:#ece5da;--mut:#9a919f;--gold:#c9a86a;--ok:#7fe0b0;--bad:#ff9a9a;--warn:#f0c674;--blue:#8bb8e8}
body{margin:0;background:var(--bg);color:var(--ink);font:13.5px/1.6 system-ui,-apple-system,"Noto Sans CJK SC","Noto Sans SC","WenQuanYi Zen Hei",sans-serif}
a{color:var(--blue)}header{padding:20px 26px 14px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#15121b,#0d0b11)}
header h1{margin:0;font-size:22px}header h1 span{color:var(--gold);font-size:14px;margin-left:10px;font-weight:500}
header p{margin:6px 0 0;color:var(--mut);font-size:12.5px;max-width:1250px}.eyebrow{color:var(--gold);font-size:11px;letter-spacing:1.6px;margin-bottom:4px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}.chip{border:1px solid var(--line);border-radius:99px;padding:2px 9px;font-size:11.5px;color:var(--mut);background:#120f16}
.chip.gold{border-color:#4a3d24;color:#e4c98e;background:#1b160d}.chip.bad{border-color:#5a2c2c;color:#ffb3b3;background:#1e1012}
.wrap{display:grid;grid-template-columns:310px minmax(0,1fr);gap:16px;padding:16px 22px 34px;max-width:1800px;margin:0 auto}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 15px;margin-bottom:14px}
.card h2{margin:0 0 10px;font-size:13px;color:var(--gold);letter-spacing:.8px;display:flex;gap:8px;align-items:center}
.num{display:inline-flex;width:21px;height:21px;border-radius:99px;background:#2a2432;color:var(--gold);align-items:center;justify-content:center;font-size:11px;flex:0 0 auto}
.small{font-size:11.5px}.muted{color:var(--mut)}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.gold{color:var(--gold)}.mono{font-family:ui-monospace,Menlo,monospace}
select{width:100%;padding:8px 9px;background:#0e0c12;color:var(--ink);border:1px solid #332d3d;border-radius:7px;font-size:12.5px}
.kv{display:grid;grid-template-columns:88px minmax(0,1fr);gap:3px 8px;font-size:11.5px}.kv dt{color:var(--mut)}.kv dd{margin:0;word-break:break-all}
.badge{display:inline-block;padding:1px 7px;border-radius:5px;font-size:10.5px;border:1px solid #3a3346;color:var(--mut);background:#17141d}
.badge.ok{color:#9be7c0;border-color:#28523e;background:#0f1b15}.badge.bad{color:#ffb3b3;border-color:#5a2c2c;background:#1e1012}
.badge.warn{color:#f3d393;border-color:#5b4a24;background:#1d180d}.badge.gold{color:#e4c98e;border-color:#4a3d24;background:#1b160d}.badge.blue{color:#b7d4f2;border-color:#2b4660;background:#101a24}
.fixture{background:#3a1220;border:1px solid #7c2942;color:#ffb8c9;padding:5px 10px;border-radius:7px;font-size:12px;font-weight:600;margin-bottom:10px}
.states{margin-bottom:12px}.state{border:1px solid var(--line);border-left:4px solid var(--warn);background:#17130f;border-radius:7px;padding:8px 11px;margin-bottom:7px;font-size:12px}
.state.bad{border-left-color:var(--bad);background:#1a1012}.state.ok{border-left-color:var(--ok);background:#0f1a15}.state b{margin-right:6px}
.runbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}.runbar h2{margin:0;font-size:17px}
.screens{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.screens .card{margin-bottom:0}.span2{grid-column:1/-1}
.imgrow{display:flex;flex-wrap:wrap;gap:9px;margin:8px 0}figure{margin:0;background:#0d0b11;border:1px solid var(--line);border-radius:8px;padding:5px;max-width:100%}
figure img{display:block;width:100%;max-height:230px;object-fit:contain;border-radius:5px;background:#0b0a0d}
figcaption{font-size:10.5px;color:var(--mut);margin-top:4px;line-height:1.35}
.obsfig,.candfig,.truthfig{width:calc(33.33% - 6px);min-width:150px}
table{border-collapse:collapse;width:100%;font-size:11.5px;margin-top:5px}th,td{border-bottom:1px solid #25212d;padding:4px 5px;text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500;background:#100e15}td.num{text-align:right;font-variant-numeric:tabular-nums}tr.sel td{background:#1b170f}tr.diag td{background:#1a1012}
#s3 table{font-size:10.8px}#s3 th,#s3 td{padding:3px 4px}.cell-ok{color:#9be7c0}.cell-bad{color:#ffb3b3}.cell-mid{color:#f3d393}
.note{font-size:11.5px;color:var(--mut);margin-top:8px;border-top:1px dashed #2a2533;padding-top:7px}.note b{color:#cfc5b8}
.big{font-size:19px;font-weight:700;color:var(--gold)}.stat{display:flex;flex-wrap:wrap;gap:7px;margin:6px 0 8px}
.stat span{border:1px solid var(--line);border-radius:7px;padding:4px 8px;font-size:11.5px;background:#100e15}.stat b{color:var(--ink)}
details{margin-top:8px}summary{cursor:pointer;color:var(--mut);font-size:11.5px}
footer{color:#6f6878;font-size:11px;padding:0 26px 26px;max-width:1800px;margin:0 auto}
@media(max-width:1100px){.wrap{grid-template-columns:1fr}.screens{grid-template-columns:1fr}}
"""


def _fig(rel, label, cls='', alt=None):
    if not _exists(rel):
        return ''
    return ('<figure class="%s"><img loading="eager" src="/img?p=%s" alt="%s"><figcaption>%s</figcaption></figure>'
            % (cls, quote(rel), _esc(alt or label), _esc(label)))


def _states(states):
    if not states:
        return ''
    out = ['<div class="states">']
    for sev, title, body in states:
        out.append('<div class="state %s"><b>%s</b>%s</div>'
                   % ('ok' if sev == 'ok' else ('bad' if sev == 'bad' else ''), _esc(title), _esc(body)))
    out.append('</div>')
    return ''.join(out)


def _page(title, body, sidebar):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><style>%s</style><header><div class="eyebrow">看不见的那一面 · UNSEEN TESTBENCH</div>'
            '<h1>生成式 3D 行动前推演 <span>真实输入 → 生成候选 → 预演 → 决定 → 独立真值执行</span></h1>'
            '<p>页面只读已落盘的真实产物：输入是仿真 RGB-D，执行是独立仿真，不是真实机器人。'
            '候选工程资格与 strict 几何一致性分列；当前收益结论是 NOT_ESTABLISHED。</p>'
            '<div class="chips">%s</div></header><div class="wrap"><aside>%s</aside><main>%s</main></div>'
            '<footer>所有图片、数字和结论均来自 runs/、cases/ 下已落盘产物；页面不调用生成 API。'
            '页面不把 fixture 标成 Lux3D，也不把预演动画标成真实执行回放。</footer>'
            '<script>function jump(s){if(s.value)location.href="/?run="+encodeURIComponent(s.value)}</script></html>'
            % (_esc(title), CSS,
               _chip('只读缓存 / 不新建任务', 'gold') + _chip('仿真 RGB-D 输入') + _chip('独立仿真执行')
               + _chip('月壤半经验 · 几何下陷未实现', 'bad') + _chip('benefit NOT_ESTABLISHED', 'bad'),
               sidebar, body))


def _select(cases, cur):
    opts = []
    for c in cases:
        tag = ' [FIXTURE]' if c['fixture'] else (' [SUPERSEDED]' if c.get('superseded') else (' [批次]' if c['kind'] == 'batch' else ''))
        opts.append('<option value="%s"%s>%s%s</option>'
                    % (_esc(c['run']), ' selected' if c['run'] == cur else '',
                       _esc(c['label']), _esc(tag)))
    return ('<div class="card"><h2>选择运行</h2><select onchange="jump(this)">%s</select>'
            '<div class="small muted" style="margin-top:7px">URL 支持 <span class="mono">?run=NAME</span>；'
            '打开任意条目都不会触发付费。</div></div>') % ''.join(opts)


def _sidebar(d, cases, mode_label):
    s = _select(cases, d.get('run'))
    src = ('<dl class="kv"><dt>run</dt><dd class="mono">%s</dd><dt>目录</dt><dd class="mono">%s</dd>'
           '<dt>case</dt><dd>%s</dd><dt>mode</dt><dd>%s</dd></dl>'
           % (_esc(d.get('run')), _esc(d.get('dir')), _esc(d.get('case_id')), _badge(mode_label, 'gold')))
    if d.get('fixture'):
        src = '<div class="fixture">FIXTURE — 非真实 Lux3D 生成候选；只验证接口/格式，不计真实成绩</div>' + src
    s += '<div class="card"><h2>数据来源</h2>%s<div class="small muted" style="margin-top:6px">%s</div></div>' % (src, _esc(d.get('mode_note')))
    rows = []
    for k, lab in (('summary', 'summary'), ('decision', 'decision'), ('records', 'records'), ('execution', 'execution')):
        p = (d.get('targets') or {}).get(k)
        rows.append('<dt>%s</dt><dd class="mono">%s</dd>' % (lab, _esc(p) if p else '<span class="warn">missing</span>'))
    s += '<div class="card"><h2>本次读取的文件</h2><dl class="kv">%s</dl><div class="small muted" style="margin-top:7px">缺项显示 missing；不会用空白冒充成功。</div></div>' % ''.join(rows)
    s += ('<div class="card"><h2>统一口径</h2><div class="small muted">'
          '<p><b class="gold">strict</b>：IoU/P95/freespace 的观测几何诊断，失败仍是失败。</p>'
          '<p><b class="gold">planning eligibility</b>：工程入场政策，独立于 strict；通过不等于安全或收益。</p>'
          '<p><b class="gold">月壤</b>：Bekker 压实阻力 + 等效库仑牵引；整机仍刚性，几何下陷未实现。</p>'
          '</div></div>')
    return s


def _obs_section(d):
    o = d['observation']
    b = []
    if o['images']:
        b.append('<div class="imgrow">' + ''.join(_fig(i['path'], i['label'], 'obsfig') for i in o['images']) + '</div>')
    elif d.get('trigger_only'):
        b.append('<div class="state"><b>观察未触发（不适用）</b>候选一致，不需要第二次观察；没有第二观察图。</div>')
    else:
        b.append('<div class="state bad"><b>观察不可用</b>%s</div>' % _esc(o['reason'] or '没有观测图。'))
    v, cam = o['visible'], o['camera']
    rows = []
    if v:
        rows += [('可见像素', _f(v.get('n_pixels'))), ('前沿 x', '%s m' % _f(v.get('x_front'), 4)),
                 ('W_vis', '%s m' % _f(v.get('W_vis'), 4)), ('H_vis', '%s m' % _f(v.get('H_vis'), 4))]
    if cam:
        wp = cam.get('world_pos') or []
        rows += [('相机位置', '(' + ', '.join(_f(x, 3) for x in wp) + ')' if wp else '—'),
                 ('俯仰', '%s°' % _f(cam.get('pitch_deg'), 2)), ('深度约定', _f(cam.get('depth_convention')))]
    if rows:
        b.append('<dl class="kv">%s</dl>' % ''.join('<dt>%s</dt><dd>%s</dd>' % (_esc(k), _esc(x)) for k, x in rows))
    if d['kind'] == 'look':
        lo = o['look']
        b.append('<div class="note"><b>观察方向 / 深度用途：</b>抬高后第二视角；基線 %s m，视线角 %s°，移动 %s s，制动稳定=%s。'
                 '深度只用于第二观察 mask 与筛选 IoU，不反推真值背面。</div>'
                 % (_f(lo.get('cam_baseline_m'), 3), _f(lo.get('bearing_change_deg'), 2),
                    _f(lo.get('move_seconds'), 2), _f((lo.get('brake') or {}).get('stable'))))
    else:
        az = (o['direction'] or {}).get('azimuth_deg')
        b.append('<div class="note"><b>观察方向 / 深度用途：</b>%s深度（positive_camera_minus_z）只用于可见面分割与 '
                 'x_front / W_vis / H_vis；不读背面深度。决策输入是可见量或候选几何。</div>'
                 % (('石头相对相机偏航 %s°；' % _f(az, 1)) if az is not None else '机器人前视；'))
    if o.get('note'):
        b.append('<div class="small muted" style="margin-top:5px">%s</div>' % _esc(o['note']))
    return '<section class="card" id="s1"><h2><span class="num">1</span>看见 · 真实输入与观测</h2>%s</section>' % ''.join(b)


def _cand_table(cands):
    rows = []
    for c in cands:
        rows.append('<tr><td>%s</td><td>%s</td><td class="mono">%s</td><td class="mono">%s</td><td class="num">%s</td></tr>'
                    % (_esc(c['id']), _esc(c['source_kind']), _esc(c.get('task_id') if c.get('task_id') is not None else '—'),
                       _esc(_short(c.get('world_sha'), 16)), _esc(c.get('coacd_parts') if c.get('coacd_parts') is not None else '—')))
    return ('<table><tr><th>候选</th><th>来源</th><th>task_id</th><th>world SHA</th><th>CoACD 部件</th></tr>%s</table>' % ''.join(rows))


def _elig(cands):
    rows = []
    for c in cands:
        if c.get('fixture'):
            st = _badge('fixture：不计 strict', 'warn')
            pl = _badge('fixture 路径', 'warn')
        else:
            st = (_badge('strict pass', 'ok') if c.get('strict_pass') is True
                  else _badge('strict fail', 'bad') if c.get('strict_pass') is False
                  else _badge('strict not run', 'warn'))
            pl = (_badge('eligible', 'ok') if c.get('planning_eligible') is True
                  else _badge('not eligible', 'bad') if c.get('planning_eligible') is False
                  else _badge('not evaluated', 'warn'))
        met = []
        for k, lab in (('iou', 'IoU'), ('p95_mm', 'P95 mm'), ('freespace', 'freespace'), ('thin_ratio', 'thin_ratio')):
            if c.get(k) is not None:
                met.append('%s %s' % (lab, _f(c[k], 4 if k in ('iou', 'freespace') else 1)))
        rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (_esc(c['id']), st, pl, _esc('；'.join(met) or '—')))
    return ('<table><tr><th>候选</th><th>strict 几何</th><th>planning eligibility</th><th>指标</th></tr>%s</table>'
            '<div class="note">strict 与 planning eligibility 分列：前者是观测一致性诊断，后者是工程入场政策；'
            '两者都不是安全证明，也不等于收益成立。</div>' % ''.join(rows))


def _imagine(d):
    cs = d['candidates']
    b = ['<div class="stat"><span>候选 <b>%d</b></span><span>有 3D 视图 <b>%d</b></span>'
         '<span>strict 通过 <b>%d</b></span><span>planning eligible <b>%d</b></span><span>fixture <b>%s</b></span></div>'
         % (len(cs), sum(1 for c in cs if c['views']), sum(1 for c in cs if c.get('strict_pass') is True),
            sum(1 for c in cs if c.get('planning_eligible') is True), '是' if d['fixture'] else '否')]
    if not cs:
        b.append('<div class="state bad"><b>无候选 / no candidate</b>该运行没有登记真实生成候选；不补造 H5。</div>')
        return '<section class="card" id="s2"><h2><span class="num">2</span>想象 · 候选与有效候选数</h2>%s</section>' % ''.join(b)
    b.append(_cand_table(cs))
    for c in cs:
        if c['views']:
            b.append('<div class="imgrow">' + ''.join(_fig(v['path'], '%s · %s' % (c['id'], v['label']), 'candfig') for v in c['views']) + '</div>')
        else:
            b.append('<div class="small warn" style="margin-top:6px">%s：尚无候选三维视图。</div>' % _esc(c['id']))
    b.append(_elig(cs))
    if d['fixture']:
        b.append('<div class="fixture" style="margin-top:8px">FIXTURE 候选：不是 Lux3D 生成结果，不能用于真实候选能力/收益主张。</div>')
    return '<section class="card" id="s2"><h2><span class="num">2</span>想象 · 候选与有效候选数</h2>%s</section>' % ''.join(b)


def _cell(o):
    if not o or not o.get('n'):
        return '<td class="muted">—</td>'
    s, n = o['success'], o['n']
    return '<td class="%s">%d/%d</td>' % ('cell-ok' if s == n else ('cell-bad' if s == 0 else 'cell-mid'), s, n)


def _reh_section(d):
    gs = d['rehearsal_groups']
    b = []
    if gs:
        cols = []
        for g in gs:
            for a in g['options']:
                if a not in cols:
                    cols.append(a)
        cols = [a for a in ACTIONS if a in cols] + [a for a in cols if a not in ACTIONS]
        rows = []
        for g in gs:
            label = g['method'] + ((' / ' + g['candidate_id']) if g['candidate_id'] else '')
            short = {'not_applicable_by_public_visibility': 'n/a',
                     'not_applicable': 'n/a', 'time_limit': 'timeout'}
            reasons = ', '.join('%s×%d' % (short.get(k, k), v) for k, v in sorted(g['reasons'].items())) or '—'
            rows.append('<tr><td>%s</td>%s<td class="small">%s</td></tr>'
                        % (_esc(label), ''.join(_cell(g['options'].get(a)) for a in cols), _esc(reasons)))
        b.append('<table><tr><th>方法 / 候选</th>%s<th>失败阶段</th></tr>%s</table>'
                 % (''.join('<th>%s</th>' % _esc(a) for a in cols), ''.join(rows)))
        b.append('<div class="note"><b>预演不是执行：</b>每格是 成功/总初态；失败阶段来自 reason（tipped / time_limit / abort …）。'
                 '预演只在候选/假设几何上进行，真值执行在画面 5。</div>')
    elif d.get('trigger_only'):
        b.append('<div class="state"><b>不适用</b>观察未触发（候选一致），因此没有第二观察后的预演。'
                 '这不是缺失或失败。</div>')
    else:
        b.append('<div class="state bad"><b>没有预演记录 / not run</b>试走矩阵为空；不把空白当“全部成功”。</div>')
    six = d.get('six') or {}
    if six.get('methods'):
        rr = [('<tr><td>%s</td><td>%s</td><td>规则法，不做候选预演（不是缺失）</td></tr>'
               % (_esc(m.get('method')), _esc(m.get('selected_action') or '—')))
              for m in six['methods'] if m.get('method') in ('B0_blind', 'B1_height')]
        if rr:
            b.append('<table style="margin-top:8px"><tr><th>规则法</th><th>动作</th><th>说明</th></tr>%s</table>' % ''.join(rr))
    diag = (d.get('six') or {}).get('diagnostic')
    if diag or any('diagnostic' in (g['method'] or '') for g in gs):
        x = diag or {}
        ev = x.get('evidence')
        ev = ev.get('rule') if isinstance(ev, dict) else ev
        b.append('<div class="card" style="margin:10px 0 0;border-color:#5a2c2c"><h2 style="color:#ffb3b3">W_width_rule · DEVELOPMENT_DIAGNOSTIC</h2>'
                 '<div class="small">这不是正式六方法之一，也不是缺失字段。问题只是：仅靠可见宽度能否选对动作。</div>'
                 '<table><tr><th>选中动作</th><th>成功</th><th>规则证据</th><th>说明</th></tr>'
                 '<tr><td>%s</td><td>%s/%s</td><td>%s</td><td>%s</td></tr></table>'
                 '<div class="small muted" style="margin-top:5px">%s</div></div>'
                 % (_esc(x.get('selected_action') or '—'), _esc(x.get('success') if x.get('success') is not None else '—'),
                    _esc(x.get('n_exec') or '—'), _esc(ev),
                    _esc(x.get('label') or 'DEVELOPMENT_DIAGNOSTIC'),
                    _esc(x.get('note') or '不替换六方法；单独列在诊断区。')))
    return ('<section class="card span2" id="s3"><h2><span class="num">3</span>试走 · 候选×动作预演与失败阶段</h2>'
            '%s</section>' % ''.join(b))


def _decision(d):
    kind, dec, chosen = d['kind'], d.get('decision') or {}, d.get('chosen')
    b = []
    if kind == 'pipeline':
        b.append('<div class="big">选择 %s</div>' % _esc(chosen or '—'))
        b.append('<div class="small muted">规则 %s；%s</div>' % (_esc(dec.get('rule')), _esc(dec.get('reason_text') or '')))
        if dec.get('no_robust_option'):
            b.append('<div class="state bad"><b>没有稳健通行动作</b>安全回退 A0；不是成功。</div>')
        b.append('<div class="note"><b>什么改变了决定：</b><br>%s</div>' % '<br>'.join('· ' + _esc(x) for x in d['changed']))
        stats = dec.get('stats') or {}
        if stats:
            rows = []
            for a in ACTIONS:
                st = stats.get(a)
                if isinstance(st, dict):
                    rows.append('<tr%s><td>%s</td><td class="num">%s</td><td class="num">%s</td><td>%s</td></tr>'
                                % (' class="sel"' if a == chosen else '', _esc(a), _f(st.get('R'), 2),
                                   _f(st.get('mean_c'), 3), _esc('、'.join((st.get('f') or {}).keys()) or '—')))
            b.append('<table><tr><th>动作</th><th>worst-case R</th><th>mean cost</th><th>候选</th></tr>%s</table>' % ''.join(rows))
    elif kind == 'six':
        six = d.get('six') or {}
        b.append('<div class="small muted">六方法各自先在自己的假设上预演，再在同一独立真值上执行；没有单一“全局决定”。</div>')
        rows = []
        for m in six.get('methods') or []:
            name = m.get('method')
            dm = (six.get('dec_by') or {}).get(name) or {}
            ev = dm.get('evidence')
            ev = ev.get('rule') if isinstance(ev, dict) else ev
            no = m.get('no_candidate')
            rows.append('<tr%s><td>%s</td><td>%s</td><td>%s</td></tr>'
                        % (' class="diag"' if name == 'H5_lux3d' else '', _esc(name),
                           _esc(m.get('selected_action') if not no else 'A0 / no candidate'),
                           _esc(('no candidate: ' if no else '') + str(ev or '—'))))
        b.append('<table><tr><th>方法</th><th>决定动作</th><th>依据</th></tr>%s</table>' % ''.join(rows))
        h5 = next((m for m in six.get('methods') or [] if m.get('method') == 'H5_lux3d'), {})
        if h5.get('no_candidate'):
            b.append('<div class="state bad"><b>H5 无候选</b>没有 planning_eligible 的生成候选；保留 no_candidate，不补造动作。</div>')
        ut = next((m.get('selected_action') for m in six.get('methods') or [] if m.get('method') == 'U_truth'), '—')
        b.append('<div class="note"><b>什么改变了决定：</b>B2_box 在盒子先验上选 D1；H5 在真实候选上选 %s；U_truth 选 %s。'
                 '所有方法最终都成功，动作差异没有带来成功差异；不能写成 H5 收益。</div>'
                 % (_esc(h5.get('selected_action') or '—'), _esc(ut)))
    elif kind == 'look' and dec.get('trigger_only'):
        tr = dec.get('trigger') or {}
        if tr.get('triggered'):
            b.append('<div class="big">观察已触发（尚未执行）</div>')
            b.append('<div class="note"><b>为什么还没有“再看一眼”结果：</b>%s。'
                     'trigger/v1 已判定需要观察，但本产物止于 trigger_only；没有第二观察图、decision 或执行。'
                     '这不是收益证据，也不是执行失败。</div>' % _esc(tr.get('reason') or '候选动作分歧'))
        else:
            b.append('<div class="big">未触发第二次观察</div>')
            b.append('<div class="note"><b>为什么没有“再看一眼”：</b>%s。'
                     '候选一致时不做观察；这不是 decision，也不是执行成功。</div>'
                     % _esc(tr.get('reason') or '候选一致'))
        b.append('<div class="small muted">规则 %s</div>' % _esc(tr.get('rule') or 'trigger/v1'))
        b.append('<div class="stat"><span>triggered <b>%s</b></span>'
                 '<span>chosen_set <b>%s</b></span>'
                 '<span>safe_sets <b>%s</b></span></div>'
                 % (_esc(tr.get('triggered')), _esc('/'.join(tr.get('chosen_set') or []) or '—'),
                    _esc(' | '.join('/'.join(x) for x in (tr.get('safe_sets') or [])) or '—')))
    elif kind == 'look':
        b.append('<div class="big">选择 %s</div>' % _esc(chosen or '—'))
        b.append('<div class="small muted">规则 %s</div>' % _esc(dec.get('rule') or '—'))
        b.append('<div class="note"><b>为什么：</b>第二观察保留了候选，但 8 个动作没有一个在 kept 候选的全部初态上通过；按规则退到 A0。A0 是安全回退，不是任务成功。</div>')
        b.append('<div class="stat"><span>观察耗时 <b>%s s</b></span><span>含观察执行代价 <b>%s</b></span>'
                 '<span>exec_seconds <b class="warn">%s</b></span><span>total_seconds <b class="warn">%s</b></span></div>'
                 % (_f(dec.get('observation_seconds'), 2), _f(dec.get('exec_cost_including_observation'), 2),
                    _f(dec.get('exec_seconds')), _f(dec.get('total_seconds'))))
        if dec.get('exec_seconds') is None or dec.get('total_seconds') is None:
            b.append('<div class="state bad"><b>计时字段缺失</b>decision 的 exec_seconds / total_seconds 为 null；不填 0。</div>')
        if dec.get('decision_sha256'):
            b.append('<div class="small muted mono">decision SHA %s</div>' % _esc(_short(dec['decision_sha256'], 20)))
    else:
        b.append('<div class="state bad"><b>缺少 decision</b>没有可显示的决定。</div>')
    return '<section class="card" id="s4"><h2><span class="num">4</span>决定 · 选了什么、为什么、什么改变了它</h2>%s</section>' % ''.join(b)


def _exec_table(gs, chosen=None):
    rows = []
    for g in gs:
        reasons = ', '.join('%s×%d' % (k, v) for k, v in sorted(g['reasons'].items())) or '—'
        rows.append('<tr%s><td>%s</td><td>%s</td><td class="num">%d</td><td class="num">%d/%d/%d</td><td>%s</td><td class="num">%s</td></tr>'
                    % (' class="sel"' if chosen and 'H5' in g['method'] else '', _esc(g['method']),
                       _esc('、'.join(g['actions'].keys()) or '—'), g['n'], g['success'], g['abort'],
                       g['fail'], _esc(reasons), _f(g['sim'], 2) if g['sim_n'] else '—'))
    return ('<table><tr><th>方法</th><th>动作</th><th>n</th><th>成功/刹停/失败</th><th>失败阶段</th><th>Σ sim 时间 (s)</th></tr>%s</table>' % ''.join(rows))


def _replay(rows):
    if not rows:
        return '<div class="state bad"><b>没有逐初态执行记录</b>无法做数值回放。</div>'
    out = []
    for r in rows[:12]:
        out.append('<tr><td>%s</td><td class="num">%s</td><td>%s</td><td>%s</td><td class="num">%s</td><td class="num">%s</td><td>%s</td></tr>'
                   % (_esc(r.get('method')), _esc(r.get('seed')), _esc(r.get('option')),
                      _esc(r.get('reason') or ('success' if r.get('success') else '—')),
                      _f(r.get('t_end'), 2), _f(r.get('final_x'), 3) if r.get('final_x') is not None else '—',
                      _esc(r.get('contact') or '—')))
    return ('<table><tr><th>方法</th><th>初态</th><th>动作</th><th>结果/失败阶段</th><th>t_end (s)</th><th>final x (m)</th><th>接触</th></tr>%s</table>' % ''.join(out))


def _exec(d):
    if d['kind'] == 'batch':
        return _batch_exec(d)
    b = []
    if not d['candidates']:
        ib = _badge('无候选：独立闭环不适用', 'warn')
    elif d['fixture']:
        ib = _badge('FIXTURE：非 Lux3D 独立闭环', 'warn')
    elif d['independent_truth'] is True:
        ib = _badge('独立真值：candidate ≠ truth', 'ok')
    elif d['independent_truth'] is False:
        ib = _badge('同一资产：不能算独立闭环', 'bad')
    else:
        ib = _badge('独立真值：未记录', 'warn')
    b.append('<div class="stat">%s<span>truth SHA <b class="mono">%s</b></span>'
             '<span>candidate world SHA <b class="mono">%s</b></span></div>'
             % (ib, _esc(_short(d['truth_sha'], 18)), _esc(_short(d['candidate_world_sha'], 18))))
    if d['truth_views']:
        b.append('<div class="imgrow">' + ''.join(_fig(v['path'], '真值 · ' + v['label'], 'truthfig') for v in d['truth_views']) + '</div>')
    else:
        b.append('<div class="small warn">尚无真值揭晓图（只显示逐初态记录）。</div>')
    gs = d['execution_groups']
    if gs:
        b.append(_exec_table(gs, d['chosen']))
        b.append('<div class="note"><b>独立真值执行</b>：决策冻结后在同一 truth 上执行；H5 与 B0 若复用同一 R1 行会显示同数。'
                 '这里不是动画，也不是把预演当执行。</div>')
        by = {g['method']: g for g in gs}
        h5, b0 = by.get('H5_lux3d'), by.get('B0_blind')
        if h5 and b0 and not d['fixture']:
            same = h5['success'] == b0['success'] and h5['n'] == b0['n']
            b.append('<div class="note"><b>收益判读：</b>H5 %d/%d，B0 %d/%d → %s。当前结论仍是 NOT_ESTABLISHED。</div>'
                     % (h5['success'], h5['n'], b0['success'], b0['n'],
                        '完全相同，不能声称 H5 更好' if same else '有差异，但样本/协议不支持统计外推'))
            if not same and any(c.get('strict_pass') is False for c in d.get('candidates') or []):
                b.append('<div class="state bad"><b>不能升级为收益</b>该候选 strict fail（planning 仅 IoU-only）；'
                         'H5 与 B0 的差异只能作为线索，不能写成 ESTABLISHED。</div>')
        elif d['fixture']:
            b.append('<div class="note"><b>收益判读：</b>fixture 链不进入真实收益结论。</div>')
        if d.get('formal_note'):
            b.append('<div class="note"><b>正式表对照（同一初态）：</b>%s；详见批次页“正式比较表 v5”。</div>'
                     % _esc(d['formal_note']))
    elif d.get('trigger_only'):
        b.append('<div class="state"><b>不适用</b>观察未触发，没有第二观察后的执行；这不是执行失败。</div>')
    else:
        b.append('<div class="state bad"><b>执行未运行 / missing execution</b>没有独立真值执行记录，不写成功。</div>')
    b.append('<details open><summary>逐初态数值回放（前 12 行）</summary>%s</details>' % _replay(d['execution']))
    if d['replay_images']:
        b.append('<div class="imgrow">' + ''.join(_fig(i['path'], '回放帧 · ' + i['label'], 'truthfig') for i in d['replay_images']) + '</div>')
    else:
        b.append('<div class="small muted" style="margin-top:6px">本运行未保存执行回放帧；上图/上表是真值几何与数值，不是视频回放。</div>')
    return '<section class="card" id="s5"><h2><span class="num">5</span>执行与揭晓 · 独立真值与对照回放</h2>%s</section>' % ''.join(b)


def _audit(d):
    cs = d['candidates']
    rows = [('fixture', '是（FIXTURE，不计真实成绩）' if d['fixture'] else '否'),
            ('mode', d.get('mode_note') or d.get('mode') or '—'),
            ('strict', '无候选（不适用）' if not cs else
             ('通过' if any(c.get('strict_pass') is True for c in cs) else '失败 / 未运行（见画面 2）')),
            ('planning eligibility', '无候选（不适用）' if not cs else
             ('至少 1 个 eligible' if any(c.get('planning_eligible') is True for c in cs)
              else '无 eligible / not evaluated')),
            ('土壤模式', 'rigid（未使用月壤模型）' if (d.get('summary') or {}).get('soil_mode') == 'rigid'
             else ((d.get('summary') or {}).get('soil_mode') or '未记录')),
            ('模拟时间', 'Σ %s s（%d 条记录）' % (_f(d['sim_total'], 2), d['sim_n']) if d['sim_n'] else '未记录'),
            ('计算时间 wall', 'Σ %s s（%d 条）' % (_f(d['wall_total'], 2), d['wall_n']) if d['wall_n']
             else '这些记录没有 wall_s；不编造'),
            ('观察可用', '是' if d['observation']['usable'] else '否：' + d['observation']['reason'])]
    return ('<section class="card span2" id="s6"><h2>资格 / 土壤 / 计时 / 声明</h2><dl class="kv">%s</dl>'
            '<div class="note">月壤是半经验近似：Bekker 压实阻力 + 等效库仑牵引；整机仍是刚性接触，几何下陷未实现。'
            '页面不把公式测试当整机测试。</div></section>'
            % ''.join('<dt>%s</dt><dd>%s</dd>' % (_esc(k), _esc(v)) for k, v in rows))


def _run_page(d, cases):
    labels = {'cached': 'cache replay（不新建）', 'local_fixture': 'local fixture（不联网）',
              'batch': 'batch manifest（只读）', 'batch_new': 'new batch run（只读）',
              'legacy': 'legacy run（只读）'}
    ml = labels.get(d['mode'], d['mode'])
    b = []
    if d.get('superseded'):
        b.append('<div class="state bad"><b>SUPERSEDED · 不用于正式表</b>'
                 '该运行使用旧初态（yaw=0.03），未与 six_R01_v5 的 0.05/0.05 统一初态配对；'
                 '3/3 结果保留作对照，不写成当前正式结果。</div>')
    if d['fixture']:
        b.append('<div class="fixture">FIXTURE — 非真实 Lux3D 生成候选；本页只把它当接口/格式验证，不进入真实收益结论。</div>')
    b.append('<div class="runbar"><h2>%s</h2>%s%s%s</div>'
             % (_esc(d['label']), _badge(ml, 'gold'), _badge('fixture', 'warn') if d['fixture'] else '',
                _badge('dev', 'blue') if d['dev'] else ''))
    b.append(_states(d['states']))
    b.append('<div class="screens">%s%s%s%s%s%s</div>'
             % (_obs_section(d), _imagine(d), _reh_section(d), _decision(d), _exec(d), _audit(d)))
    return _page(d['label'], ''.join(b), _sidebar(d, cases, ml))


def _batch_run_rows(d):
    out = []
    for r in d.get('runs') or []:
        rd = _resolve(r['dir'])
        sm = _json(rd / 'summary.json', {}) or {}
        chosen = sm.get('chosen')
        if not chosen:
            h5 = next((m for m in sm.get('methods', []) if m.get('method') == 'H5_lux3d'), {})
            chosen = h5.get('selected_action')
        h5n = b0n = None
        if sm.get('chosen_truth_success'):
            h5n = sm.get('chosen_truth_success')
        if sm.get('blind_truth_success'):
            b0n = sm.get('blind_truth_success')
        h5m = next((m for m in sm.get('methods', []) if m.get('method') == 'H5_lux3d'), {})
        if h5m:
            if h5m.get('no_candidate'):
                chosen = 'A0 / no candidate'
                h5n = '0/0 (no candidate)'
            else:
                h5n = '%s/%s' % (h5m.get('success'), h5m.get('n_exec'))
            b0m = next((m for m in sm.get('methods', []) if m.get('method') == 'B0_blind'), {})
            b0n = '%s/%s' % (b0m.get('success'), b0m.get('n_exec')) if b0m else None
        look = _json(rd / 'look_loop.json', {}) if r.get('kind') == 'look' else {}
        note = ''
        if 'init003' in r.get('run', ''):
            note = 'SUPERSEDED: yaw=0.03, not paired'
        elif r.get('kind') == 'look':
            if look.get('outcome') == 'trigger_only':
                note = '观察未触发：' + str((look.get('trigger') or {}).get('reason') or '')
            else:
                note = str(look.get('outcome') or '')
        out.append({'run': r['run'], 'kind': r.get('kind'), 'case': r.get('case_id'),
                    'chosen': chosen, 'h5': h5n, 'b0': b0n, 'note': note,
                    'link': '/?run=' + quote(r['run']),
                    'truth': sm.get('truth_sha') or ((look.get('truth_assets') or {}).get('world_sha') if look else None),
                    'rule': (_json(rd / 'decision.json', {}) or {}).get('rule') if (rd / 'decision.json').exists() else None})
    return out


def _formal_card(d):
    formal = d.get('formal') or {}
    benefit = d.get('benefit') or {}
    cases = formal.get('cases') or []
    rows = formal.get('rows') or []
    if not cases:
        return ''
    by_case = {}
    for r in rows:
        by_case.setdefault(r.get('case'), []).append(r)

    def mcell(case, method):
        for r in by_case.get(case, []):
            if r.get('method') == method:
                if r.get('no_candidate'):
                    return 'no candidate'
                return '%s %s/%s（%s）' % (r.get('selected_action') or '—',
                                          r.get('success'), r.get('n_exec'),
                                          _f(r.get('mean_cost'), 3))
        return '—'

    out = []
    for c in cases:
        case = c.get('case')
        cand = c.get('candidate') or '—'
        pl = c.get('candidate_planning_eligible')
        plb = ('IoU-only' if pl is True else 'ineligible' if pl is False else '—')
        st = c.get('candidate_strict_pass')
        stb = 'pass' if st is True else 'fail' if st is False else '—'
        if case == 'R01':
            concl = (benefit.get('R01') or {}).get('conclusion') or 'H5 2/3 低于 B3/U/宽度规则 3/3；无收益'
        elif case == 'R03':
            concl = (benefit.get('R03') or {}).get('conclusion') or 'H5 与盲走同分；无收益'
        elif case in ('R02', 'R04'):
            concl = (benefit.get('R02_R04') or {}).get('conclusion') or '所有非放弃动作 0/3；能力边界'
        else:
            concl = '—'
        out.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                   '<td class="small">%s</td></tr>'
                   % (_esc(case), _esc(cand), _esc(stb), _esc(plb), _esc(mcell(case, 'H5_lux3d')),
                      _esc(mcell(case, 'B0_blind')), _esc(mcell(case, 'B3_mirror')),
                      _esc(mcell(case, 'U_truth')), _esc(concl)))
    b = ['<section class="card" id="formal"><h2>正式比较表 v5 · 统一初态 0.05/0.05</h2>'
         '<div class="stat"><span>benefit <b class="bad">%s</b></span>'
         '<span>initial state <b>0.05 / 0.05</b></span>'
         '<span>state match <b>%s</b></span>'
         '<span>formal table <b class="mono">%s</b></span></div>'
         % (_esc(benefit.get('benefit_status') or 'NOT_ESTABLISHED'),
            _f(((_json(_resolve(d['dir']) / 'evaluation' / 'state_alignment_R01.json', {}) or {}).get('all_match'))),
            _esc('evaluation/formal_table_v5.json'))]
    b.append('<table><tr><th>case</th><th>候选</th><th>strict</th><th>planning</th><th>H5</th>'
             '<th>B0</th><th>B3_mirror</th><th>U_truth</th><th>结论</th></tr>%s</table>' % ''.join(out))
    b.append('<div class="note"><b>初态更正：</b>旧 <span class="mono">H5_R01_face12k_init003</span> 在 yaw=0.03 下 L2 3/3，'
             '已标 SUPERSEDED，不用于正式表；正式表用 0.05/0.05 配对，H5 L2 <b>2/3</b>（seed0 30.02 s timeout），'
             'B0 R1 0/3。B3_mirror / U_truth / 宽度规则均 S1 3/3（mean 6.593）。'
             'H5 没有优于 B3/U/宽度规则，benefit=NOT_ESTABLISHED。</div></section>')
    return ''.join(b)


def _batch_page(d, cases):
    m = d['manifest']
    s = _select(cases, d['run'])
    s += ('<div class="card"><h2>批次入口</h2><dl class="kv"><dt>batch</dt><dd class="mono">%s</dd>'
          '<dt>manifest</dt><dd class="mono">%s</dd><dt>目录</dt><dd class="mono">%s</dd></dl>'
          '<div class="small muted" style="margin-top:7px">%s</div></div>'
          % (_esc(d['batch_id']), _esc(d['manifest_path']), _esc(d['dir']), _esc(d['mode_note'])))
    s += ('<div class="card"><h2>本页怎么读</h2><div class="small muted">画面 1/2 是本批已落盘的观测与候选；'
          '画面 3/4/5 明确区分<b>未运行</b>与<b>真值扫描</b>。没有 candidate decision 时，不把 case 扫描写成 H5 成绩。</div></div>')
    b = ['<div class="runbar"><h2>%s</h2>%s</div>' % (_esc(d['label']), _badge('批次入口', 'gold'))]
    b.append('<div class="stat"><span>batch <b class="mono">%s</b></span>'
             '<span>候选 <b>%d</b>（清理 %d / 配准完成 %d / strict %d / planning %d）</span>'
             '<span>planning eligible <b>%d</b> · IoU-only <b>%d</b></span>'
             '<span>观测可用 <b>%d/%d</b></span><span>case 记录 <b>%d</b></span>'
             '<span>正式运行 <b>%d</b></span></div>'
             % (_esc(d['batch_id']), len(d['candidates']), d['n_clean'], d['n_align_done'],
                d['n_strict'], d['n_planning'], d['n_planning'],
                sum(1 for c in d['candidates'] if c.get('planning_status') == 'IoU-only'),
                d['n_obs_ok'], len(d['observations']), len(d['cases']), len(d['runs'])))
    b.append('<div class="small muted">manifest：<span class="mono">%s</span>；work_packages：%s</div>'
             % (_esc(d['manifest_path']), _esc('、'.join('%s=%s' % (k, (v or {}).get('status'))
                                                        for k, v in (m.get('work_packages') or {}).items()))))
    b.append(_states(d['states']))
    b.append(_formal_card(d))
    body = []
    for o in d['observations']:
        body.append('<div class="card" style="margin:10px 0 0;background:#100e15"><h2 style="color:#cfc5b8">%s %s</h2>'
                    % (_esc(o['id']), _badge('可用', 'ok') if o['usable'] else _badge('不可用', 'bad')))
        if o['images']:
            body.append('<div class="imgrow">' + ''.join(_fig(i['path'], '%s · %s' % (o['id'], i['label']), 'obsfig') for i in o['images']) + '</div>')
        else:
            body.append('<div class="state bad"><b>observation unusable</b>%s</div>' % _esc(o['reason']))
        if o['visible']:
            v = o['visible']
            body.append('<div class="small muted">可见 px %s；x_front %s m；W_vis %s m；H_vis %s m%s</div>'
                        % (_f(v.get('n_pixels')), _f(v.get('x_front'), 4), _f(v.get('W_vis'), 4), _f(v.get('H_vis'), 4),
                           ('；偏航 %s°' % _f(o.get('azimuth_deg'), 1)) if o.get('azimuth_deg') is not None else ''))
        if o['reason']:
            body.append('<div class="small warn" style="margin-top:4px">%s</div>' % _esc(o['reason']))
        body.append('</div>')
    body.append('<div class="note"><b>深度用途：</b>分割可见面并得到 x_front/W_vis/H_vis；az25/az45 是不同相对观察方向的诊断，'
                '不是原始 R01 单视角的重复采样。R01_base 只有 manifest/birth_state，显式标不可用。</div>')
    sec1 = '<section class="card" id="s1"><h2><span class="num">1</span>看见 · 本批观测与方向</h2>%s</section>' % ''.join(body)

    b2 = ['<div class="stat"><span>候选 <b>%d</b></span><span>清理通过 <b>%d</b></span>'
          '<span>配准完成 <b>%d</b> / align pass <b>%d</b></span><span>strict <b>%d</b></span>'
          '<span>planning eligible <b>%d</b>（IoU-only）</span><span>ineligible <b>%d</b></span></div>'
          % (len(d['candidates']), d['n_clean'], d['n_align_done'], d['n_align'], d['n_strict'],
             d['n_planning'], d['n_ineligible'])]
    if d['candidates']:
        rows = []
        for c in d['candidates']:
            pl = c.get('planning_eligible')
            pl_b = (_badge('IoU-only', 'warn') if pl is True else
                    _badge('ineligible', 'bad') if pl is False else _badge('not evaluated', 'warn'))
            rows.append('<tr><td>%s</td><td>%s</td><td class="mono">%s</td><td>%s</td><td>%s</td>'
                        '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td>%s</td><td>%s</td></tr>'
                        % (_esc(c['id']), _esc(c.get('task_id')), _esc(_short(c.get('world_sha') or c.get('clean_sha'), 14)),
                           _esc(c.get('clean_verdict')), _esc(c.get('alignment_status')),
                           _f(c.get('iou'), 4), _f(c.get('p95_mm'), 2), _f(c.get('freespace'), 4),
                           _badge('strict fail', 'bad') if c.get('strict_pass') is False else _badge('strict not run', 'warn'),
                           pl_b + ((' ' + _badge('part cap', 'warn')) if c.get('hit_part_cap') else '')))
        b2.append('<table><tr><th>候选</th><th>task</th><th>SHA</th><th>清理</th><th>配准</th><th>IoU</th><th>P95 mm</th>'
                  '<th>freespace</th><th>strict</th><th>planning</th></tr>%s</table>' % ''.join(rows))
        for c in d['candidates']:
            if c['views']:
                b2.append('<div class="imgrow">' + ''.join(_fig(v['path'], '%s · %s' % (c['id'], v['label']), 'candfig') for v in c['views']) + '</div>')
        b2.append('<div class="note"><b>有效候选数：</b>清理 %d / 配准完成 %d / align pass %d / strict %d / '
                  'planning eligible %d（其中 IoU-only 1）/ ineligible %d。'
                  'strict 与 planning 分列：C_R01_face12k 只过 IoU，strict 仍失败。</div>'
                  % (d['n_clean'], d['n_align_done'], d['n_align'], d['n_strict'], d['n_planning'], d['n_ineligible']))
        b2.append('<div class="state bad"><b>strict 0/3；planning 1/3（IoU-only）</b>'
                  'C_R01_face12k：IoU 0.8622、P95 11.0 mm > 9.957、freespace 0.5106、hit_part_cap=true；'
                  '另外 2 个 ineligible。planning 通过不等于 strict 通过，也不等于收益成立。</div>')
    else:
        b2.append('<div class="state bad"><b>no candidate</b>批次目录尚未出现清理候选。</div>')
    sec2 = '<section class="card" id="s2"><h2><span class="num">2</span>想象 · 本批候选与有效候选数</h2>%s</section>' % ''.join(b2)

    run_rows = _batch_run_rows(d)
    if run_rows:
        rr = ''.join('<tr><td><a href="%s">%s</a></td><td>%s</td><td>%s</td><td>%s</td></tr>'
                     % (r['link'], _esc(r['run']), _esc(r['kind']), _esc(r['chosen'] or '—'),
                        _esc(r['note'] or '已落盘')) for r in run_rows)
        sec3 = ('<section class="card" id="s3"><h2><span class="num">3</span>试走 · 候选×动作预演</h2>'
                '<div class="state ok"><b>本批已有正式运行</b>%d 个；预演矩阵与失败阶段在各运行页的“试走”画面，'
                '不在批次页用假动画代替。</div>'
                '<table><tr><th>运行</th><th>类型</th><th>H5 选择</th><th>状态</th></tr>%s</table></section>'
                % (len(run_rows), rr))
        rr2 = ''.join('<tr><td><a href="%s">%s</a></td><td>%s</td><td>%s</td></tr>'
                      % (r['link'], _esc(r['run']), _esc(r['chosen'] or '—'), _esc(r['rule'] or '见运行页'))
                      for r in run_rows)
        sec4 = ('<section class="card" id="s4"><h2><span class="num">4</span>决定 · 选了什么、为什么</h2>'
                '<div class="state ok"><b>决定已落盘</b>批次页只做索引；冻结理由、候选约束与 changed-by 在运行页。</div>'
                '<table><tr><th>运行</th><th>H5 选择</th><th>规则</th></tr>%s</table></section>' % rr2)
    else:
        sec3 = ('<section class="card" id="s3"><h2><span class="num">3</span>试走 · 候选×动作预演</h2>'
                '<div class="state bad"><b>not run</b>本批没有 evaluation 的 rehearsal/records；不展示假动画。</div></section>')
        sec4 = ('<section class="card" id="s4"><h2><span class="num">4</span>决定 · 选了什么、为什么</h2>'
                '<div class="state bad"><b>missing decision</b>本批没有 decision 产物；不补造“成功”。</div></section>')

    rows = []
    for c in d['cases']:
        detail = '；'.join('%s %d/%d' % (a['action'], a['success'], a['n']) for a in c['actions'] if a['n'])
        passing = c['flags'].get('passing_actions') or []
        rows.append('<tr><td>%s</td><td class="mono">%s</td><td class="num">%s</td><td>%s</td><td>%s</td></tr>'
                    % (_esc(c['id']), _esc(_short(c['truth_sha'], 14)), _esc(c['coacd_parts']), _esc(detail or '—'),
                       _esc('/'.join(passing) if passing else '无（A0 只是 abort）')))
    if run_rows:
        er = ''.join('<tr><td><a href="%s">%s</a></td><td>%s</td><td>%s</td><td>%s</td><td class="mono">%s</td></tr>'
                     % (r['link'], _esc(r['run']), _esc(r['kind']), _esc(r['h5'] or '—'),
                        _esc(r['b0'] or '—'), _esc(_short(r['truth'], 14)))
                     for r in run_rows)
        sec5 = ('<section class="card" id="s5"><h2><span class="num">5</span>执行与揭晓 · 本批正式运行 + 真值扫描</h2>'
                '<div class="state ok"><b>已有候选闭环执行</b>下表是本批运行；H5 与 B0 的差异必须结合候选 strict/eligibility 读，'
                '不单独升级为收益。</div>'
                '<table><tr><th>运行</th><th>类型</th><th>H5 成功</th><th>B0 成功</th><th>truth SHA</th></tr>%s</table>'
                % er)
    else:
        sec5 = ('<section class="card" id="s5"><h2><span class="num">5</span>执行与揭晓 · 真值扫描（非候选闭环）</h2>'
                '<div class="state bad"><b>候选执行未运行</b>本批没有 evaluation/<run>/execution；下表是真值动作扫描，'
                '不是候选闭环执行，不写成 H5 成绩。</div>')
    if rows:
        sec5 += ('<table><tr><th>case</th><th>truth SHA</th><th>CoACD</th><th>真值动作扫描（成功/初态）</th>'
                 '<th>可通行动作</th></tr>%s</table>' % ''.join(rows))
    sec5 += ('<div class="note">这些是独立真值上的动作扫描，用于找边界和诊断；不是“候选预演后选择并执行”的正式结果。'
             'R02/R04 全部非 A0 失败是真实能力边界。</div></section>')

    soil = d['soil']
    sr = []
    for r in soil['rows']:
        s = r['summary']
        extra = ''
        if r['key'] == 'a':
            raw = r.get('raw') or {}
            cal = [x.get('rel_err') for x in (raw.get('calibration') or []) if x.get('rel_err') is not None]
            val = [x.get('rel_err') for x in (raw.get('validation') or []) if x.get('rel_err') is not None]
            extra = ('calibration %s；validation %s' % (
                ('%.2f%%' % (100 * max(cal))) if cal else '—',
                ('%.2f–%.2f%%' % (100 * min(val), 100 * max(val))) if val else '—'))
        elif r['key'] == 'b':
            extra = 'rigid x %s / soil x %s；wall %s / %s s' % (_f(s.get('rigid_final_x_mean'), 3), _f(s.get('soil_final_x_mean'), 3),
                                                               _f(s.get('rigid_wall_s_mean'), 3), _f(s.get('soil_wall_s_mean'), 3))
        elif r['key'] == 'c':
            raw = r.get('raw') or {}
            extra = '; '.join('%g° %s %s' % (x.get('slope_deg'), 'soil' if x.get('soil') else 'rigid',
                                             x.get('reason')) for x in (raw.get('rows') or []))
        elif r['key'] == 'd':
            raw = r.get('raw') or {}
            extra = '; '.join('H=%s → p95 %s N' % (_f(x.get('H'), 2), _f(x.get('ft_p95'), 4))
                              for x in (raw.get('rows') or []))
        elif r['key'] == 'e':
            raw = r.get('raw') or {}
            extra = ('%s episodes；anomaly %s；max final_x %s m；max tilt %s°' % (
                raw.get('n_episodes'), raw.get('n_anomaly'),
                _f(raw.get('max_final_x_m'), 3), _f(raw.get('max_tilt_deg'), 2)))
        elif r['key'] == 'f':
            extra = 'wall ratio soil/rigid %s' % _f(s.get('wall_time_ratio_soil_over_rigid'), 3)
        elif r['key'] == 'g':
            extra = 'geometry_sinkage_implemented=%s；formula max_sink=%s m；measured penetration=%s m' % (
                r.get('geometry_sinkage_implemented'), _f(r.get('formula_max_sink_m'), 4), _f(r.get('measured_wheel_penetration_m'), 4))
        sr.append('<tr><td>%s</td><td>%s</td><td class="small">%s</td></tr>' % (_esc(r['stage']), _esc(extra or '—'), _esc(r['note'])))
    sec6 = ('<section class="card span2" id="s6"><h2>土壤 / 预检 / 计时</h2>'
            '<div class="stat"><span>soil_version <b>%s</b></span><span>stability <b>%d/1000</b></span>'
            '<span>stage G <b>%s</b></span></div>'
            % (_esc((soil['acceptance'] or {}).get('soil_version')), soil['stability'],
               _esc((soil['stage_g'] or {}).get('verdict') or '—')))
    sec6 += '<table><tr><th>阶段</th><th>结果</th><th>边界说明</th></tr>%s</table>' % ''.join(sr)
    sec6 += ('<div class="note">月壤为半经验近似：Bekker 压实阻力 + 等效库仑牵引；整机仍刚性接触，<b>几何下陷未实现</b>。'
             '单轮标定不能直接证明整机几何下陷。</div>')
    pf = d['preflight']
    sec6 += '<div class="small muted" style="margin-top:8px">preflight：%s</div></section>' % _esc('%d/%d 通过' % (pf['pass'], len(pf['checks'])))
    b.append('<div class="screens">%s%s%s%s%s%s</div>' % (sec1, sec2, sec3, sec4, sec5, sec6))
    return _page(d['batch_id'], ''.join(b), s)


def render_page(name=None):
    reg = _load_registry()
    cases = list_cases()
    if not cases:
        return _page('没有运行', '<section class="card"><h2>没有可读运行</h2>检查 page_registry.json / manifest。</section>')
    if not name:
        name = reg.get('default') or cases[0]['run']
    try:
        d = load_run(name)
    except FileNotFoundError:
        return _page('未找到运行', '<section class="card"><h2>未找到运行</h2><p class="muted">%s</p><p><a href="/">默认页</a></p></section>' % _esc(name))
    except Exception as e:
        return _page('加载失败', '<section class="card"><h2>加载失败</h2><div class="state bad"><b>%s</b>%s</div><p><a href="/">默认页</a></p></section>'
                     % (_esc(type(e).__name__), _esc(str(e))))
    return _batch_page(d, cases) if d['kind'] == 'batch' else _run_page(d, cases)


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        try:
            if p in ('/', '/index.html'):
                return self._send(200, render_page((q.get('run') or [None])[0]), 'text/html; charset=utf-8')
            if p == '/api/cases':
                return self._send(200, json.dumps({'cases': list_cases()}, ensure_ascii=False))
            if p == '/api/run':
                return self._send(200, json.dumps(load_run((q.get('name') or q.get('run') or [''])[0]), ensure_ascii=False))
            if p == '/img':
                rel = (q.get('p') or [''])[0]
                f = _resolve(rel)
                if not f.is_file():
                    return self._send(404, json.dumps({'error': 'missing image', 'path': rel}, ensure_ascii=False))
                ctype = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                         '.webp': 'image/webp', '.gif': 'image/gif'}.get(f.suffix.lower())
                if not ctype:
                    return self._send(403, json.dumps({'error': 'unsupported image type'}, ensure_ascii=False))
                return self._send(200, f.read_bytes(), ctype)
            if p == '/healthz':
                return self._send(200, '{"ok":true}')
            return self._send(404, json.dumps({'error': 'not found'}, ensure_ascii=False))
        except ValueError as e:
            return self._send(403, json.dumps({'error': str(e)}, ensure_ascii=False))
        except Exception as e:
            return self._send(500, json.dumps({'error': '%s: %s' % (type(e).__name__, e)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description='看不见的那一面 · 只读页面')
    ap.add_argument('--port', type=int, default=8091)
    ap.add_argument('--host', default='127.0.0.1')
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print('看不见的那一面：http://%s:%d' % (a.host, a.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
