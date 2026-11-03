"""数据发布：生成可下载分卷索引、校验、以及（有凭据时）上传。

  python scripts/v3_publish.py --plan --out dist/publish      # 生成索引与状态
  python scripts/v3_publish.py --verify dist/publish          # 校验本地解包/下载目录
  python scripts/v3_publish.py --upload dist/publish          # 需要 GITHUB_TOKEN 或 gh

没有凭据时 --upload 明确失败并写 PUBLISH_STATUS.json（不假装已发布）。
索引里每条记录：相对路径、字节、SHA256、内容范围、对应场景/候选/运行、
代码/协议身份、下载 URL（上传后回填）。
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
VOLUMES = [
    {'id': 'v3_bundle', 'paths': ['dist/v3_bundle'],
     'content': 'v3 场景级轻量包（代码/协议/数据/媒体/页面/离线演示）',
     'scope': 'v3 批次 48 状态中的 4 个完整状态 + 主角状态观测'},
    {'id': 'v3_media', 'paths': ['media/v3/*.mp4', 'media/v3/page', 'media/v3/manifest.json'],
     'content': '1920x1080/30fps 真实三维渲染与五画面页面',
     'scope': '主角状态 moon_rock_01_h0v0'},
    {'id': 'legacy_p58_preview', 'paths': ['legacy_p58_preview'],
     'content': 'P58·S2 旧预览原件（按 task_id 重新下载的 results.zip）',
     'scope': 'v7_20261030_r1 gen_v2 P58_S2 六个候选；v3batch_nominal coll 缺失'},
    {'id': 'v3_records', 'paths': ['runs/v3/report', 'plans/v3_protocol.json',
                                   'plans/v3_sources.json', 'plans/v3_selected.json'],
     'content': '权威结果表、协议与来源清单',
     'scope': '全部已执行状态'},
]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def expand(root, pats):
    out = []
    for pat in pats:
        p = root / pat
        if any(c in pat for c in '*?'):
            out += [x for x in sorted(root.glob(pat)) if x.is_file() or x.is_dir()]
        elif p.is_dir():
            out += [x for x in sorted(p.rglob('*')) if x.is_file()]
        elif p.is_file():
            out.append(p)
    seen, uniq = set(), []
    for x in out:
        r = x.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(x)
    return uniq


def code_tree_sha(root):
    """实际代码内容身份：scripts/*.py + plans/*.json 的 (path, sha256) 排序哈希。"""
    items = []
    for pat in ('scripts/*.py', 'plans/*.json'):
        for f in sorted(root.glob(pat)):
            items.append((str(f.relative_to(root)), sha256_file(f)))
    h = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    return h


def git_sha(root):
    try:
        return subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def plan(args):
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    code_sha = args.code_sha or git_sha(ROOT)
    tree_sha = code_tree_sha(ROOT)
    proto = ROOT / 'plans/v3_protocol.json'
    proto_sha = sha256_file(proto) if proto.is_file() else None
    vols = []
    for v in VOLUMES:
        files = expand(ROOT, v['paths'])
        recs = [{'path': str(f.relative_to(ROOT)), 'bytes': f.stat().st_size,
                 'sha256': sha256_file(f)} for f in files]
        vols.append({'volume_id': v['id'], 'content': v['content'], 'scope': v['scope'],
                     'n_files': len(recs), 'bytes': sum(r['bytes'] for r in recs),
                     'code_sha': code_sha, 'code_tree_sha256': tree_sha,
                     'protocol_sha256': proto_sha,
                     'download_url': None, 'status': 'staged', 'files': recs})
    idx = {'schema': 'v3-publish-index/v1',
           'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
           'repo': 'codezzzsleep/lunar-wheelleg-testbench',
           'code_sha': code_sha, 'code_tree_sha256': tree_sha,
           'protocol_sha256': proto_sha,
           'volumes': vols}
    (out / 'INDEX.json').write_text(json.dumps(idx, ensure_ascii=False, indent=2))
    missing = [
        {'path': 'runs/unseen/delivery_v7/v7_20261030_r1/gen_v2/P58_S2/raw/*/results.zip',
         'status': 'recovered',
         'note': '原件不在本机；已按 tasks.json 的 task_id 从 API 原样重新下载，'
                 '未新建任务、未消耗积分；文件与 task_id 绑定'},
        {'path': 'runs/unseen/delivery_v7/v7_20261030_r1/v3batch_nominal/P58_S2/*/coll',
         'status': 'asset_missing',
         'note': '该目录整体不存在；同批 v3batch/* 所有状态目录为空（0 文件），'
                 '无法用新生成替代。需要确认是否有其他副本或从 task 重算'},
    ]
    status = {'schema': 'v3-publish-status/v1',
              'generated_at': idx['generated_at'],
              'state': 'blocked_on_credentials' if not _creds() else 'ready',
              'blocked_reason': None if _creds() else
              '缺少 GITHUB_TOKEN/GH_TOKEN 且无 gh/git-lfs，无法创建 Release 或 LFS 上传；'
              '只有 SSH git push 权限',
              'volumes': [{'volume_id': v['volume_id'], 'bytes': v['bytes'],
                           'n_files': v['n_files']} for v in vols],
              'missing': missing}
    (out / 'PUBLISH_STATUS.json').write_text(json.dumps(status, ensure_ascii=False, indent=2))
    print(json.dumps({'out': str(out), 'volumes': status['volumes'],
                      'state': status['state'], 'missing': [m['status'] for m in missing]},
                     ensure_ascii=False))


def _creds():
    return bool(os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
                or shutil.which('gh'))


def verify(args):
    out = pathlib.Path(args.plan_dir)
    idx = json.loads((out / 'INDEX.json').read_text())
    bad, missing, n = [], [], 0
    for v in idx['volumes']:
        for r in v['files']:
            p = out / 'download' / v['volume_id'] / r['path']
            if not p.is_file():
                missing.append(f"{v['volume_id']}:{r['path']}")
                continue
            n += 1
            if sha256_file(p) != r['sha256']:
                bad.append(f"{v['volume_id']}:{r['path']}")
    # 再跑一次解包/加载检查（包内 demo 会做 SHA 与数据读取）
    demo_ok = None
    demo = out / 'download' / 'v3_bundle' / 'dist/v3_bundle' / 'demo' / 'run_offline.py'
    if demo.is_file():
        r = subprocess.run([sys.executable, str(demo)], capture_output=True, text=True)
        demo_ok = r.returncode == 0
    res = {'schema': 'v3-publish-verify/v1', 'checked': n,
           'missing': missing[:20], 'n_missing': len(missing),
           'sha_mismatch': bad[:20], 'n_sha_mismatch': len(bad),
           'bundle_demo_ok': demo_ok,
           'verified_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    (out / 'VERIFY.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if not (missing or bad) else 1


def upload(args):
    out = pathlib.Path(args.plan_dir)
    if not _creds():
        print(json.dumps({'error': 'no_credentials',
                          'message': '缺少 GITHUB_TOKEN/GH_TOKEN 且无 gh；先修凭据再上传。'
                                     '本命令不会把数据写到别处冒充已发布。'},
                         ensure_ascii=False))
        return 2
    print(json.dumps({'error': 'not_implemented',
                      'message': '凭据存在时在此实现 Release 分卷上传与 URL 回填'},
                     ensure_ascii=False))
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--upload', action='store_true')
    ap.add_argument('--out', default='dist/publish')
    ap.add_argument('--code-sha', default=None,
                    help='记录用的仓库提交号（在沙箱里生成时传入宿主 git HEAD）')
    a = ap.parse_args()
    if a.verify:
        return verify(type('A', (), {'plan_dir': a.out})())
    if a.upload:
        return upload(type('A', (), {'plan_dir': a.out})())
    plan(a)
    return 0


if __name__ == '__main__':
    sys.exit(main())
