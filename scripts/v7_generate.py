"""
V7：真实 Lux3D 生成驱动（单图 / 两图），预算先预留，结果落盘可复现。

设计原则：
  · 每次创建前先在**本批独立账本**里 reserve（est_upper=20，来自本仓库历史账本口径），
    同一 identity 已成功则不重复付费（除非显式 --repeat 且带新 sample_id）；
  · resume 只查询/下载，绝不 create；
  · 请求身份 = 模式 + 全部图片字节（有序）+ 版本 + faceCount + sample_id；
  · 单图发送 img，两图发送有序 imgs 且不带 img；
  · 下载 ZIP → 解 GLB → 记录 SHA256 与任务 ID；实际扣费一律 unknown。

  set -a; . /var/lib/deepseek-harness/Aholo3D/.env; set +a
  .venv/bin/python scripts/v7_generate.py --batch-dir runs/unseen/delivery_v7/v7_20261030 \
      --object R02 --images runs/.../upload_pkg/R02/upload_1024.png --sample s1
  .venv/bin/python scripts/v7_generate.py --resume --batch-dir ...
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import budget
import imagine
import lux3d_client as LC

CREDIT_UPPER = 20.0
MODEL_VERSION = 'G1-Turbo'
FACE_COUNT = 30000


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch-dir', required=True)
    ap.add_argument('--object', default=None)
    ap.add_argument('--images', nargs='+', default=None, help='1 张=单图，2 张=两图')
    ap.add_argument('--sample', default='s1', help='采样身份，重复采样必须换')
    ap.add_argument('--resume', action='store_true', help='只查询状态，不创建')
    ap.add_argument('--download', action='store_true', help='只下载已成功的输出，不创建')
    ap.add_argument('--version', default=MODEL_VERSION)
    ap.add_argument('--budget-total', type=float, default=500.0)
    ap.add_argument('--credit-upper', type=float, default=CREDIT_UPPER,
                    help='单任务预留上界（当前价目口径，默认 1.0 需显式传）')
    ap.add_argument('--max-tasks', type=int, default=200,
                    help='计划级防无限重复的任务上限，不由旧估价推导')
    ap.add_argument('--scope', default='v7_r1')
    a = ap.parse_args()
    B = ROOT / a.batch_dir
    gen = B / 'generation'
    gen.mkdir(parents=True, exist_ok=True)
    led = budget.BudgetLedger(str(gen / 'ledger.jsonl'))
    # 单价与任务数解耦：hard_cap 仍是授权总额，per_task_cap 是单任务预留上界；
    # 不再用 budget_total // 25 之类由旧估价推导的硬任务数限制（任务书 §3.2）
    bud = {'hard_cap': a.budget_total,
           'per_task_cap': float(a.credit_upper),
           'max_create_tasks': int(a.max_tasks), 'scope': a.scope}

    if a.download:
        import urllib.request
        import zipfile
        n = 0
        for f in sorted(gen.glob('task_*.json')):
            rec = json.loads(f.read_text())
            tid = rec.get('task_id')
            if not tid or rec.get('glb_sha'):
                continue
            j = imagine.get_task(int(tid))
            if j.get('status') != 3:
                continue
            outs = j.get('outputs') or []
            if not outs:
                continue
            url = outs[0].get('content') or outs[0].get('url')
            d = gen / f'task_{tid}'
            d.mkdir(parents=True, exist_ok=True)
            zp = d / 'results.zip'
            urllib.request.urlretrieve(url, zp)
            glb = None
            with zipfile.ZipFile(zp) as z:
                names = [x for x in z.namelist() if x.lower().endswith('.glb')]
                names.sort(key=lambda x: z.getinfo(x).file_size, reverse=True)
                if names:
                    z.extract(names[0], d)
                    glb = d / names[0]
            rec.update({'status': 3, 'output_url': url, 'zip_sha': sha(zp),
                        'zip_bytes': zp.stat().st_size,
                        'glb_path': str(glb) if glb else None,
                        'glb_sha': sha(glb) if glb else None,
                        'downloaded_at': time.time()})
            f.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
            try:
                led.mark(rec['attempt_id'], budget.ST_DOWNLOADED, task_id=int(tid))
            except Exception:
                pass
            n += 1
            print(json.dumps({'task_id': tid, 'glb': rec['glb_sha'][:12] if glb else None,
                              'bytes': rec['zip_bytes']}, ensure_ascii=False))
        print(json.dumps({'downloaded': n}, ensure_ascii=False))
        return 0

    if a.resume:
        done = 0
        for f in sorted(gen.glob('task_*.json')):
            rec = json.loads(f.read_text())
            if rec.get('status') in (3, 'succeeded') and rec.get('glb_sha'):
                continue
            tid = rec.get('task_id')
            if not tid:
                continue
            j = imagine.poll(int(tid), timeout_s=1, interval=0)
            st = j.get('status')
            print(json.dumps({'task_id': tid, 'status': st}, ensure_ascii=False))
            if st == 3:
                rec['status'] = 3
                f.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
                done += 1
        print(json.dumps({'resumed': done}, ensure_ascii=False))
        return 0

    imgs = [pathlib.Path(p) for p in (a.images or [])]
    if not imgs or a.object is None:
        raise SystemExit('创建需要 --object 与 --images（1 或 2 张）')
    mode = 'img-to-3d-multi' if len(imgs) >= 2 else 'img-to-3d'
    ident = LC.request_identity(mode, imgs, a.version, FACE_COUNT, {'sample': a.sample})
    attempt = hashlib.sha256(f'{ident}|{a.sample}'.encode()).hexdigest()[:32]
    ok, why = led.reserve(ident, attempt, float(a.credit_upper), bud)
    rep = led.report(bud)
    print(json.dumps({'reserve': ok, 'why': why, 'held': rep['held_credits_upper'],
                      'remaining': rep['remaining_credits']}, ensure_ascii=False))
    if not ok:
        return 2 if '已存在' in str(why) else 1

    urls = [imagine.upload_image(p) for p in imgs]
    led.mark(attempt, budget.ST_PLANNED, note=f'uploaded {len(urls)} image(s)')
    t0 = time.time()
    if len(urls) >= 2:
        task = LC.submit_img_to_3d_multi(urls, version=a.version, face_count=FACE_COUNT)
    else:
        task = LC.submit_img_to_3d(urls[0], version=a.version, face_count=FACE_COUNT)
    tid = int(task['taskId'])
    led.mark(attempt, budget.ST_SUBMITTED, task_id=tid, submitted_at=time.time())
    rec = {'schema': 'v7-generation-task/v1', 'object': a.object, 'sample_id': a.sample,
           'mode': 'two_image' if len(urls) >= 2 else 'single_image',
           'n_images': len(urls), 'image_sha256': [sha(p) for p in imgs],
           'image_paths': [str(p) for p in imgs], 'image_urls': urls,
           'version': a.version, 'face_count': FACE_COUNT,
           'request_identity': ident, 'attempt_id': attempt, 'task_id': tid,
           'submitted_at': t0, 'status': 'submitted',
           'legacy_estimate_upper': CREDIT_UPPER,
           'price_expected': float(a.credit_upper),
           'price_basis': 'Lux3D 图生网格极速版 1 积分/次（用户价目截图；未与 API 扣费核对）',
           'price_verified': False,
           'reserved_current': float(a.credit_upper),
           'estimate_upper': float(a.credit_upper),
           'actual_charge': None, 'actual_charge_verified': False, 'verified': 'unknown',
           'batch': B.name}
    f = gen / f'task_{tid}.json'
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({'task_id': tid, 'mode': rec['mode'], 'identity': ident[:12]},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
