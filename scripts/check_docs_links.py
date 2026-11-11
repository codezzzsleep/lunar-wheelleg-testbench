#!/usr/bin/env python3
"""文档链接检查：找出 Markdown 里指向不存在文件的引用。

背景：`docs/` 经过一次归档重组（58 篇历史文档移入 `docs/archive/`），仓库里原有的
`docs/LINK_CHECK.md` 只覆盖 v3 那批生成物，对 v4–v8 与归档后的新路径没有约束。
本脚本是轻量的替代：扫所有 md 里的

  · 反引号路径 `` `docs/xxx.md` `` / `` `runs/xxx/yyy.json` ``
  · Markdown 链接 `[文字](相对路径)` 与 `[文字](相对路径#锚点)`

按"相对当前文件所在目录"→"相对仓库根"的顺序解析，报出两边都不存在的路径。
外链（http/https/mailto）与同文档锚点跳过。

用法：

    python3 scripts/check_docs_links.py               # 报告，有悬空引用则退出 1
    python3 scripts/check_docs_links.py --baseline 28  # 只允许不超过基线的数量（历史遗留门禁）
    python3 scripts/check_docs_links.py --only docs/v8  # 只看某个子树

退出码：0 = 通过；1 = 有悬空引用（或超过 --baseline）。
"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'vendor', 'dist', 'assets', 'runs',
             'legacy_p58_preview'}

# 反引号里以这些前缀开头的才当路径检查（避免把普通词语当路径）
PATH_PREFIXES = ('docs/', 'scripts/', 'runs/', 'configs/', 'plans/', 'cases/', 'tests/',
                 'scenes/', 'assets/', 'dist/', 'demo/', 'reports/', 'references/', 'tasks/')
TICK_RE = re.compile(r'`([^`\n]{3,200})`')
MD_LINK_RE = re.compile(r'\[[^\]]*\]\(([^)\s]+?)(?:#[^)]*)?\)')


def md_files(only=None):
    base = ROOT / only if only else ROOT
    for p in base.rglob('*.md'):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def normalize(ref):
    """把文档里的引用收敛成单个路径：去锚点、去行号、命令行取第一个 token。"""
    ref = ref.split('#')[0].strip()
    if ' ' in ref:                      # 形如 `scripts/pipeline.py --demo`：只查命令本身
        ref = ref.split()[0]
    ref = re.sub(r':\d+(-\d+)?$', '', ref)      # `docs/x.md:19-107` / `scripts/y.py:97`
    return ref


def resolves(ref, src_dir):
    """True = 可解析（含"不该判为路径"的形态）。"""
    raw = ref.strip()
    if not raw or raw.startswith(('http://', 'https://', 'mailto:', '/', '#', '<')):
        return True
    ref = normalize(raw)
    # 通配、目录、花括号列举、省略号、行号范围都当作"不是单个可解析路径"，跳过
    if any(ch in ref for ch in '*?{}<>…()') or '...' in ref or ref.endswith('/'):
        return True
    if ':' in ref:                      # 仍带冒号（如 a.py::TestX）不判
        return True
    for cand in (src_dir / ref, ROOT / ref):
        if cand.exists():
            return True
    return False


IGNORE_BLOCK = re.compile(r'<!--\s*link-check:ignore-start\s*-->.*?<!--\s*link-check:ignore-end\s*-->',
                          re.S)


def scan(files):
    dangling = []
    for f in files:
        text = f.read_text(encoding='utf-8', errors='replace')
        # 允许用成对注释标记"这里故意列举了不存在的路径"（例如缺陷清单）
        text = IGNORE_BLOCK.sub('', text)
        src = f.parent
        for m in TICK_RE.finditer(text):
            ref = m.group(1).strip()
            if ref.startswith(PATH_PREFIXES) and not resolves(ref, src):
                dangling.append((str(f.relative_to(ROOT)), ref, 'tick'))
        for m in MD_LINK_RE.finditer(text):
            ref = m.group(1).strip()
            if ref.startswith(('http', 'mailto:', '#')):
                continue
            if not resolves(ref, src):
                dangling.append((str(f.relative_to(ROOT)), ref, 'link'))
    return dangling


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default=None, help='只看某个子树，如 docs/v8')
    ap.add_argument('--baseline', type=int, default=None,
                    help='允许的历史遗留悬空引用上限（超过则失败）')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--count', action='store_true',
                    help='只打印悬空引用条数（给 check_repo_hygiene.py 调用）')
    a = ap.parse_args(argv[1:])

    files = list(md_files(a.only))
    bad = scan(files)
    uniq = sorted({(f, r) for f, r, _ in bad})
    if a.count:
        print(len(uniq))          # 按"不同的悬空目标"计数，重复提及不重复计
        return 0 if not bad else 1
    if not a.quiet:
        print(f'检查 {len(files)} 个 md，悬空引用 {len(bad)} 处 / {len(uniq)} 个不同路径')
        for f, ref in uniq:
            print(f'  {f}  ->  {ref}')
    if a.baseline is not None and len(uniq) <= a.baseline:
        print(f'在基线 {a.baseline} 以内，通过')
        return 0
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
