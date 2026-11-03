"""v3 来源池：下载 CC0 真实扫描岩石（Poly Haven），并逐件登记来源与哈希。

只用 Poly Haven 官方 Files API，不镜像、不改写原始文件；
原始 glTF + 纹理 + `provenance.json` 落在 `assets/raw/ph/<asset_id>/`。

  /opt/lunar/bin/python scripts/v3_fetch_rocks.py --plan plans/v3_sources.json
  /opt/lunar/bin/python scripts/v3_fetch_rocks.py --plan plans/v3_sources.json --verify-only

许可：Poly Haven 全站 CC0（https://polyhaven.com/license），逐件记录 authors 与 dims。
命名里的 "moon_rock" 只是 Poly Haven 的合集名，**不是月球采样返回样品**；
本管线只把它当作“真实拍摄/摄影测量扫描的岩石”，正文一律写“仿真中的真实扫描岩石”。
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = 'https://api.polyhaven.com'
DL = 'https://dl.polyhaven.org/file/ph-assets'
LICENSE_URL = 'https://polyhaven.com/license'


def _get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': 'lunar-lab-v3/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _download(url, dest, timeout=300):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return 'cached'
    req = urllib.request.Request(url, headers={'User-Agent': 'lunar-lab-v3/1.0'})
    tmp = dest.with_suffix(dest.suffix + '.part')
    with urllib.request.urlopen(req, timeout=timeout) as r, tmp.open('wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    tmp.replace(dest)
    return 'downloaded'


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def fetch_one(asset_id, out_root, variant='2k', verify_only=False):
    out_root = pathlib.Path(out_root).resolve()
    d = out_root / asset_id
    info = _get_json(f'{API}/info/{asset_id}')
    files = _get_json(f'{API}/files/{asset_id}')
    node = ((files.get('gltf') or {}).get(variant) or {}).get('gltf')
    if not node or not node.get('url'):
        raise SystemExit(f'{asset_id}: no gltf/{variant} available')
    rec = {
        'schema': 'v3-real-rock/v1',
        'asset_id': asset_id,
        'provider': 'Poly Haven',
        'license': 'CC0-1.0',
        'license_url': LICENSE_URL,
        'source_url': f'https://polyhaven.com/a/{asset_id}',
        'api_info': f'{API}/info/{asset_id}',
        'api_files': f'{API}/files/{asset_id}',
        'name': info.get('name'),
        'authors': info.get('authors'),
        'dimensions_mm': info.get('dimensions'),
        'date_published': info.get('date_published'),
        'categories': info.get('categories'),
        'variant': variant,
        'files': {},
        'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'note': ('真实摄影测量扫描件；名称中的 moon 只是 Poly Haven 合集名，'
                 '不是月球采样返回样品。'),
    }
    if not verify_only:
        d.mkdir(parents=True, exist_ok=True)
        main_url = node['url']
        main_name = pathlib.Path(main_url.split('?')[0]).name
        st = _download(main_url, d / main_name)
        rec['files'][main_name] = {'role': 'gltf_main', 'url': main_url,
                                   'md5_api': node.get('md5'), 'size_api': node.get('size'),
                                   'state': st}
        for rel, meta in (node.get('include') or {}).items():
            p = d / rel
            st = _download(meta['url'], p)
            rec['files'][rel] = {'role': 'include', 'url': meta['url'],
                                 'md5_api': meta.get('md5'), 'size_api': meta.get('size'),
                                 'state': st}
    # 校验 md5 与实际大小（cached 也要校验）
    ok = True
    for rel, meta in rec['files'].items():
        p = d / rel
        if not p.is_file():
            ok = False
            meta['error'] = 'missing'
            continue
        h = hashlib.md5(p.read_bytes()).hexdigest()
        meta['md5'] = h
        meta['size'] = p.stat().st_size
        meta['md5_ok'] = (h == meta.get('md5_api'))
        meta['sha256'] = sha256(p)
        ok = ok and meta['md5_ok']
    rec['integrity_ok'] = ok
    rec['gltf_main'] = next((k for k, v in rec['files'].items() if v['role'] == 'gltf_main'), None)
    (d / 'provenance.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    rec['dir'] = str(d.relative_to(ROOT))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', default='plans/v3_sources.json')
    ap.add_argument('--out', default='assets/raw/ph')
    ap.add_argument('--variant', default='2k')
    ap.add_argument('--verify-only', action='store_true')
    a = ap.parse_args()
    plan = json.loads((ROOT / a.plan).read_text())
    ids = [r['asset_id'] for r in plan['pool']]
    out_root = ROOT / a.out
    out_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for aid in ids:
        try:
            rec = fetch_one(aid, out_root, a.variant, a.verify_only)
            rows.append({'asset_id': aid, 'dir': rec['dir'],
                         'integrity_ok': rec['integrity_ok'],
                         'files': len(rec['files']),
                         'bytes': sum(v.get('size') or 0 for v in rec['files'].values())})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001 - 单件失败不阻塞其余来源
            rows.append({'asset_id': aid, 'error': f'{type(e).__name__}: {e}'})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    manifest = {'schema': 'v3-source-pool/v1', 'plan': a.plan, 'variant': a.variant,
                'license': 'CC0-1.0', 'license_url': LICENSE_URL,
                'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'n_requested': len(ids), 'n_ok': sum(1 for r in rows if r.get('integrity_ok')),
                'rocks': rows}
    (out_root / 'pool_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'n_ok': manifest['n_ok'], 'n_requested': len(ids)}, ensure_ascii=False))
    return 0 if manifest['n_ok'] == len(ids) else 1


if __name__ == '__main__':
    sys.exit(main())
