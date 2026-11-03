"""按 task_id 重新下载已存在的 Lux3D 结果（只读，不新建任务、不消耗积分）。

  python scripts/v3_redownload.py --tasks runs/unseen/delivery_v7/v7_20261030_r1/gen_v2/P58_S2/tasks.json \
      --out legacy_p58_preview/gen_v2/P58_S2/raw

对每个 task：get_task -> status==3 -> 下载全部 outputs 原样（含 results.zip）到
<out>/<name>/，写 meta.json（task_id、下载时刻、文件 SHA、原始 URL 列表）。
status!=3 / 404 / 无 outputs 记 missing 与原因，不拿新生成冒充旧原件。
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import lux3d_client as IM


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tasks', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    spec = json.loads((ROOT / a.tasks).read_text())
    out_root = ROOT / a.out
    out_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, t in enumerate(spec.get('tasks') or []):
        if a.limit and i >= a.limit:
            break
        name = t.get('name') or f'task_{i}'
        dest = out_root / name
        tid = t.get('task_id')
        rec = {'name': name, 'task_id': tid, 'image': t.get('image'),
               'image_sha256': t.get('image_sha256'), 'version': t.get('version'),
               'face_count': t.get('face_count'), 'group': t.get('group'),
               'sample_index': t.get('sample_index')}
        if not tid:
            rec.update({'status': 'missing', 'reason': 'no_task_id_in_tasks_json'})
            rows.append(rec)
            continue
        try:
            j = IM.get_task(int(tid))
        except Exception as e:  # noqa: BLE001
            rec.update({'status': 'missing', 'reason': f'get_task_error:{type(e).__name__}:{e}'[:200]})
            rows.append(rec)
            continue
        st = j.get('status')
        urls = [o['content'] for o in (j.get('outputs') or []) if o.get('content')]
        if st != 3 or not urls:
            rec.update({'status': 'missing',
                        'reason': f'provider_status={st}', 'n_outputs': len(urls)})
            rows.append(rec)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        files = []
        for k, u in enumerate(urls):
            fn = pathlib.Path(u.split('?')[0]).name or f'out_{k}'
            p = dest / fn
            try:
                with urllib.request.urlopen(u, timeout=300) as r, p.open('wb') as f:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                files.append({'file': fn, 'bytes': p.stat().st_size, 'sha256': sha256(p)})
            except Exception as e:  # noqa: BLE001
                rec.setdefault('errors', []).append(f'{fn}: {type(e).__name__}: {e}'[:200])
        rec.update({'status': 'downloaded' if files else 'missing',
                    'reason': None if files else 'download_failed',
                    'files': files,
                    'downloaded_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')})
        (dest / 'meta.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        rows.append(rec)
        print(json.dumps({'name': name, 'status': rec['status'],
                          'files': [f['file'] for f in rec.get('files', [])]},
                         ensure_ascii=False), flush=True)
    man = {'schema': 'v3-redownload/v1', 'source_tasks': a.tasks,
           'n_tasks': len(rows),
           'n_downloaded': sum(1 for r in rows if r['status'] == 'downloaded'),
           'n_missing': sum(1 for r in rows if r['status'] == 'missing'),
           'rows': rows}
    (out_root / 'redownload_manifest.json').write_text(
        json.dumps(man, ensure_ascii=False, indent=2))
    print(json.dumps({k: man[k] for k in ('n_tasks', 'n_downloaded', 'n_missing')}))


if __name__ == '__main__':
    main()
