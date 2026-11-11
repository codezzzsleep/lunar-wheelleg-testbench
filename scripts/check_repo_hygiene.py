#!/usr/bin/env python3
"""仓库卫生检查：止住"把实验产物当源码入库"的老毛病。

背景（2026-11-11 审查）：仓库跟踪 28.7 万个文件，99% 在 `runs/`；其中 4.84 GiB /
175,460 个二进制没有走 LFS。根因是 `.gitignore` 的规则路径与真实布局不符
（写成 `runs/unseen/generation/**`，实际是 `runs/unseen/delivery_v7/*/generation/**`），
于是 68–72 MB 的 `results.zip` 以原始 blob 直接进了历史。.git 因此涨到 8.0 GB。

本脚本只读、不联网、不改任何文件。它做四件事：

1. 校验补丁清单 `PATCH_SHA256.txt`（存在时）；
2. 检查 git-lfs 是否安装——没有 lfs 的机器 clone 后只会拿到指针文件；
3. 找出**直接入库的超大文件**（走 LFS 的文件在 tree 里是指针，约 130 B，
   所以树内尺寸大 = 没走 LFS）；
4. 找出**不该入库的产物路径**（results.zip / lux_cache / bundle / 逐帧目录）。

用法：

    .venv/bin/python scripts/check_repo_hygiene.py            # 报告，退出 0
    .venv/bin/python scripts/check_repo_hygiene.py --strict   # 有违规即退出 1（给 CI 用）

判据可用 `--max-mb` 调（默认 20 MB）。
"""
import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 这些路径形态一律不该以原始 blob 入库（应走 LFS 或干脆不入库）。
ARTIFACT_PATTERNS = [
    (re.compile(r'(^|/)results\.zip$'), 'Lux3D 原始结果包'),
    (re.compile(r'(^|/)lux_cache/'), '生成缓存'),
    (re.compile(r'(^|/)[^/]*_bundle/'), '打包/解包目录'),
    (re.compile(r'(^|/)frames/'), '逐帧产物'),
    (re.compile(r'(^|/)raw/'), '原始采集'),
    (re.compile(r'\.ledger\.lock$'), '运行期锁文件'),
]


def git(*args):
    return subprocess.run(['git', *args], cwd=str(ROOT), capture_output=True, text=True)


def verify_manifest():
    path = ROOT / 'PATCH_SHA256.txt'
    if not path.exists():
        return None, []
    bad, n = [], 0
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        want, _, rel = line.partition('  ')
        target = ROOT / rel.strip()
        n += 1
        if not target.exists():
            bad.append(f'{rel.strip()} 不存在')
            continue
        got = hashlib.sha256(target.read_bytes()).hexdigest()
        if got != want:
            bad.append(f'{rel.strip()} sha256 不符')
    return n, bad


def tracked_blobs():
    """一次 `git ls-tree -r -l HEAD` 拿到 (path, size)。"""
    r = git('ls-tree', '-r', '-l', 'HEAD')
    if r.returncode != 0:
        raise SystemExit(f'git ls-tree 失败：{r.stderr.strip()[:300]}')
    out = []
    for line in r.stdout.splitlines():
        meta, _, path = line.partition('\t')
        parts = meta.split()
        if len(parts) < 4:
            continue
        out.append((path, int(parts[3])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-mb', type=float, default=20.0)
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--strict', action='store_true', help='有违规时退出 1')
    a = ap.parse_args()

    problems, notes = [], []

    n_manifest, bad = verify_manifest()
    if n_manifest is None:
        notes.append('未找到 PATCH_SHA256.txt，跳过补丁校验')
    elif bad:
        problems.append(f'补丁清单校验失败（{len(bad)}/{n_manifest}）：' + '；'.join(bad[:5]))
    else:
        notes.append(f'补丁清单校验通过：{n_manifest}/{n_manifest}')

    if shutil.which('git-lfs') is None:
        problems.append('未安装 git-lfs：clone 后 LFS 文件只会是指针，需要用 lfs 重新检出')
    else:
        notes.append('git-lfs 已安装')

    # 文档链接：历史遗留的悬空引用有固定基线（见 docs/README.md），只拦"新增"。
    doc_baseline = 27
    try:
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/check_docs_links.py'), '--count'],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        n_bad = int(r.stdout.strip()) if r.stdout.strip().isdigit() else -1
    except Exception as e:                                   # noqa: BLE001
        notes.append(f'文档链接检查未执行：{type(e).__name__}')
        n_bad = -1
    if n_bad > doc_baseline:
        problems.append(f'文档悬空目标 {n_bad} 个，超过基线 {doc_baseline}（新增了断链）')
    elif n_bad >= 0:
        notes.append(f'文档悬空目标 {n_bad} 个（基线 {doc_baseline}，没有新增）')

    blobs = tracked_blobs()
    limit = int(a.max_mb * 1024 * 1024)
    big = sorted(((p, s) for p, s in blobs if s > limit), key=lambda x: -x[1])
    if big:
        problems.append(
            f'{len(big)} 个受版本控制的文件超过 {a.max_mb:g} MB 且未走 LFS'
            f'（合计 {sum(s for _, s in big) / 2**30:.2f} GiB）')
        for p, s in big[:a.top]:
            notes.append(f'  大文件 {s / 2**20:7.1f} MB  {p}')

    hits = {}
    for p, _s in blobs:
        for pat, label in ARTIFACT_PATTERNS:
            if pat.search(p):
                hits.setdefault(label, []).append(p)
    if hits:
        total = sum(len(v) for v in hits.values())
        problems.append(f'{total} 个产物类文件仍在版本控制内：' +
                        '、'.join(f'{k} {len(v)}' for k, v in hits.items()))
        for label, ps in list(hits.items())[:3]:
            notes.append(f'  例：{label} → {ps[0]}')

    print(f'仓库：{ROOT}')
    print(f'跟踪文件 {len(blobs)} 个，其中 >{a.max_mb:g} MB 的 {len(big)} 个')
    for s in notes:
        print(f'  {s}' if not s.startswith('  ') else s)
    if not problems:
        print('\n结论：通过（无大文件直入库、无产物入库、清单与 lfs 正常）')
        return 0
    print('\n结论：发现问题')
    for p in problems:
        print(f'  ✗ {p}')
    print('\n建议：新产物先补 .gitignore 规则（用 git check-ignore 验证命中）；'
          '历史重写（git lfs migrate）另议，会改写全部提交哈希。')
    return 1 if a.strict else 0


if __name__ == '__main__':
    sys.exit(main())
