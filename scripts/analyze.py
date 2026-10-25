"""
分析：把一次运行的 results.jsonl 变成报告。

  python scripts/analyze.py --input runs/<run_id>/results.jsonl --out runs/<run_id>

原则（对应复查意见第 3、4、5、6 节）：
  · 只读 **显式指定** 的结果文件，绝不 glob 历史批次
  · 分组键包含 shape 与 controller：方块 / 圆柱 / 斜坡 / 生成网格、三个考生不混算
  · 报告里每个数字都来自本文件的输入；没有数据的组不生成结论
  · 字体不再硬编码；找不到中文字体时降级为英文标签并明确提示
"""
import argparse
import json
import os
import pathlib
import sys
from collections import Counter, defaultdict
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
BG, FG, DIM, GRID = (8, 7, 10), (244, 238, 228), (150, 143, 133), (32, 30, 36)
GOLD, MINT, VIOLET = (232, 180, 90), (130, 230, 198), (164, 135, 255)

CJK_CANDIDATES = [
    os.environ.get('RLL_FONT', ''),
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    str(ROOT / 'assets/fonts/wqy-zenhei.ttc'),
]


def find_cjk_font():
    """返回 (path, supports_cjk)。找不到就返回 (None, False)，由调用方降级。"""
    for p in CJK_CANDIDATES:
        if p and pathlib.Path(p).exists():
            return str(p), True
    for root in ('/usr/share/fonts', str(pathlib.Path.home() / '.fonts')):
        r = pathlib.Path(root)
        if not r.exists():
            continue
        for pat in ('*wqy*', '*CJK*', '*SourceHan*', '*DroidSansFallback*'):
            hits = sorted(r.rglob(pat))
            if hits:
                return str(hits[0]), True
    return None, False


class LBL:
    """有中文字体就用中文，没有就降级英文（并在报告里说明）。"""

    def __init__(self, has_cjk):
        self.cjk = has_cjk

    def __call__(self, zh, en):
        return zh if self.cjk else en


def load(path):
    rows, bad = [], 0
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    return rows, bad


def counts(rows):
    c = Counter()
    for r in rows:
        c['records'] += 1
        if r.get('status') == 'precheck_failed':
            c['precheck_failed'] += 1
            continue
        c['executed'] += 1
        if r.get('contact_any'):
            c['contact_any'] += 1
        if r.get('contact_wheel'):
            c['contact_wheel'] += 1
        c[r.get('outcome') or 'ERROR'] += 1
    c['not_contacted'] = c['executed'] - c['contact_any']
    return c


def group(rows, keys):
    agg = defaultdict(lambda: {'n': 0, 'outcomes': Counter(),
                               'contact_any': 0, 'contact_wheel': 0})
    for r in rows:
        if r.get('status') == 'precheck_failed':
            continue
        k = tuple(r.get(x) for x in keys)
        a = agg[k]
        a['n'] += 1
        a['outcomes'][r.get('outcome') or 'ERROR'] += 1
        a['contact_any'] += 1 if r.get('contact_any') else 0
        a['contact_wheel'] += 1 if r.get('contact_wheel') else 0
    return agg


def _font(path, size):
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def bar_chart(agg, path, title, note, font_path):
    keys = sorted({(k[0], k[2]) for k in agg}, key=lambda t: (str(t[0]), str(t[1])))
    if not keys:
        return None
    W, H = 1100, 620
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    f_t, f_s, f_l = _font(font_path, 26), _font(font_path, 15), _font(font_path, 14)
    d.text((50, 30), title, font=f_t, fill=FG)
    d.text((50, 68), note, font=f_s, fill=DIM)

    x0, y0, pw, ph = 90, 500, W - 140, 340
    d.line([x0 - 10, y0, x0 + pw, y0], fill=(70, 65, 72))
    d.line([x0 - 10, y0 - ph, x0 - 10, y0], fill=(70, 65, 72))
    for pct in (0, .25, .5, .75, 1.0):
        y = y0 - ph * pct
        d.line([x0 - 10, y, x0 + pw, y], fill=GRID)
        d.text((x0 - 58, y - 9), f'{int(pct*100)}%', font=f_s, fill=DIM)

    bw = pw / len(keys) * 0.55
    for i, k in enumerate(keys):
        # 该 (shape, controller) 在全部姿态/分层上的合并完成率
        num = sum(a['outcomes'].get('completed', 0) for kk, a in agg.items()
                  if kk[0] == k[0] and kk[2] == k[1])
        den = sum(a['n'] for kk, a in agg.items() if kk[0] == k[0] and kk[2] == k[1])
        rate = num / den if den else 0
        cx = x0 + pw * (i + 0.5) / len(keys)
        h = ph * rate
        color = {'box': MINT, 'mesh': GOLD}.get(k[0], VIOLET)
        d.rectangle([cx - bw/2, y0 - h, cx + bw/2, y0], fill=color)
        d.text((cx - 16, y0 - h - 22), f'{rate*100:.0f}%', font=f_s, fill=FG)
        d.text((cx - 10, y0 + 10), str(k[0])[:9], font=f_l, fill=DIM)
        d.text((cx - 10, y0 + 28), str(k[1]), font=f_l, fill=DIM)
        d.text((cx - 12, y0 + 46), f'n={den}', font=f_l, fill=DIM)
    img.save(path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True, help='results.jsonl 的显式路径')
    ap.add_argument('--out', required=True, help='报告输出目录')
    a = ap.parse_args()

    inp = pathlib.Path(a.input)
    if not inp.exists():
        raise SystemExit(f'输入不存在：{inp}')
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'figures').mkdir(exist_ok=True)

    rows, bad = load(inp)
    if not rows:
        raise SystemExit('输入为空，拒绝生成成功报告')

    font_path, has_cjk = find_cjk_font()
    L = LBL(has_cjk)
    cfg_path, env_path = inp.parent / 'config.json', inp.parent / 'environment.json'
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    env = json.loads(env_path.read_text()) if env_path.exists() else {}

    c = counts(rows)
    md = ['# 运行报告\n']
    md.append(f'- 运行目录：`{inp.parent.name}`　suite：`{cfg.get("suite", "?")}`')
    md.append(f'- 输入：`{inp.name}`（记录 {c["records"]} 条，无法解析 {bad} 行）')
    if env:
        md.append(f'- 代码提交：`{str(env.get("code", {}).get("commit"))[:12]}`'
                  f'（未提交修改：{env.get("code", {}).get("uncommitted_changes")}）')
        md.append(f'- 模型提交：`{str(env.get("robot_model", {}).get("commit"))[:12]}`')
        md.append(f'- 版本：`{env.get("packages")}`')
    if not has_cjk:
        md.append('\n> 未找到中文字体，图中标签已降级为英文；正文仍为中文。'
                  '设置 `RLL_FONT=/path/to/font.ttc` 可恢复。')

    md.append('\n## 1. 任务计数\n')
    md.append('| 计划 | 执行 | 预检失败 | 未接触 | 接触(任意机体) | 接触(轮子) |')
    md.append('| --- | --- | --- | --- | --- | --- |')
    md.append(f'| {cfg.get("planned_trials", "?")} | {c["executed"]} | {c["precheck_failed"]} | '
              f'{c["not_contacted"]} | {c["contact_any"]} | {c["contact_wheel"]} |')
    outs = {k: v for k, v in c.items()
            if k in ('completed', 'tipped', 'stuck', 'timeout', 'ERROR')}
    md.append(f'\n结果分布（分母 = 已执行 {c["executed"]}）：`{outs}`\n')

    agg = group(rows, ['shape', 'source_kind', 'controller', 'stance'])
    md.append('## 2. 分形状 × 分考生\n')
    md.append('方块、圆柱、斜坡、生成网格分别统计；三个考生分别统计，不合并成单一比例。\n')
    md.append('| shape | 来源 | 考生 | 姿态 | 执行 | 接触(任意) | 接触(轮) | 完成 | 完成率 | 结果分布 |')
    md.append('| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for k in sorted(agg, key=lambda t: tuple(str(x) for x in t)):
        a2 = agg[k]
        done = a2['outcomes'].get('completed', 0)
        md.append(f'| {k[0]} | {k[1]} | {k[2]} | {k[3]} | {a2["n"]} | {a2["contact_any"]} | '
                  f'{a2["contact_wheel"]} | {done} | {done/a2["n"]*100:.0f}% | '
                  f'{dict(a2["outcomes"])} |')

    if bar_chart(agg, out / 'figures/completion_by_shape_controller.png',
                 L('完成率 · 按形状与考生', 'Completion rate by shape and controller'),
                 L('每根柱合并该形状该考生的全部姿态与分层；n 为执行数',
                   'each bar merges stances/layers; n = executed trials'),
                 font_path):
        md.append('\n![完成率](figures/completion_by_shape_controller.png)\n')

    # ---- 同尺寸配对 ----
    by_h = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get('status') == 'precheck_failed':
            continue
        h = (r.get('dimensions') or {}).get('rel_height')
        if h is None:
            continue
        by_h[(round(h, 2), r.get('controller'), r.get('stance'))][r.get('shape')].append(r)
    pairs = []
    for (h, ctrl, stance), shapes in sorted(by_h.items(), key=lambda kv: tuple(map(str, kv[0]))):
        if 'box' in shapes and 'mesh' in shapes:
            def rate(rs):
                return sum(1 for x in rs if x.get('outcome') == 'completed'), len(rs)
            bd, bn = rate(shapes['box'])
            md_, mn = rate(shapes['mesh'])
            pairs.append({'rel_height': h, 'controller': ctrl, 'stance': stance,
                          'box': f'{bd}/{bn}', 'mesh': f'{md_}/{mn}'})

    md.append('\n## 3. 同尺寸对照（box vs 生成网格）\n')
    if pairs:
        md.append('仅列出同时存在 box 与 mesh 的 (相对高度, 考生, 姿态) 组合。'
                  '格式为「完成数/执行数」。\n')
        md.append('| 相对高度 | 考生 | 姿态 | box | mesh |')
        md.append('| --- | --- | --- | --- | --- |')
        for p in pairs:
            md.append(f'| {p["rel_height"]:.2f} | {p["controller"]} | {p["stance"]} | '
                      f'{p["box"]} | {p["mesh"]} |')
    else:
        md.append('本次输入中没有任何同高度的 box 与 mesh 配对，'
                  '**因此不对形状差异作任何陈述**。')

    md.append('\n## 4. 怎么读这张表\n')
    md.append('- 完成率的分母是**已执行 trial**，其中包含未接触障碍物的场景；'
              '"接触后完成率"需要另取分母，本文未做该条件统计。')
    md.append('- 横向偏移是**确定性网格**，不是随机采样；本表的完成率只描述这张网格，'
              '不能外推为随机月面或现实任务的成功概率。')
    md.append('- 同一资产的多个偏移不是多个独立的形状家族。')
    md.append('- 三个考生是手工控制器：`hold` 锁死站姿只转轮，`step` 执行固定抬腿序列，'
              '`adapt` 用本体感觉在"抬腿/加大力矩"之间二选一。'
              '都不能读作"学会了越障"。')
    md.append('- 障碍物是**静态刚性体**，不滚动、不翻倒；地面刚性，摩擦未标定。')

    md.append('\n## 5. 未做的事\n')
    md.append('- 未做形状家族留出测试，**不能**声称"对未见过物体泛化"。')
    md.append('- 未做训练对照，**不能**声称生成资产对训练有帮助。')
    md.append('- 未独立定义"有效难度"，**不能**声称"同难度下无差异"。')

    (out / 'report.md').write_text('\n'.join(md), encoding='utf-8')
    print(f'wrote {out/"report.md"}  records={len(rows)} executed={c["executed"]} pairs={len(pairs)}')
    if not pairs:
        print('注意：没有同尺寸配对，报告不含形状对比结论')
    return 0


if __name__ == '__main__':
    sys.exit(main())
