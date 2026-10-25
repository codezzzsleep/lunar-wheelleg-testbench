"""
出报告：读 runs/batch.jsonl，算分组统计，画图，写 docs/REPORT.md。

只用 PIL 画图（本机没有 matplotlib），中文字体用解包出来的文泉驿。
"""
import json, pathlib, sys
from collections import defaultdict, Counter
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT = '/tmp/sysroot/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'
BG, FG, DIM = (8, 7, 10), (244, 238, 228), (150, 143, 133)
GOLD, MINT, ROSE, VIOLET = (232, 180, 90), (130, 230, 198), (255, 143, 163), (164, 135, 255)

LAYERS = ['L0 (<0.5)', 'L1 (0.5-1)', 'L2 (1-1.5)', 'L3 (>1.5)']


def layer_of(rel_h):
    if rel_h < 0.5:  return LAYERS[0]
    if rel_h < 1.0:  return LAYERS[1]
    if rel_h < 1.5:  return LAYERS[2]
    return LAYERS[3]


def load(path):
    rows = []
    for line in pathlib.Path(path).read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return [r for r in rows if r.get('outcome') != 'ERROR']


def group(rows, *keys):
    agg = defaultdict(lambda: {'n': 0, 'ok': 0, 'outcomes': Counter(), 'conc': []})
    for r in rows:
        k = tuple(r[key] for key in keys)
        a = agg[k]
        a['n'] += 1
        a['ok'] += r['outcome'] == 'completed'
        a['outcomes'][r['outcome']] += 1
        if r.get('concavity') is not None:
            a['conc'].append(r['concavity'])
    return agg


def bar_chart(agg, path, stance, sources):
    W, H = 1100, 640
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(FONT, 30)
    f_lbl = ImageFont.truetype(FONT, 20)
    f_small = ImageFont.truetype(FONT, 16)

    d.text((60, 40), f'通过率 · 考生 {stance}', font=f_title, fill=FG)
    d.text((60, 82), '同一几何分层内比较形状来源；柱上数字为该组场景数', font=f_small, fill=DIM)

    x0, y0, pw, ph = 120, 520, 860, 380
    d.line([x0 - 10, y0, x0 + pw, y0], fill=(60, 56, 62))
    d.line([x0 - 10, y0 - ph, x0 - 10, y0], fill=(60, 56, 62))
    for pct in (0, 0.25, 0.5, 0.75, 1.0):
        y = y0 - ph * pct
        d.line([x0 - 10, y, x0 + pw, y], fill=(30, 28, 34))
        d.text((x0 - 60, y - 10), f'{int(pct*100)}%', font=f_small, fill=DIM)

    colors = {'procedural': MINT, 'lux3d': GOLD}
    gw = pw / len(LAYERS)
    bw = gw * 0.30
    for li, layer in enumerate(LAYERS):
        for si, src in enumerate(sources):
            a = agg.get((src, layer))
            cx = x0 + gw * li + gw * 0.5 + (si - (len(sources)-1)/2) * (bw + 14)
            if not a or not a['n']:
                continue
            rate = a['ok'] / a['n']
            h = ph * rate
            d.rectangle([cx - bw/2, y0 - h, cx + bw/2, y0], fill=colors.get(src, VIOLET))
            d.text((cx - 12, y0 - h - 26), f'{rate*100:.0f}%', font=f_small, fill=FG)
            d.text((cx - 10, y0 + 10), f'n={a["n"]}', font=f_small, fill=DIM)
        d.text((x0 + gw * li + 10, y0 + 40), layer, font=f_lbl, fill=FG)

    lx = x0
    for src in sources:
        d.rectangle([lx, 610, lx + 18, 626], fill=colors.get(src, VIOLET))
        d.text((lx + 26, 606), src, font=f_small, fill=FG)
        lx += 150
    img.save(path)
    return path


def contact_sheet(frames, path, cols=4, w=340):
    imgs = [Image.open(f) for f in frames]
    if not imgs:
        return None
    ratio = imgs[0].height / imgs[0].width
    h = int(w * ratio)
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * w, rows * h), BG)
    for i, im in enumerate(imgs):
        sheet.paste(im.resize((w, h)), ((i % cols) * w, (i // cols) * h))
    sheet.save(path)
    return path


def main():
    rows = load(ROOT / 'runs/batch.jsonl')
    if not rows:
        print('no rows'); return 1
    sources = sorted({r['source_kind'] for r in rows})
    stances = sorted({r['stance'] for r in rows})
    fig_dir = ROOT / 'docs/figures'; fig_dir.mkdir(parents=True, exist_ok=True)

    for stance in stances:
        sub = [r for r in rows if r['stance'] == stance]
        bar_chart(_layer_agg(sub), fig_dir / f'pass_{stance}.png', stance, sources)

    md = []
    md.append('# 月球基地轮腿机器人训练场 · 结果报告\n')
    md.append(f'仿真次数 **{len(rows)}**；数据源 `runs/batch.jsonl`。\n')
    md.append('## 结论先行\n')

    # per-layer comparison across sources
    agg = _layer_agg(rows)
    lines = ['| 分层 | 来源 | n | 完成 | 通过率 | 失败构成 | 凹度均值 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for layer in LAYERS:
        for src in sources:
            a = agg.get((src, layer))
            if not a or not a['n']:
                continue
            conc = sum(a['conc']) / len(a['conc']) if a['conc'] else None
            lines.append(f"| {layer} | {src} | {a['n']} | {a['ok']} | "
                         f"{a['ok']/a['n']*100:.0f}% | "
                         f"{', '.join(f'{k}×{v}' for k, v in a['outcomes'].most_common())} | "
                         f"{'' if conc is None else f'{conc:.3f}'} |")
    md.append('\n'.join(lines) + '\n')

    for stance in stances:
        md.append(f'![通过率 {stance}](figures/pass_{stance}.png)\n')

    (ROOT / 'docs/REPORT.md').write_text('\n'.join(md), encoding='utf-8')
    print('wrote docs/REPORT.md')
    return 0


def _layer_agg(rows):
    """按 (来源, 分层) 聚合，两个考生合并。"""
    agg = defaultdict(lambda: {'n': 0, 'ok': 0, 'outcomes': Counter(), 'conc': []})
    for r in rows:
        k = (r['source_kind'], layer_of(r['rel_height']))
        a = agg[k]
        a['n'] += 1
        a['ok'] += r['outcome'] == 'completed'
        a['outcomes'][r['outcome']] += 1
        if r.get('concavity') is not None:
            a['conc'].append(r['concavity'])
    return agg


if __name__ == '__main__':
    sys.exit(main())
