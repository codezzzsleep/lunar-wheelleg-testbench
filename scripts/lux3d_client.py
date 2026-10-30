"""
Lux3D 最小客户端（只做本项目需要的四件事，不建通用平台）。

  export AHOLO_API_KEY=...            # 只从环境注入，不写进仓库
  .venv/bin/python scripts/lux3d_client.py --submit --brief P1
  .venv/bin/python scripts/lux3d_client.py --status <taskId>
  .venv/bin/python scripts/lux3d_client.py --ledger

能力：
  1. 从简报创建文生 3D 任务（也支持图生 3D，需给 --img URL）
  2. 保存 taskId 并轮询到终态，处理超时/失败/恢复查询
  3. 下载原始结果到持久目录并解包
  4. 记录输入输出哈希、任务来源、耗时、模型版本、实际扣费

幂等：同一简报（prompt 哈希）已有成功任务时默认复用，--force 才重复付费提交。
所有消费写进 runs/lux3d/ledger.jsonl，一次一行的追加式账本。
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = 'https://api.aholo3d.cn'
STORE = ROOT / 'assets/generated'
LEDGER = ROOT / 'runs/lux3d/ledger.jsonl'
BUDGET_CREDITS = 100          # 本轮上限（任务书第三节）
CREDITS_PER_TASK = 13         # 实测 g1-turbo 文生 3D 的扣费


def _key():
    k = os.environ.get('AHOLO_API_KEY', '').strip()
    if not k:
        raise SystemExit('缺少 AHOLO_API_KEY：请用环境变量注入，不要写进仓库。')
    return k


def _req(method, path, body=None, timeout=90):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', _key())
    if data:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {'f': None, 'c': str(e.code), 'm': e.read().decode()[:400], 'd': None}


def submit_text_to_3d(prompt, version='G1-Turbo', face_count=30000,
                      output_format=None, style='photorealistic'):
    body = {'prompt': prompt, 'version': version, 'faceCount': face_count,
            'style': style, 'aiPredictSize': True}
    if output_format:
        body['outputFormat'] = output_format
    r = _req('POST', '/lux3d/v1/generate/text-to-3d/task/create', body)
    if r.get('c') != '0':
        raise RuntimeError(f'创建任务失败: {r.get("m") or r}')
    # 该接口的 d 直接是 taskId（整数），不是对象
    d = r['d']
    return d if isinstance(d, dict) else {'taskId': int(d)}


def submit_img_to_3d(img_url, version='G1-Turbo', face_count=30000):
    body = {'img': img_url, 'version': version, 'faceCount': face_count,
            'aiPredictSize': True}
    r = _req('POST', '/lux3d/v1/generate/img-to-3d/task/create', body)
    if r.get('c') != '0':
        raise RuntimeError(f'创建任务失败: {r.get("m") or r}')
    d = r['d']
    return d if isinstance(d, dict) else {'taskId': int(d)}


def submit_img_to_3d_multi(img_urls, version='G1-Turbo', face_count=30000):
    """真实两图/多图路径：发送有序 imgs 列表，**不同时**发送 img。

    V7 要求：显式模型版本、顺序参与请求身份、单图路径保持兼容。
    """
    urls = [str(u) for u in img_urls]
    if len(urls) < 2:
        raise SystemExit('submit_img_to_3d_multi 需要至少两张图；单图请用 submit_img_to_3d')
    body = {'imgs': urls, 'version': version, 'faceCount': face_count,
            'aiPredictSize': True}
    if 'img' in body:
        raise SystemExit('多图请求不允许同时携带 img')
    r = _req('POST', '/lux3d/v1/generate/img-to-3d/task/create', body)
    if r.get('c') != '0':
        raise RuntimeError(f'创建任务失败: {r.get("m") or r}')
    d = r['d']
    return d if isinstance(d, dict) else {'taskId': int(d)}


def request_identity(mode, items, version, face_count=30000, extra=None):
    """请求身份 = 模式 + 全部图片字节/顺序 + 实际参数。换序或换图必须变身份。"""
    import hashlib as _h
    parts = [mode, str(version), str(int(face_count))]
    for it in items:
        p = pathlib.Path(it)
        parts.append(_h.sha256(p.read_bytes()).hexdigest() if p.exists() else str(it))
    if extra:
        parts.append(json.dumps(extra, sort_keys=True))
    return _h.sha256('\n'.join(parts).encode()).hexdigest()


def get_task(task_id):
    r = _req('GET', f'/lux3d/v1/generate/task/get?taskid={task_id}')
    if r.get('c') != '0':
        raise RuntimeError(f'查询失败: {r.get("m") or r}')
    return r['d']


def list_tasks(page=1, page_size=20):
    r = _req('GET', f'/lux3d/v1/generate/task/list?page={page}&pageSize={page_size}')
    if r.get('c') != '0':
        raise RuntimeError(f'列表失败: {r.get("m") or r}')
    return r['d']


def spend_so_far():
    if not LEDGER.exists():
        return 0
    total = 0
    for line in LEDGER.read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get('event') == 'submitted':
            total += int(rec.get('estimated_credits') or 0)
    return total


def append_ledger(rec):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    rec = {'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), **rec}
    with LEDGER.open('a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


def find_cached(prompt_hash):
    if not LEDGER.exists():
        return None
    for line in LEDGER.read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if (rec.get('event') == 'completed'
                and rec.get('prompt_hash') == prompt_hash
                and rec.get('local_dir')):
            return rec
    return None


def poll(task_id, timeout_s=1800, interval=10):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout_s:
        d = get_task(task_id)
        st = d.get('status')
        if st != last:
            print(f'  [{int(time.time()-t0):4d}s] status={st}', flush=True)
            last = st
        if st in (3, 'success', 'SUCCESS'):
            return d
        if st in (4, 'failed', 'FAILED', -1):
            return d
        time.sleep(interval)
    raise TimeoutError(f'任务 {task_id} 超时（{timeout_s}s）')


def download(urls, dest):
    dest = pathlib.Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, u in enumerate(urls):
        name = pathlib.Path(u.split('?')[0]).name or f'file_{i}'
        out = dest / name
        with urllib.request.urlopen(u, timeout=300) as r, out.open('wb') as f:
            f.write(r.read())
        saved.append(out)
        print(f'  saved {out.name} ({out.stat().st_size/1e6:.2f} MB)')
    return saved


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--submit', action='store_true')
    ap.add_argument('--brief', default=None, help='简报 id，见 briefs/lux3d_briefs.json')
    ap.add_argument('--prompt', default=None)
    ap.add_argument('--version', default='G1-Turbo')
    ap.add_argument('--status', default=None)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--ledger', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--budget', type=int, default=BUDGET_CREDITS)
    a = ap.parse_args()

    if a.ledger:
        print(f'已记账提交额: {spend_so_far()} / {BUDGET_CREDITS} 积分')
        if LEDGER.exists():
            for line in LEDGER.read_text().splitlines()[-10:]:
                print(' ', line[:200])
        return 0

    if a.list:
        d = list_tasks()
        for it in d.get('items', [])[:15]:
            print(f"  {it['taskId']}  {it.get('taskType')}  v={it.get('version')} "
                  f"credits={it.get('consumedCredits')} status={it.get('status')}")
        return 0

    if a.status:
        print(json.dumps(get_task(a.status), indent=2, ensure_ascii=False)[:2000])
        return 0

    if not a.submit:
        raise SystemExit('需要 --submit / --status / --list / --ledger')

    prompt = a.prompt
    brief_id = a.brief
    if brief_id:
        briefs = json.loads((ROOT / 'briefs/lux3d_briefs.json').read_text())
        if brief_id not in briefs:
            raise SystemExit(f'未知简报 {brief_id}，可用: {list(briefs)}')
        prompt = briefs[brief_id]['prompt']
    if not prompt:
        raise SystemExit('需要 --prompt 或 --brief')

    ph = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    cached = None if a.force else find_cached(ph)
    if cached:
        print(f'复用缓存：简报 {brief_id} 已有成功任务 {cached.get("task_id")} '
              f'-> {cached.get("local_dir")}（未重复付费）')
        return 0

    spent = spend_so_far()
    if spent + CREDITS_PER_TASK > a.budget:
        raise SystemExit(f'预算不足：已提交 {spent}，本次预计 {CREDITS_PER_TASK}，'
                         f'上限 {a.budget}。')

    print(f'提交任务：brief={brief_id} version={a.version} 预计 {CREDITS_PER_TASK} 积分')
    t_submit = time.time()
    d = submit_text_to_3d(prompt, version=a.version)
    task_id = d.get('taskId') or d.get('taskid')
    append_ledger({'event': 'submitted', 'brief': brief_id, 'task_id': task_id,
                   'prompt_hash': ph, 'prompt': prompt, 'version': a.version,
                   'estimated_credits': CREDITS_PER_TASK})
    print(f'  taskId={task_id}')

    final = poll(task_id)
    elapsed = round(time.time() - t_submit, 1)
    status = final.get('status')
    consumed = final.get('consumedCredits')
    print(f'  终态 status={status} 实际扣费={consumed} 耗时={elapsed}s')

    # 该接口的终态结构是 {"outputs": [{"content": "<url>"}, ...]}
    urls = []
    for o in (final.get('outputs') or []):
        if isinstance(o, dict) and o.get('content'):
            urls.append(o['content'])
    if not urls:
        for k in ('resultUrls', 'urls', 'outputFiles'):
            v = final.get(k)
            if isinstance(v, list) and v:
                urls = [x if isinstance(x, str) else x.get('url') for x in v]
                break

    dest = STORE / (brief_id or f'task_{task_id}')
    if urls:
        files = download(urls, dest)
        for f in files:
            if f.suffix.lower() == '.zip':
                with zipfile.ZipFile(f) as z:
                    z.extractall(dest / 'unpacked')
                print(f'  解包 {f.name} -> unpacked/')
    else:
        files = []
        print('  警告：终态里没有找到结果 URL，请用 --status 检查')

    hashes = {f.name: sha256(f) for f in files}
    append_ledger({'event': 'completed', 'brief': brief_id, 'task_id': task_id,
                   'prompt_hash': ph, 'version': a.version, 'status': status,
                   'consumed_credits': consumed, 'seconds': elapsed,
                   'local_dir': str(dest.relative_to(ROOT)),
                   'files': hashes, 'raw': {k: final.get(k) for k in
                                            ('status', 'consumedCredits')}})
    print(f'  落盘 {dest.relative_to(ROOT)} 文件 {list(hashes)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
