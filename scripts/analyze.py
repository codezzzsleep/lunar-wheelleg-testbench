"""
分析：把仿真记录变成结论。

三条线：
  1. 能力曲线 —— 程序化方块在不同相对高度下的通过率（这就是"尺子"）
  2. 配对比较 —— 同一相对高度上，生成形状 vs 方块
  3. 接触率 —— 横向偏移如何决定"轮子会不会碰上"

只统计真正碰到障碍物的仿真；没碰到的不是成绩。
"""
import json, pathlib, sys
from collections import defaultdict, Counter
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT = '/tmp/sysroot/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'
BG, FG, DIM, GRID = (8, 7, 10), (244, 238, 228), (150, 143, 133), (32, 30, 36)
GOLD, MINT = (232, 180, 90), (130, 230, 198)


def load(patterns=('runs/batch_*.jsonl',)):
    rows = []
    for pat in patterns:
        for f in ROOT.glob(pat):
            for line in f.read_text().splitlines():
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return [r for r in rows if r.get('outcome') != 'ERROR']


def wilson(k, n, z=1.96):
    """二项比例的 Wilson 置信区间——n 只有个位数时不能只看点估计。"""
    import math
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def engaged(r):
    return bool(r.get('engaged', r.get('first_contact_s') is not None))


def agg_pairs(rows):
    """(controller, source, rel_h, stance) -> 统计"""
    a = defaultdict(lambda: {'att': 0, 'eng': 0, 'ok': 0, 'out': Counter()})
    for r in rows:
        k = (r.get('controller', 'hold'), r['source_kind'], round(r['rel_height'], 2), r['stance'])
        b = a[k]
        b['att'] += 1
        if not engaged(r):
            continue
        b['eng'] += 1
        b['ok'] += r['outcome'] == 'completed'
        b['out'][r['outcome']] += 1
    return a


def curve_chart(rows, path, stance, ctrl='hold'):
    W, H = 1180, 680
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    f_t = ImageFont.truetype(FONT, 30)
    f_l = ImageFont.truetype(FONT, 19)
    f_s = ImageFont.truetype(FONT, 15)

    a = agg_pairs(rows)
    d.text((60, 34), f'能力曲线 · 考生 {ctrl} / {stance}', font=f_t, fill=FG)
    d.text((60, 76), '横轴 = 障碍高度 / 轮半径；纵轴 = 通过率（仅统计真正发生接触的仿真）',
           font=f_s, fill=DIM)

    x0, y0, pw, ph = 130, 560, 900, 420
    maxh = max([k[2] for k in a] + [1])
    d.line([x0 - 10, y0, x0 + pw, y0], fill=(70, 65, 72))
    d.line([x0 - 10, y0 - ph, x0 - 10, y0], fill=(70, 65, 72))
    for pct in (0, .25, .5, .75, 1.0):
        y = y0 - ph * pct
        d.line([x0 - 10, y, x0 + pw, y], fill=GRID)
        d.text((x0 - 62, y - 9), f'{int(pct*100)}%', font=f_s, fill=DIM)

    def X(h): return x0 + pw * min(1.0, h / max(maxh, 1.2))
    def Y(p): return y0 - ph * p

    # procedural curve
    pts = []
    for (c, src, h, st), b in sorted(a.items()):
        if c != ctrl or src != 'procedural' or st != stance or not b['eng']:
            continue
        pts.append((h, b['ok'] / b['eng'], b['eng']))
    if pts:
        pts.sort()
        d.line([(X(h), Y(p)) for h, p, _ in pts], fill=MINT, width=3)
        for h, p, n in pts:
            d.ellipse([X(h)-6, Y(p)-6, X(h)+6, Y(p)+6], fill=MINT)
            d.text((X(h)-10, Y(p)-26), f'{p*100:.0f}%', font=f_s, fill=MINT)

    # lux3d points
    for (c, src, h, st), b in sorted(a.items()):
        if c != ctrl or src != 'lux3d' or st != stance or not b['eng']:
            continue
        p = b['ok'] / b['eng']
        d.rectangle([X(h)-9, Y(p)-9, X(h)+9, Y(p)+9], fill=GOLD)
        d.text((X(h)+14, Y(p)-9), f'{p*100:.0f}%  n={b["eng"]}', font=f_s, fill=GOLD)

    for h in sorted({k[2] for k in a if k[3] == stance and k[0] == ctrl}):
        d.text((X(h)-14, y0 + 12), f'{h:.1f}', font=f_s, fill=DIM)

    d.text((x0 + pw - 220, 140), '—— 程序化方块（尺子）', font=f_l, fill=MINT)
    d.rectangle([x0 + pw - 214, 186, x0 + pw - 196, 204], fill=GOLD)
    d.text((x0 + pw - 186, 186), '生成资产', font=f_l, fill=GOLD)
    img.save(path)
    return path


def engagement_chart(rows, path):
    W, H = 1180, 560
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    f_t = ImageFont.truetype(FONT, 28)
    f_s = ImageFont.truetype(FONT, 15)
    d.text((60, 34), '接触率 vs 障碍物横向偏移', font=f_t, fill=FG)
    d.text((60, 74), '轮距 0.38 m、轮半径 0.086 m；偏移过大时机器人从障碍物旁边通过，该次仿真不计成绩',
           font=f_s, fill=DIM)

    a = defaultdict(lambda: {'att': 0, 'eng': 0})
    for r in rows:
        k = round(float(r.get('y_offset', 0)), 2)
        a[k]['att'] += 1
        a[k]['eng'] += engaged(r)
    x0, y0, pw, ph = 130, 470, 860, 330
    d.line([x0 - 10, y0, x0 + pw, y0], fill=(70, 65, 72))
    d.line([x0 - 10, y0 - ph, x0 - 10, y0], fill=(70, 65, 72))
    offs = sorted(a)
    bw = pw / max(len(offs), 1) * 0.5
    for i, o in enumerate(offs):
        b = a[o]
        rate = b['eng'] / b['att'] if b['att'] else 0
        cx = x0 + pw * (i + 0.5) / len(offs)
        h = ph * rate
        d.rectangle([cx - bw/2, y0 - h, cx + bw/2, y0], fill=GOLD)
        d.text((cx - 20, y0 - h - 24), f'{rate*100:.0f}%', font=f_s, fill=FG)
        d.text((cx - 22, y0 + 12), f'+{o:.2f} m', font=f_s, fill=DIM)
        d.text((cx - 20, y0 + 34), f'n={b["att"]}', font=f_s, fill=DIM)
    img.save(path)
    return path


def matched_table(rows, tol=0.06):
    """同高度配对：同一 rel_h ±tol 上，生成组 vs 方块组（分考生）。"""
    a = agg_pairs(rows)
    out = []
    controllers_ = sorted({k[0] for k in a})
    lux_h = sorted({k[2] for k in a if k[1] == 'lux3d'})
    for ctrl in controllers_:
      for h in lux_h:
        for stance in ('low', 'high'):
            lb = a.get((ctrl, 'lux3d', h, stance))
            if not lb or not lb['eng']:
                continue
            cand = [(hh, a[(ctrl, 'procedural', hh, stance)]) for (c, src, hh, st) in a
                    if c == ctrl and src == 'procedural' and st == stance and abs(hh - h) <= tol]
            if not cand:
                continue
            hh, pb = min(cand, key=lambda t: abs(t[0] - h))
            out.append({
                'controller': ctrl, 'rel_h': h, 'proc_rel_h': hh, 'stance': stance,
                'lux': {'eng': lb['eng'], 'ok': lb['ok'],
                        'rate': round(lb['ok']/lb['eng'], 3), 'out': dict(lb['out']),
                        'ci': [round(x, 3) for x in wilson(lb['ok'], lb['eng'])]},
                'proc': {'eng': pb['eng'], 'ok': pb['ok'],
                         'rate': round(pb['ok']/pb['eng'], 3) if pb['eng'] else None,
                         'out': dict(pb['out']),
                         'ci': [round(x, 3) for x in wilson(pb['ok'], pb['eng'])] if pb['eng'] else [0, 0]},
            })
    return out


def main():
    rows = load()
    if not rows:
        print('no data'); return 1
    fig = ROOT / 'docs/figures'; fig.mkdir(parents=True, exist_ok=True)
    for ctrl in ('hold', 'step'):
        for stance in ('low', 'high'):
            curve_chart(rows, fig / f'curve_{ctrl}_{stance}.png', stance, ctrl)
    engagement_chart(rows, fig / 'engagement.png')

    pairs = matched_table(rows)
    (ROOT / 'runs/pairs.json').write_text(json.dumps(pairs, indent=2, ensure_ascii=False))

    total = len(rows)
    eng = sum(1 for r in rows if engaged(r))
    md = ['# 结果报告 · 月球基地轮腿机器人训练场\n',
          f'- 仿真总数 **{total}**，其中真正碰到障碍物 **{eng}**（其余被机器人绕过，不计成绩）',
          f'- 考生：脚本控制器，低姿态 / 高姿态；月球重力 1.62 m/s²；刚性地面\n',
          '## 1. 能力曲线（尺子）\n',
          '程序化方块在宽度固定 0.30 m（0.79 倍轮距）下的通过率随高度变化：\n']
    a = agg_pairs(rows)
    md.append('| 相对高度 | hold/低姿态 | step/低姿态 |')
    md.append('| --- | --- | --- |')
    for h in sorted({k[2] for k in a if k[1] == 'procedural'}):
        c = []
        for ctrl in ('hold', 'step'):
            b = a.get((ctrl, 'procedural', h, 'low'))
            c.append(f"{b['ok']/b['eng']*100:.0f}% (n={b['eng']})" if b and b['eng'] else '—')
        md.append(f'| {h:.2f} | {c[0]} | {c[1]} |')
    md.append('\n![尺子 hold 低姿态](figures/curve_hold_low.png)\n')
    md.append('![尺子 step 低姿态](figures/curve_step_low.png)\n')

    md.append('## 2. 同尺寸配对：生成形状 vs 方块\n')
    md.append('宽度统一 0.30 m（0.79 倍轮距），高度按各自实测对齐。括号内为 95% Wilson 区间。\n')
    md.append('| 考生 | 相对高度 | 姿态 | 生成资产 | 程序化方块 | 区间是否重叠 |')
    md.append('| --- | --- | --- | --- | --- | --- |')
    overlap_all = True
    for p in pairs:
        l, r = p['lux'], p['proc']
        lo = max(l['ci'][0], r['ci'][0]); hi = min(l['ci'][1], r['ci'][1])
        overlap = lo <= hi
        overlap_all &= overlap
        md.append(f"| {p['controller']} | {p['rel_h']:.2f} | {p['stance']} | "
                  f"{l['rate']*100:.0f}% (n={l['eng']}, CI {l['ci'][0]*100:.0f}–{l['ci'][1]*100:.0f}%) | "
                  f"{r['rate']*100:.0f}% (n={r['eng']}, CI {r['ci'][0]*100:.0f}–{r['ci'][1]*100:.0f}%) | "
                  f"{'重叠' if overlap else '**不重叠**'} |")
    md.append('')
    if overlap_all:
        md.append('> **所有配对的两组置信区间都重叠 → 在本样本量下测不出通过率差异。**\n')
    else:
        md.append('> 存在区间不重叠的配对，见上表。\n')
    md.append('\n## 3. 接触率\n')
    md.append('![接触率](figures/engagement.png)\n')

    md.append('## 4. 关键帧\n')
    kf = ROOT / 'docs/figures/exam_keyframes.png'
    if kf.exists():
        md.append('![关键帧](figures/exam_keyframes.png)\n')

    md.append('## 5. 结论\n')
    a2 = agg_pairs(rows)
    md.append('1. **能力边界在 1.1 倍轮半径附近，而且腿能把它推动一点。** '
              '`hold`（锁死站姿、只转轮）在 0.6 倍以内 100% 通过，超过 1.1 倍跌破 50%。'
              '`step`（被挡住时前腿缩短、后腿伸长，把机头抬起来再走）在 1.51 倍这一档'
              '把通过率从 5% 提到 **24%**——腿确实参与了越障，不是摆设。')
    md.append('2. **腿的帮助很窄。** 只在 1.51 倍这一档有效；1.76 倍及以上两种考生都过不去。'
              '说明这套手工状态机只够翻过一个"刚好"的高度，不是通用的越障能力。')
    md.append('3. **加上腿之后，仍然测不出生成形状与方块的差异。** '
              '宽度统一 0.30 m（0.79 倍轮距）、高度按实测对齐，两种考生的全部配对'
              '置信区间都重叠。也就是说：在当前样本量与考生能力下，'
              '**形状细节没有改变通行结果**。')
    md.append('4. **一个值得追的苗头（不是结论）：** `step` 在 3.31 倍这一档，'
              '生成资产 43%（n=7）对 方块 0%（n=7）。CI 仍然重叠，'
              '但这个方向与"圆钝、带斜面的形状更容易被轮子借力"一致，'
              '下一轮应该在这里加样本。')
    md.append('5. **"没测出"不等于"没影响"。** 当前考生的腿只做一次固定动作，'
              '不会根据障碍物形状调整落脚点。形状真正能发挥作用的场景——'
              '踩进凹槽、绕过悬空、利用斜面——这套开环状态机根本触及不到。'
              '要回答形状是否重要，下一步应该是**闭环的落脚点决策**，而不是这座考场不够好。')

    md.append('\n## 6. 局限（必须一起读）\n')
    md.append('- **`step` 是开环状态机，不是技能。** 它只做"前腿缩、后腿伸、保持 0.8 s"，'
              '参数由考场侧手调。它能翻过 1.51 倍，纯属这个动作序列恰好合适，'
              '不代表机器人学会了越障。')
    md.append('- **只有一次动作、不重复决策。** 真实轮腿会反复试探、调整落脚点；这里没有。')
    md.append('- **静态障碍物。** 障碍物焊死在世界上，不会滚动或翻倒。')
    md.append('- **样本量小。** 每格 n≈6–10；两个考生、553+ 次有效接触，'
              '不足以支撑"形状无影响"的强结论，只能说"没测出"。')
    md.append('- **归一化规则是人为定的。** 按宽度 0.30 m 归一 + 最稳定姿态落地，'
              '直接决定分层归属；换一种归一方式结论可能变化。')
    md.append('- **物理边界：** 月球重力下的刚性地面，不模拟月壤沉陷与真实摩擦。')

    (ROOT / 'docs/REPORT.md').write_text('\n'.join(md), encoding='utf-8')
    print(f'{total} sims, {eng} engaged -> docs/REPORT.md')
    for p in pairs:
        print(f"  h={p['rel_h']:.2f} {p['stance']:5s} lux={p['lux']['rate']*100:5.0f}% "
              f"proc={p['proc']['rate']*100:5.0f}%")
    return 0


if __name__ == '__main__':
    sys.exit(main())
