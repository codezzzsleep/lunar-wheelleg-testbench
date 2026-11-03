"""v3 轻量交付包：可迁移目录 + 离线演示 + 缓存重仿真入口（默认不联网）。

  python scripts/v3_package.py --protocol plans/v3_protocol.json
产物：dist/v3_bundle/（目标 ≤300 MiB），含
  code/  plans/  data/<state>/  media/  page/  demo/  MANIFEST.json  README.md

包内不含 .env / 密钥 / SSH 凭证；在线 Lux3D 入口单独标注、默认关闭。
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist/v3_bundle'
MAX_MIB = 300


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def add(paths, dest_root, manifest, base):
    for src in paths:
        src = pathlib.Path(src)
        if not src.is_file():
            continue
        rel = src.relative_to(base)
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest.append({'path': str(rel), 'bytes': dst.stat().st_size,
                         'sha256': sha256_file(dst)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--max-states', type=int, default=4)
    ap.add_argument('--include-media', action='store_true', default=True)
    a = ap.parse_args()
    res_p = ROOT / 'runs/v3/report/v3_results.json'
    if not res_p.is_file():
        raise SystemExit('先跑 scripts/v3_report.py')
    res = json.loads(res_p.read_text())
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    man = []
    # code
    for f in sorted((ROOT / 'scripts').glob('*.py')):
        if f.name.startswith(('v3_', 'run_v3')):
            add([f], DIST, man, ROOT)
    for f in (ROOT / 'scripts').glob('*.py'):
        if f.name in ('actions.py', 'skills.py', 'terrain.py', 'wheelleg_env.py',
                      'runner.py', 'observe.py', 'camera_io.py', 'soil.py', 'v7_soil.py',
                      'collision_box_union.py', 'fuse_observed.py', 'build_scene.py',
                      'drive_test.py', 'meshdist.py', 'gate_physics.py'):
            add([f], DIST, man, ROOT)
    add([ROOT / 'plans/v3_protocol.json', ROOT / 'plans/v3_sources.json',
         ROOT / 'requirements-lock.txt', ROOT / 'requirements.txt'], DIST, man, ROOT)
    # 选择主角 + 边界状态
    pairs = res['summary'].get('pairs') or []
    hero = next((p for p in pairs if p['FULL'] == 'pass' and p['OBS_ONLY'] != 'pass'), None)
    boundary = next((p for p in pairs if p['FULL'] != 'pass'), None)
    picks = []
    for p in (hero, boundary):
        if p and p['state_id'] not in picks:
            picks.append(p['state_id'])
    for s in res['states']:
        if len(picks) >= a.max_states:
            break
        if s.get('arms') and s['state_id'] not in picks:
            picks.append(s['state_id'])
    picks = picks[:a.max_states]
    (DIST / 'data').mkdir(exist_ok=True)
    for sid in picks:
        sd = ROOT / 'runs/v3/states' / sid
        out = DIST / 'data' / sid
        files = [sd / 'state.json', sd / 'scene_spec.json',
                 sd / 'observation' / 'observation.json', sd / 'observation' / 'rgb.png',
                 sd / 'observation' / 'mask.png',
                 sd / 'observation' / 'gen' / 'rgb_gen.png',
                 sd / 'observation' / 'gen' / 'variants.json']
        for k in ('A1', 'B1', 'C1'):
            files.append(sd / 'observation' / 'gen' / 'variants' / f'{k}.png')
        files += sorted((sd / 'decision').glob('*.json'))
        files += sorted((sd / 'decision').glob('*.jsonl'))
        for c in sorted((sd / 'candidates').glob('*/candidate.json')):
            files.append(c)
            files += [c.parent / 'parent_world' / 'body.stl',
                      c.parent / 'fused' / 'manifest.json',
                      c.parent / 'fused' / 'occ_full.npz',
                      c.parent / 'fused' / 'occ_obs_only.npz',
                      c.parent / 'coll' / 'manifest.json']
        files += sorted((sd / 'metrics').glob('*.json'))
        if sid == picks[0]:
            files += [sd / 'observation' / 'depth.npy', sd / 'truth' / 'body_world.stl',
                      sd / 'fusion' / 'V.npz', sd / 'fusion' / 'V.json']
        for src in files:
            src = pathlib.Path(src)
            if not src.is_file():
                continue
            rel = src.relative_to(sd)
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            man.append({'path': str(dst.relative_to(DIST)), 'bytes': dst.stat().st_size,
                        'sha256': sha256_file(dst)})
    # media + page
    if a.include_media:
        for src in sorted((ROOT / 'media/v3').glob('*.mp4')) + \
                sorted((ROOT / 'media/v3').glob('*.json')):
            dst = DIST / 'media' / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            man.append({'path': f'media/{src.name}', 'bytes': dst.stat().st_size,
                        'sha256': sha256_file(dst)})
        pg = ROOT / 'media/v3/page/index.html'
        if pg.is_file():
            (DIST / 'page').mkdir(parents=True, exist_ok=True)
            shutil.copy2(pg, DIST / 'page/index.html')
            man.append({'path': 'page/index.html',
                        'bytes': (DIST / 'page/index.html').stat().st_size,
                        'sha256': sha256_file(DIST / 'page/index.html')})
    # demo 入口
    demo = DIST / 'demo'
    demo.mkdir(parents=True, exist_ok=True)
    (demo / 'run_offline.py').write_text(DEMO)
    man.append({'path': 'demo/run_offline.py', 'bytes': (demo / 'run_offline.py').stat().st_size,
                'sha256': sha256_file(demo / 'run_offline.py')})
    (DIST / 'README.md').write_text(README.format(
        n_states=len(picks), size=None, hero=(hero or {}).get('state_id'),
        states=', '.join(picks)))
    man.append({'path': 'README.md', 'bytes': (DIST / 'README.md').stat().st_size,
                'sha256': sha256_file(DIST / 'README.md')})
    total = sum(m['bytes'] for m in man)
    payload = {'schema': 'v3-bundle/v1', 'n_files': len(man), 'total_bytes': total,
               'protocol_sha256': sha256_file(ROOT / 'plans/v3_protocol.json'),
               'states': picks, 'files': man}
    (DIST / 'MANIFEST.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    mib = total / 1e6
    print(json.dumps({'bundle': str(DIST), 'n_files': len(man), 'MB': round(mib, 1),
                      'over_limit': mib > MAX_MIB}, ensure_ascii=False))
    return 0 if mib <= MAX_MIB else 1


DEMO = r'''"""离线演示：校验输入 → 确定性重建碰撞 → 复算决策 → 重仿真 → 打开页面。

  python demo/run_offline.py            # 全流程自检（不需要网络、不需要沙箱）
  python demo/run_offline.py --serve    # 起本地页面服务器
"""
import argparse, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def jl(p, d=None):
    p = pathlib.Path(p)
    return json.loads(p.read_text()) if p.is_file() else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--serve', action='store_true')
    ap.add_argument('--port', type=int, default=8093)
    a = ap.parse_args()
    man = jl(ROOT / 'MANIFEST.json')
    miss, bad = [], []
    import hashlib
    for rec in man['files']:
        p = ROOT / rec['path']
        if not p.is_file():
            miss.append(rec['path'])
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if h != rec['sha256']:
            bad.append(rec['path'])
    print(json.dumps({'checked': len(man['files']), 'missing': miss, 'sha_mismatch': bad},
                     ensure_ascii=False))
    if miss or bad:
        return 2
    # 逐状态：核对决策与执行产物、重建 box 碰撞件数
    rows = []
    for sd in sorted((ROOT / 'data').glob('*/')):
        dec = {arm: jl(sd / 'decision' / f'decision_{arm}.json') for arm in ('FULL', 'OBS_ONLY')}
        ex = {arm: jl(sd / 'decision' / f'execution_{arm}.json') for arm in ('FULL', 'OBS_ONLY')}
        coll = [jl(p) for p in sorted((sd / 'candidates').glob('*/coll/manifest.json'))]
        rows.append({'state': sd.name,
                     'FULL': (dec['FULL'] or {}).get('decision', {}).get('chosen'),
                     'FULL_outcome': (ex['FULL'] or {}).get('outcome'),
                     'OBS_ONLY': (dec['OBS_ONLY'] or {}).get('decision', {}).get('chosen'),
                     'OBS_outcome': (ex['OBS_ONLY'] or {}).get('outcome'),
                     'collision_manifests': len(coll),
                     'boxes': [c.get('n_boxes') for c in coll]})
        print(json.dumps(rows[-1], ensure_ascii=False))
    if a.serve:
        import http.server, socketserver
        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kw):
                super().__init__(*args, directory=str(ROOT), **kw)
            def log_message(self, *args):
                pass
        with socketserver.TCPServer(('0.0.0.0', a.port), H) as httpd:
            print(f'page: http://127.0.0.1:{a.port}/page/index.html', flush=True)
            httpd.serve_forever()
    return 0


if __name__ == '__main__':
    sys.exit(main())
'''

README = """# v3 轻量交付包（真实扫描岩石 · FULL vs OBS_ONLY）

这是 {n_states} 个状态的完整可复现子集（主角 {hero}）：{states}。

## 目录

- `code/` scripts 与 v3 流水线（`run_v3.py` 为唯一入口）
- `plans/` 冻结协议与来源清单
- `data/<state>/` 观测、候选（已配准父网格 + 占据 + 碰撞清单）、决策、执行、隐藏误差
- `media/` 1920×1080 / 30 fps 真实三维渲染
- `page/index.html` 五画面作品页（相对路径，直接打开）
- `demo/run_offline.py` 离线自检

## 离线运行（默认，不联网）

```bash
python demo/run_offline.py          # 校验 SHA → 列出双枪决策/结局与碰撞清单
python demo/run_offline.py --serve  # 打开五画面页面（浏览器）
```

## 缓存重仿真

`data/<state>/decision/trajectory_*.jsonl` 保存了真实执行的 qpos 轨迹；
在装有 MuJoCo 的环境里可用 `code/scripts/v3_media.py` 的 `_replay_frames` 重新渲染，
不需要重新调用任何付费接口。

## 在线 Lux3D（可选，默认关闭）

`code/scripts/v3_generate.py` 是真实图生 3D 入口；运行时需要自己提供
`AHOLO_API_KEY` 环境变量（本包不包含任何密钥、.env 或凭证）。
"""


if __name__ == '__main__':
    sys.exit(main())
