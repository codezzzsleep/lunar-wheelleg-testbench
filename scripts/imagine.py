"""
Lux3D 图生 3D 客户端：计划 → 预算预留 → 上传 → 提交 → 轮询 → 下载 → 账本。

  .venv/bin/python scripts/imagine.py --plan plans/unseen_v1_generation.json --dry-run
  .venv/bin/python scripts/imagine.py --plan ... --submit  --budget configs/unseen_v1_budget.json
  .venv/bin/python scripts/imagine.py --plan ... --resume  --budget configs/unseen_v1_budget.json
  .venv/bin/python scripts/imagine.py --plan ... --cached-only

硬性规则（任务书第六节）：
  · 默认 dry-run：不联网、不上传、不提交，只打印计划与预算；
  · 预算与任务账本用**文件锁**，提交前原子预留"任务数 + 费用上界"；
  · pending/uncertain 一律按费用上界保留，只有明确未受理才释放；
  · task_id 一拿到立即落盘；超时先查询，不重新 create；
  · 缓存键 = 输入图字节 SHA + 变体 + 模型/区域/面数/输出参数 + repeat_idx；
    命中要求文件存在、可解析、SHA 一致；
  · 密钥只从 AHOLO_API_KEY 读取，不打印、不落盘。
"""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
API_BASE = os.environ.get('AHOLO_API_BASE', 'https://api.aholo3d.cn')

# 状态机
ST_PLANNED = 'planned'
ST_SUBMITTED = 'submitted'
ST_PENDING = 'pending'
ST_SUCCEEDED = 'succeeded'
ST_FAILED = 'failed'
ST_UNCERTAIN = 'uncertain'
ST_DOWNLOADED = 'downloaded'
ST_INVALID = 'invalid_asset'
HELD = {ST_SUBMITTED, ST_PENDING, ST_UNCERTAIN, ST_SUCCEEDED}


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _key():
    k = os.environ.get('AHOLO_API_KEY')
    if not k:
        raise SystemExit('缺少 AHOLO_API_KEY 环境变量：图生需在执行环境中设置（不会打印其值）')
    return k


class Lock:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = None

    def __enter__(self):
        self.fh = open(self.path, 'a+')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


class Ledger:
    """任务账本：每个 task 一行 JSON，追加写；预留与提交在同一把锁里完成。"""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_suffix('.lock')

    def all(self):
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def held_credits(self):
        return sum(float(r.get('estimate_upper') or 0) for r in self.all()
                   if r.get('status') in HELD)

    def held_tasks(self):
        return sum(1 for r in self.all() if r.get('status') in HELD)

    def append(self, rec):
        with self.lock_path():
            with open(self.path, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    def lock_path(self):
        return Lock(self.lock)

    def update(self, identity, **kw):
        with Lock(self.lock):
            rows = self.all()
            for r in rows:
                if r.get('identity') == identity:
                    r.update(kw)
            self.path.write_text('\n'.join(json.dumps(r, ensure_ascii=False)
                                           for r in rows) + '\n')

    def reserve(self, identity, credits_upper, budget):
        """
        原子预留：任务数 + 积分上界同时检查。成功返回 True。
        预留本身写一条 planned 记录（随后立即转 submitted）。
        """
        with Lock(self.lock):
            rows = self.all()
            held_c = sum(float(r.get('estimate_upper') or 0) for r in rows
                         if r.get('status') in HELD)
            held_n = sum(1 for r in rows if r.get('status') in HELD)
            if held_c + credits_upper > budget['hard_cap']:
                return False, f'积分将达 {held_c + credits_upper} > 上限 {budget["hard_cap"]}'
            if held_n + 1 > budget['max_create_tasks']:
                return False, f'任务数将达 {held_n + 1} > 上限 {budget["max_create_tasks"]}'
            if credits_upper > budget['per_task_cap']:
                return False, f'单任务 {credits_upper} > 上限 {budget["per_task_cap"]}'
            rows.append({'identity': identity, 'status': ST_PLANNED,
                         'estimate_upper': credits_upper, 'actual_charge': None,
                         'verified': 'unknown', 'ts': time.time()})
            self.path.write_text('\n'.join(json.dumps(r, ensure_ascii=False)
                                           for r in rows) + '\n')
            return True, 'reserved'


def request_identity(image_bytes, variant, model_cfg, repeat_idx):
    """缓存与去重身份：图像字节 + 变体 + 模型/区域/面数/输出参数 + 重复序号。"""
    payload = json.dumps({
        'img_sha': sha256_bytes(image_bytes), 'variant': variant,
        'model': model_cfg, 'repeat_idx': repeat_idx,
    }, sort_keys=True, ensure_ascii=False)
    return sha256_bytes(payload.encode())


def cache_path(cache_dir, identity):
    return pathlib.Path(cache_dir) / identity[:2] / identity


def cache_valid(cache_dir, identity):
    """命中要求：GLB 存在、可解析（文件头 glTF）、SHA 与记录一致。"""
    d = cache_path(cache_dir, identity)
    meta = d / 'meta.json'
    glb = d / 'model.glb'
    if not (meta.exists() and glb.exists()):
        return False
    try:
        m = json.loads(meta.read_text())
        head = glb.open('rb').read(4)
        if head != b'glTF':
            return False
        return sha256_file(glb) == m.get('glb_sha')
    except Exception:
        return False


def _http(method, path, body=None, timeout=90, headers=None):
    url = API_BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', _key())
    req.add_header('Content-Type', 'application/json')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code}: {e.read()[:200]!r}') from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw          # 图生 create 返回裸整数 taskId


def submit_img_to_3d(img_url, model_cfg):
    body = {'imageUrl': img_url,
            'version': model_cfg.get('version', 'G1-Turbo'),
            'faceCount': model_cfg.get('face_count', 30000)}
    r = _http('POST', '/lux3d/v1/generate/image-to-3d/task/create', body)
    tid = r if isinstance(r, int) else (r.get('data') or r.get('taskId'))
    return int(tid)


def get_task(task_id):
    return _http('GET', f'/lux3d/v1/generate/task/get?taskid={task_id}')


def poll(task_id, timeout_s=1800, interval=10):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        j = get_task(task_id)
        st = j.get('status') if isinstance(j, dict) else None
        if st == 3:
            return j
        if st in (4, -1, 2):
            return j
        time.sleep(interval)
    return {'status': 'timeout'}


def download_urls(urls, dest):
    dest = pathlib.Path(dest); dest.mkdir(parents=True, exist_ok=True)
    out = []
    for u in urls:
        with urllib.request.urlopen(u, timeout=180) as r:
            b = r.read()
        p = dest / ('model.glb' if u.lower().endswith(('.glb',)) else
                    pathlib.Path(u.split('?')[0]).name)
        p.write_bytes(b)
        out.append(p)
    return out


def plan_entries(plan):
    return plan['inputs']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--submit', action='store_true')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--cached-only', action='store_true')
    ap.add_argument('--budget', default='configs/unseen_v1_budget.json')
    ap.add_argument('--ledger', default='runs/unseen/generation/ledger.jsonl')
    ap.add_argument('--cache', default='runs/unseen/generation/cache')
    a = ap.parse_args()

    plan = json.loads(pathlib.Path(a.plan).read_text())
    budget = json.loads(pathlib.Path(a.budget).read_text()) if \
        pathlib.Path(a.budget).exists() else None
    led = Ledger(a.ledger)

    rows, need_submit = [], 0
    for item in plan_entries(plan):
        img = pathlib.Path(item['image'])
        if not img.exists():
            rows.append({'id': item['id'], 'state': 'missing_image', 'path': str(img)})
            continue
        b = img.read_bytes()
        ident = request_identity(b, item.get('variant', 'orig'), item['model'],
                                 item.get('repeat_idx', 0))
        hit = cache_valid(a.cache, ident)
        rec = next((r for r in led.all() if r.get('identity') == ident), None)
        st = rec.get('status') if rec else None
        if hit:
            state = 'cached'
        elif st in HELD:
            state = f'{st}_held'
        else:
            state = 'need_create'
            need_submit += 1
        rows.append({'id': item['id'], 'state': state, 'identity': ident[:16],
                     'task_id': (rec or {}).get('task_id'),
                     'img_sha': sha256_bytes(b)[:16], 'variant': item.get('variant', 'orig')})

    held_c = led.held_credits()
    est = need_submit * float(plan.get('credits_upper_per_task', 20))
    print(json.dumps({
        'mode': ('dry-run' if a.dry_run or not (a.submit or a.resume or a.cached_only)
                 else 'submit/resume'),
        'n_inputs': len(rows), 'n_cached': sum(1 for r in rows if r['state'] == 'cached'),
        'n_need_create': need_submit, 'n_held': sum(1 for r in rows if 'held' in r['state']),
        'held_credits': held_c, 'planned_credits_upper': est,
        'budget': budget, 'entries': rows,
    }, indent=2, ensure_ascii=False))

    if a.dry_run or not (a.submit or a.resume or a.cached_only):
        print('\n[dry-run] 不联网、不上传、不提交。加 --submit 才会真正创建任务。')
        return 0
    if a.cached_only:
        return 0

    if not budget:
        raise SystemExit(f'缺预算配置 {a.budget}：未核定预算时拒绝付费 create')
    if os.environ.get('AHOLO_API_KEY') is None:
        print('\n[BLOCKED] 缺少 AHOLO_API_KEY：无法执行上传与提交。'
              '其余工作（计划、缓存校验、离线处理）已完成。')
        return 3

    for item, row in zip(plan_entries(plan), rows):
        if row['state'] not in ('need_create',):
            continue
        ident = row['identity']
        item_model = item['model']
        ok, why = led.reserve(ident, float(plan.get('credits_upper_per_task', 20)), budget)
        if not ok:
            print(f'[budget] 停止新增：{why}')
            break
        img_url = item.get('image_url')
        if not img_url:
            print(f'[blocked] {item["id"]} 没有 image_url：需要官方上传接口，未擅自换公共图床')
            led.update(ident, status=ST_FAILED, note='no_upload_url')
            continue
        try:
            tid = submit_img_to_3d(img_url, item_model)
        except Exception as e:
            led.update(ident, status=ST_UNCERTAIN, note=f'submit_error: {type(e).__name__}')
            print(f'[uncertain] {item["id"]}: {e} —— 不重提，先查询')
            continue
        led.update(ident, status=ST_SUBMITTED, task_id=tid)
        print(f'[submitted] {item["id"]} task_id={tid}')
        try:
            j = poll(tid)
        except Exception as e:
            led.update(ident, status=ST_UNCERTAIN, note=f'poll_error: {type(e).__name__}')
            continue
        if j.get('status') == 3:
            urls = [o['content'] for o in j.get('outputs', []) if o.get('content')]
            d = cache_path(a.cache, ident); d.mkdir(parents=True, exist_ok=True)
            try:
                files = download_urls(urls, d)
            except Exception as e:
                led.update(ident, status=ST_FAILED, note=f'download_error: {type(e).__name__}')
                continue
            glb = next((f for f in files if f.suffix == '.glb'), files[0] if files else None)
            if glb is None or glb.open('rb').read(4) != b'glTF':
                led.update(ident, status=ST_INVALID, note='not_glb')
                continue
            (d / 'meta.json').write_text(json.dumps({
                'identity': ident, 'task_id': tid, 'glb_sha': sha256_file(glb),
                'request': item_model, 'variant': item.get('variant', 'orig'),
                'ts': time.time()}, ensure_ascii=False, indent=2))
            led.update(ident, status=ST_DOWNLOADED, glb_sha=sha256_file(glb))
            print(f'[downloaded] {item["id"]} -> {glb}')
        else:
            led.update(ident, status=ST_FAILED, note=f'task_status={j.get("status")}')

    print(json.dumps({'held_credits_after': led.held_credits(),
                      'held_tasks_after': led.held_tasks()}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
