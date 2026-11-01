"""执行生成申请（已获批准）：按 create_order 提交、轮询、下载、落账。

- 失败任务不自动重提，记录失败并保留分母；
- 每任务记录实际 consumedCredits（来自任务详情）；
- 只提交 application.json 里列出的任务，不新增。

  python scripts/v7_gen_run.py --application <json> --limit 2
"""
import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import lux3d_client as LC


def load_env():
    for p in (ROOT / '.env', pathlib.Path('/var/lib/deepseek-harness/Aholo3D/.env')):
        if not p.is_file():
            continue
        for line in p.read_text().splitlines():
            if line.strip() and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--application', required=True)
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 个（0=全部）')
    ap.add_argument('--out', default='assets/generated')
    a = ap.parse_args()
    load_env()
    app = json.loads((ROOT / a.application).read_text())
    tasks = sorted(app['tasks'], key=lambda t: t['create_order'])
    if a.limit:
        tasks = tasks[:a.limit]
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / 'generation_ledger.jsonl'
    results = []
    for t in tasks:
        rec = {'create_order': t['create_order'], 'rock': t['rock'], 'view': t['view'],
               'image': t['image'], 'image_sha256': t['image_sha256'],
               'version': t['version'], 'face_count': t['face_count'],
               'started': time.time()}
        try:
            import imagine
            url = imagine.upload_image(str(ROOT / t['image']))
            rec['image_url'] = url
            r = LC.submit_img_to_3d(url, version=t['version'], face_count=t['face_count'])
            tid = r['taskId']
            rec['task_id'] = tid
            print(f"[{t['rock']}] submitted task {tid}", flush=True)
            d = LC.poll(tid, timeout_s=1800, interval=10)
            rec['status'] = d.get('status')
            rec['consumed_credits'] = d.get('consumedCredits')
            if d.get('status') not in (3, 'success', 'SUCCESS'):
                rec['ok'] = False
                rec['error'] = f"任务未成功：status={d.get('status')} {str(d)[:300]}"
            else:
                urls = []
                for o in (d.get('outputs') or []):
                    if isinstance(o, dict) and o.get('content'):
                        urls.append(o['content'])
                    elif isinstance(o, str):
                        urls.append(o)
                urls = urls or d.get('resultUrls') or d.get('urls') or d.get('files') or []
                if not urls:
                    for k in ('resultUrl', 'downloadUrl', 'url'):
                        if d.get(k):
                            urls = [d[k]]
                            break
                rec['result_urls'] = urls
                dest = out / t['rock']
                saved = LC.download(urls, dest)
                rec['files'] = [{'path': str(p.relative_to(ROOT)), 'sha256': LC.sha256(p),
                                 'bytes': p.stat().st_size} for p in saved]
                rec['ok'] = bool(saved)
        except Exception as e:
            rec['ok'] = False
            rec['error'] = f'{type(e).__name__}: {e}'[:400]
        rec['finished'] = time.time()
        with ledger.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        results.append(rec)
        print(json.dumps({k: rec.get(k) for k in ('rock', 'task_id', 'status', 'ok',
                                                  'consumed_credits')}, ensure_ascii=False),
              flush=True)
    spent = sum(int(r.get('consumed_credits') or 0) for r in results)
    print(json.dumps({'n': len(results), 'ok': sum(1 for r in results if r.get('ok')),
                      'credits_consumed': spent,
                      'failed': [r['rock'] for r in results if not r.get('ok')]},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
