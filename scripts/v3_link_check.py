"""交付 QA：检查 docs/*.md 里的相对链接/路径是否存在。"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
pat = re.compile(r'\]\(([^)]+)\)')
hpat = re.compile(r'href="([^"]+)"')
rows = []
for md in sorted((ROOT / 'docs').glob('*.md')) + [ROOT / 'dist/minimal/index.html']:
    text = md.read_text()
    found = hpat.finditer(text) if md.suffix == '.html' else pat.finditer(text)
    for m in found:
        target = m.group(1).strip()
        if target.startswith(('http://', 'https://', '#', 'mailto:')):
            continue
        target = target.split('#')[0].strip('`')
        if not target or target.startswith('<'):
            continue
        cands = [ROOT / target, md.parent / target]
        ok = any(p.exists() for p in cands)
        rows.append({'doc': md.name, 'target': target, 'ok': ok})
broken = [r for r in rows if not r['ok']]
lines = ['# 链接检查', '', f'检查 {len(rows)} 个相对链接，缺失 {len(broken)} 个。', '']
if broken:
    lines += ['| 文档 | 缺失目标 |', '| --- | --- |']
    lines += [f"| {r['doc']} | `{r['target']}` |" for r in broken]
(ROOT / 'docs/LINK_CHECK.md').write_text('\n'.join(lines) + '\n')
print({'n': len(rows), 'broken': len(broken)})
raise SystemExit(1 if broken else 0)
