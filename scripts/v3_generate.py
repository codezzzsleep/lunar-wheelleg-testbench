"""v3 生成：Lux3D 图生 3D 批量（并发、幂等、账本、断点恢复）。

复用 `imagine.py` 的官方上传/创建/查询/下载原语，不新造平台；本脚本只补三件事：
  1. **并发 create/poll**（API 等待可并行，本地重任务不并行）；
  2. **身份缓存**：identity = 有序图片 SHA + version + faceCount + repeat_idx，命中即复用；
  3. **真实过程记录**：上传/创建/轮询/下载每一步带时间戳写 ledger，作为"生成过程"证据。

规矩（SPEC §7）：
  · task_id 一拿到立刻落盘；超时先查询，记 uncertain，**不重复 create**；
  · 失败不自动重提；
  · 首个任务就是最终计划里的真实任务，不造测试任务；
  · 费用分列 estimated / consumed（接口不返回就写 unknown）。

  set -a; . /root/.aholo_env; set +a
  python scripts/v3_generate.py --tasks runs/v3/generation/tasks.json --submit --workers 4
  python scripts/v3_generate.py --tasks runs/v3/generation/tasks.json --resume
  python scripts/v3_generate.py --tasks runs/v3/generation/tasks.json --report
"""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import imagine as IM

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / 'runs/v3/generation'
CACHE = GEN / 'cache'
LEDGER = GEN / 'ledger.jsonl'
LOCK = GEN / '.ledger.lock'


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def identity_of(task):
    parts = [task['variant'], str(task['model'].get('version', 'G1-Turbo')),
             str(int(task['model'].get('face_count', 30000))),
             str(int(task.get('repeat_idx', 0))),
             sha256_file(task['image'])]
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def append(rec):
    GEN.mkdir(parents=True, exist_ok=True)
    rec = {'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), **rec}
    with open(LOCK, 'a+') as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        with LEDGER.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        fcntl.flock(lf, fcntl.LOCK_UN)
    return rec


def ledger_rows():
    if not LEDGER.is_file():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def cache_valid(ident):
    d = CACHE / ident
    meta = d / 'meta.json'
    glb = d / 'model.glb'
    if not (meta.is_file() and glb.is_file()):
        return None
    try:
        m = json.loads(meta.read_text())
    except Exception:
        return None
    if m.get('glb_sha256') != sha256_file(glb):
        return None
    return {'dir': str(d), 'glb': str(glb), 'meta': m}


def task_state(task, rows):
    ident = identity_of(task)
    hit = cache_valid(ident)
    if hit:
        return {'identity': ident, 'state': 'cached', **hit}
    recs = [r for r in rows if r.get('identity') == ident]
    last = recs[-1] if recs else None
    if last and last.get('task_id') and last.get('event') in ('created', 'downloaded'):
        return {'identity': ident, 'state': 'has_task', 'task_id': int(last['task_id']),
                'last': last}
    if last and last.get('event') == 'uncertain':
        return {'identity': ident, 'state': 'uncertain', 'task_id': last.get('task_id')}
    if last and last.get('event') in ('failed', 'invalid'):
        return {'identity': ident, 'state': 'failed', 'reason': last.get('note')}
    n_rej = sum(1 for r in recs if r.get('event') == 'rejected')
    if n_rej >= 12:
        return {'identity': ident, 'state': 'failed', 'reason': 'rejected_too_many_times'}
    return {'identity': ident, 'state': 'need_create'}


def download_outputs(urls, dest):
    dest = pathlib.Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, u in enumerate(urls):
        name = pathlib.Path(u.split('?')[0]).name or f'out_{i}'
        out = dest / name
        with urllib.request.urlopen(u, timeout=300) as r, out.open('wb') as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        saved.append(out)
    return saved


def fetch_result(tid, dest, meta):
    j = IM.get_task(int(tid))
    st = j.get('status')
    if st != 3:
        return None, st
    urls = [o['content'] for o in (j.get('outputs') or []) if o.get('content')]
    if not urls:
        return None, 'no_outputs'
    files = download_outputs(urls, dest)
    glb = next((f for f in files if f.suffix.lower() == '.glb'), None)
    if glb is None:
        zp = next((f for f in files if f.suffix.lower() == '.zip'), None)
        if zp is not None:
            glb = IM.extract_glb(zp, dest)
    if glb is None or glb.open('rb').read(4) != b'glTF':
        return None, 'not_glb'
    rec = dict(meta)
    rec['glb'] = str(glb.relative_to(ROOT))
    rec['glb_sha256'] = sha256_file(glb)
    rec['task_id'] = int(tid)
    rec['downloaded_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    (pathlib.Path(dest) / 'meta.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return {'glb': str(glb), 'dir': str(dest), 'meta': rec}, 'ok'


def run_task(task, rows):
    ident = identity_of(task)
    st = task_state(task, rows)
    if st['state'] in ('cached', 'failed'):
        return {**st, 'task_id': task.get('task_id')}
    d = CACHE / ident
    d.mkdir(parents=True, exist_ok=True)
    meta = {'id': task['id'], 'state_id': task.get('state_id'), 'variant': task.get('variant'),
            'repeat_idx': int(task.get('repeat_idx', 0)), 'identity': ident,
            'image': task['image'], 'image_sha256': sha256_file(task['image']),
            'model': task['model'], 'create_order': int(task.get('create_order', 0))}
    if st['state'] in ('has_task', 'uncertain') and st.get('task_id'):
        append({'event': 'resume_poll', 'identity': ident, 'task_id': st['task_id'],
                'id': task['id']})
        got, why = fetch_result(st['task_id'], d, meta)
        if got:
            append({'event': 'downloaded', 'identity': ident, 'task_id': st['task_id'],
                    'id': task['id'], 'glb_sha256': got['meta']['glb_sha256']})
            return {**got, 'state': 'downloaded', 'identity': ident}
        append({'event': 'poll', 'identity': ident, 'task_id': st['task_id'],
                'id': task['id'], 'status': why})
        return {'state': 'pending_task', 'identity': ident, 'task_id': st['task_id'],
                'status': why}
    # ---- 新建：先上传，再 create（唯一付费入口） ----
    t0 = time.time()
    try:
        img_url = IM.upload_image(task['image'])
    except Exception as e:  # noqa: BLE001
        append({'event': 'upload_failed', 'identity': ident, 'id': task['id'],
                'error': f'{type(e).__name__}: {e}'})
        return {'state': 'upload_failed', 'error': str(e)[:200]}
    append({'event': 'uploaded', 'identity': ident, 'id': task['id'],
            'image': task['image'], 'image_sha256': meta['image_sha256'],
            'url_sha256': hashlib.sha256(img_url.encode()).hexdigest(),
            'upload_seconds': round(time.time() - t0, 2)})
    tid = None
    last_err = None
    for attempt in range(4):
        try:
            tid = IM.submit_img_to_3d(img_url, task['model'])
            break
        except Exception as e:  # noqa: BLE001
            last_err = f'{type(e).__name__}: {e}'
            msg = str(e)
            # 明确的业务拒绝（并发上限等）：任务**没有**被受理，可以稍后重试
            if 'LIMIT' in msg or '并发' in msg or 'CONCURRENCY' in msg.upper():
                append({'event': 'rejected', 'identity': ident, 'id': task['id'],
                        'attempt': attempt, 'error': msg[:300]})
                time.sleep(12 + 8 * attempt)
                continue
            append({'event': 'uncertain', 'identity': ident, 'id': task['id'],
                    'error': last_err[:300], 'note': '可能已受理，不重提，先查询'})
            return {'state': 'uncertain', 'error': last_err[:200]}
    if tid is None:
        return {'state': 'rejected', 'error': last_err}
    append({'event': 'created', 'identity': ident, 'task_id': int(tid), 'id': task['id'],
            'variant': task.get('variant'), 'state_id': task.get('state_id'),
            'create_order': int(task.get('create_order', 0)),
            'estimated_credits': task.get('estimated_credits')})
    try:
        j = IM.poll(int(tid), timeout_s=int(task.get('timeout_s', 1800)))
        stt = j.get('status') if isinstance(j, dict) else None
    except Exception as e:  # noqa: BLE001
        append({'event': 'poll_error', 'identity': ident, 'task_id': int(tid),
                'id': task['id'], 'error': f'{type(e).__name__}: {e}'})
        return {'state': 'poll_error', 'task_id': int(tid)}
    if stt != 3:
        append({'event': 'failed', 'identity': ident, 'task_id': int(tid),
                'id': task['id'], 'status': stt})
        return {'state': 'failed_task', 'task_id': int(tid), 'status': stt}
    got, why = fetch_result(tid, d, meta)
    if not got:
        append({'event': 'invalid', 'identity': ident, 'task_id': int(tid),
                'id': task['id'], 'note': why})
        return {'state': 'invalid', 'task_id': int(tid), 'note': why}
    append({'event': 'downloaded', 'identity': ident, 'task_id': int(tid),
            'id': task['id'], 'glb_sha256': got['meta']['glb_sha256'],
            'total_seconds': round(time.time() - t0, 2),
            'consumed_credits': (j.get('consumedCredits') if isinstance(j, dict) else None)})
    return {**got, 'state': 'downloaded', 'identity': ident}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tasks', default='runs/v3/generation/tasks.json')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--submit', action='store_true')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    tasks = json.loads((ROOT / a.tasks).read_text())['tasks']
    if a.limit:
        tasks = tasks[:a.limit]
    rows = ledger_rows()
    if a.report:
        states = [task_state(t, rows) for t in tasks]
        summary = {}
        for s in states:
            summary[s['state']] = summary.get(s['state'], 0) + 1
        created = [r for r in rows if r.get('event') == 'created']
        downloaded = [r for r in rows if r.get('event') == 'downloaded']
        out = {'n_tasks': len(tasks), 'states': summary,
               'n_created': len({r['task_id'] for r in created}),
               'n_downloaded': len({r['task_id'] for r in downloaded}),
               'estimated_credits': sum(int(r.get('estimated_credits') or 0) for r in created),
               'consumed_credits': [r.get('consumed_credits') for r in downloaded
                                    if r.get('consumed_credits') is not None]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not (a.submit or a.resume):
        raise SystemExit('需要 --submit / --resume / --report')
    if os.environ.get('AHOLO_API_KEY') is None:
        raise SystemExit('缺少 AHOLO_API_KEY（只从环境注入）')
    # 只对需要创建的任务并发
    todo = []
    for t in tasks:
        st = task_state(t, rows)
        if st['state'] == 'cached':
            continue
        if a.resume and st['state'] in ('need_create', 'failed'):
            continue
        todo.append(t)
    todo.sort(key=lambda t: int(t.get('create_order', 0)))
    results = []
    lock = threading.Lock()
    idx = {'i': 0}

    def worker():
        while True:
            with lock:
                if idx['i'] >= len(todo):
                    return
                t = todo[idx['i']]; idx['i'] += 1
            try:
                r = run_task(t, ledger_rows())
            except Exception as e:  # noqa: BLE001
                r = {'state': 'error', 'error': f'{type(e).__name__}: {e}'}
            with lock:
                results.append({**r, 'id': t['id']})
                print(json.dumps({'id': t['id'], 'state': r.get('state'),
                                  'task_id': r.get('task_id')}, ensure_ascii=False),
                      flush=True)

    ths = [threading.Thread(target=worker) for _ in range(max(1, int(a.workers)))]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    summary = {}
    for r in results:
        summary[r.get('state')] = summary.get(r.get('state'), 0) + 1
    print(json.dumps({'n': len(results), 'states': summary}, ensure_ascii=False))


if __name__ == '__main__':
    main()
