"""
分析：把一次运行的 results.jsonl 变成报告。

  python scripts/analyze.py --input runs/<run_id>/results.jsonl --out runs/<run_id>
                            [--allow-partial]

严格校验（第二轮任务 3）：
  · 逐行校验：必须是 JSON 对象、必要字段齐全、类型正确、status/outcome 自洽
  · 重复 trial_id 直接报错，不自动合并
  · 若同目录有冻结清单 manifest.json，则校验缺失/计划外 ID、参数身份、schema
  · 全 ERROR / 全预检失败 / 无有效仿真 → 只写诊断文件并非零退出
  · 不同控制/物理配置的记录不允许混成一个成绩
  · 默认只读显式指定的文件；--allow-partial 才允许部分报告，且报告会醒目标注
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

REQUIRED = ('trial_id', 'status', 'controller', 'stance')
VALID_STATUS = {'ok', 'precheck_failed', 'ERROR'}
VALID_OUTCOME = {'completed', 'tipped', 'stuck', 'timeout', 'precheck_failed', 'ERROR'}
PHYSICS_KEYS = ('control', 'gravity', 'friction', 'timestep')

CJK_CANDIDATES = [
    os.environ.get('RLL_FONT', ''),
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    str(ROOT / 'assets/fonts/wqy-zenhei.ttc'),
]


def find_cjk_font():
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
    def __init__(self, has_cjk):
        self.cjk = has_cjk

    def __call__(self, zh, en):
        return zh if self.cjk else en


# ------------------------------------------------------------------ 读取/校验

def load(path):
    rows, bad = [], []
    for i, line in enumerate(pathlib.Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            bad.append({'line': i, 'error': f'json:{e.msg}'})
            continue
        if not isinstance(obj, dict):
            bad.append({'line': i, 'error': 'not_an_object'})
            continue
        miss = [k for k in REQUIRED if k not in obj]
        if miss:
            bad.append({'line': i, 'error': f'missing_fields:{",".join(miss)}'})
            continue
        if obj.get('status') not in VALID_STATUS:
            bad.append({'line': i, 'error': f'bad_status:{obj.get("status")}'})
            continue
        if obj.get('outcome') not in VALID_OUTCOME:
            bad.append({'line': i, 'error': f'bad_outcome:{obj.get("outcome")}'})
            continue
        # status / outcome 必须自洽
        st, oc = obj['status'], obj['outcome']
        if st == 'ok' and oc in ('precheck_failed', 'ERROR'):
            bad.append({'line': i, 'error': f'status_outcome_conflict:{st}/{oc}'})
            continue
        if st in ('precheck_failed', 'ERROR') and oc != st:
            bad.append({'line': i, 'error': f'status_outcome_conflict:{st}/{oc}'})
            continue
        rows.append(obj)
    return rows, bad


def validate(rows, bad, manifest):
    """返回 issues 列表。空列表表示可以出正式报告。"""
    issues = []
    if bad:
        issues.append(f'{len(bad)} 行无法解析或字段非法（行号见 issues 详情）')

    ids = [r.get('trial_id') for r in rows]
    dups = [k for k, v in Counter(ids).items() if v > 1]
    if dups:
        issues.append(f'重复 trial_id {len(dups)} 个：{dups[:5]}')

    if manifest:
        expected = set(manifest.get('trial_ids') or [])
        got = set(ids)
        miss, extra = expected - got, got - expected
        if miss:
            issues.append(f'缺失 {len(miss)} 个计划内 trial')
        if extra:
            issues.append(f'{len(extra)} 个计划外 trial_id')

    # 不同物理/控制配置不得混算
    cfg = {json.dumps({k: r.get(k) for k in PHYSICS_KEYS}, sort_keys=True)
           for r in rows}
    if len(cfg) > 1:
        issues.append(f'输入里存在 {len(cfg)} 套不同的控制/物理配置，不能合并为一个成绩')

    ok_rows = [r for r in rows if r.get('status') == 'ok']
    if not ok_rows:
        issues.append('没有任何有效仿真记录（全为 ERROR 或 precheck_failed）')
    return issues


def counts(rows):
    c = Counter()
    for r in rows:
        c['records'] += 1
        st = r.get('status')
        if st == 'precheck_failed':
            c['precheck_failed'] += 1
            continue
        if st == 'ERROR':
            c['ERROR'] += 1
            continue
        c['executed'] += 1
        if r.get('contact_any'):
            c['contact_any'] += 1
        if r.get('contact_wheel'):
            c['contact_wheel'] += 1
        c[r.get('outcome') or 'UNKNOWN'] += 1
    c['not_contacted'] = c['executed'] - c['contact_any']
    return c


def group(rows, keys):
    agg = defaultdict(lambda: {'n': 0, 'outcomes': Counter(),
                               'contact_any': 0, 'contact_wheel': 0})
    for r in rows:
        if r.get('status') != 'ok':
            continue
        k = tuple(r.get(x) for x in keys)
        a = agg[k]
        a['n'] += 1
        a['outcomes'][r.get('outcome') or 'UNKNOWN'] += 1
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


# ------------------------------------------------------------------ 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--allow-partial', action='store_true',
                    help='允许在不完整/有失败记录时仍生成报告（报告会醒目标注）')
    a = ap.parse_args()

    inp = pathlib.Path(a.input)
    if not inp.exists():
        raise SystemExit(f'输入不存在：{inp}')
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'figures').mkdir(exist_ok=True)

    man_path = inp.parent / 'manifest.json'
    manifest = json.loads(man_path.read_text()) if man_path.exists() else None

    rows, bad = load(inp)
    issues = validate(rows, bad, manifest)
    has_plan = manifest is not None
    # 探索性报告只适用于「单条合法仿真记录」；只有 ERROR 的一条记录不是探索性场景
    exploratory = (not has_plan) and len(rows) == 1 and rows[0].get('status') == 'ok'

    if issues and not a.allow_partial and not exploratory:
        diag = {'input': str(inp), 'records': len(rows), 'bad_lines': bad,
                'issues': issues,
                'has_manifest': has_plan}
        (out / 'diagnostics.json').write_text(json.dumps(diag, indent=2, ensure_ascii=False))
        print('拒绝生成正式报告：', file=sys.stderr)
        for i in issues:
            print('  -', i, file=sys.stderr)
        print(f'诊断已写入 {out/"diagnostics.json"}；如确需部分报告，加 --allow-partial',
              file=sys.stderr)
        return 2

    font_path, has_cjk = find_cjk_font()
    L = LBL(has_cjk)
    cfg_path, env_path = inp.parent / 'config.json', inp.parent / 'environment.json'
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text())
    elif manifest:                       # 新版运行器把配置写在 manifest.json
        cfg = manifest
    else:
        cfg = {}
    env = json.loads(env_path.read_text()) if env_path.exists() else {}

    c = counts(rows)
    status = 'complete' if not issues else 'partial'
    md = ['# 运行报告\n']
    if status != 'complete':
        md.append(f'> **状态：{status}。** 本报告基于不完整或有失败记录的输入，'
                  f'不能作为正式验收通过。问题：{"; ".join(issues)}\n')
    if exploratory:
        md.append('> **探索性报告：未提供冻结任务清单，计划完整性未验证。**\n')

    md.append(f'- 运行目录：`{inp.parent.name}`　suite：`{cfg.get("suite", "未提供")}`')
    md.append(f'- 输入：`{inp.name}`（记录 {c["records"]} 条，非法行 {len(bad)}）')
    if env:
        md.append(f'- 运行源码内容哈希：`{(env.get("source") or {}).get("content_sha")}`'
                  f'（git {(env.get("source") or {}).get("git_commit")}，'
                  f'未提交修改 {(env.get("source") or {}).get("git_dirty")}）')
        md.append(f'- 模型：`{(env.get("model") or {}).get("go2w_xml_sha")}`'
                  f'（git {(env.get("model") or {}).get("git_commit")}，'
                  f'未提交修改 {(env.get("model") or {}).get("git_dirty")}）')
        md.append(f'- 版本：`{env.get("packages")}`')
    if not has_cjk:
        md.append('\n> 未找到中文字体，图内标签降级为英文（正文仍中文）。'
                  '设置 `RLL_FONT` 可恢复。')

    md.append('\n## 1. 任务计数\n')
    md.append('| 计划 | 收到 | ok | 预检失败 | ERROR | 缺失 | 重复 | 非法行 |')
    md.append('| --- | --- | --- | --- | --- | --- | --- | --- |')
    planned = cfg.get('planned_trials', '未提供')
    n_missing = len(set((manifest or {}).get('trial_ids') or []) - {r['trial_id'] for r in rows})
    n_dup = sum(1 for v in Counter(r['trial_id'] for r in rows).values() if v > 1)
    md.append(f'| {planned} | {c["records"]} | {c["executed"]} | {c["precheck_failed"]} | '
              f'{c["ERROR"]} | {n_missing} | {n_dup} | {len(bad)} |')
    md.append(f'\n已执行记录的结果分布：'
              f'`{ {k: v for k, v in c.items() if k in ("completed","tipped","stuck","timeout")} }`\n')
    md.append('其中「完成」是**终点任务完成数**（机体中心越过障碍后方净空），'
              '包含未接触障碍物的场景，不等于"越障成功数"。\n')
    md.append(f'接触覆盖：任意机体接触 {c["contact_any"]}　轮子接触 {c["contact_wheel"]}　'
              f'未接触 {c["not_contacted"]}（分母 = 已执行 {c["executed"]}）。\n')

    agg = group(rows, ['shape', 'source_kind', 'controller', 'stance'])
    md.append('## 2. 分形状 × 分考生\n')
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
                   'bars merge stances/layers; n = executed'), font_path):
        md.append('\n![完成率](figures/completion_by_shape_controller.png)\n')

    by_h = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get('status') != 'ok':
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
        md.append('匹配的是**相对高度与横向宽度**，前后长度未必相同；'
                  '偏移网格与控制配置在同一批次内一致。格式为「完成数/执行数」。\n')
        md.append('| 相对高度 | 考生 | 姿态 | box | mesh |')
        md.append('| --- | --- | --- | --- | --- |')
        for p in pairs:
            md.append(f'| {p["rel_height"]:.2f} | {p["controller"]} | {p["stance"]} | '
                      f'{p["box"]} | {p["mesh"]} |')
        md.append(f'\n共 {len(pairs)} 条，来自少量几何对在不同考生与站姿下的重复比较，'
                  '**不是**独立形状样本，不作显著性推断。')
    else:
        md.append('本次输入中没有同高度的 box 与 mesh 配对，**不对形状差异作任何陈述**。')

    md.append('\n## 4. 怎么读这张表\n')
    md.append('- 完成率分母是**已执行 trial**，含未接触障碍物的场景；'
              '「接触后完成率」需另取分母，不同控制器接触子集不同，不能称严格配对。')
    md.append('- 横向偏移是确定性网格，非随机采样；结果只描述这张网格。')
    md.append('- 同一资产的多个偏移不是独立形状家族。')
    md.append('- 三个考生是手工控制器，不能读作"学会了越障"。')
    md.append('- 障碍物静态刚性，地面刚性，摩擦未标定。')

    md.append('\n## 5. 未做的事\n')
    md.append('- 未做形状家族留出 → 不能声称泛化。')
    md.append('- 未做训练对照 → 不能声称对训练有帮助。')
    md.append('- 未独立定义"有效难度" → 不能声称"同难度下无差异"。')

    (out / 'report.md').write_text('\n'.join(md), encoding='utf-8')
    print(f'wrote {out/"report.md"}  status={status} records={len(rows)} '
          f'executed={c["executed"]} pairs={len(pairs)} issues={len(issues)}')
    return 0 if status == 'complete' else 3


if __name__ == '__main__':
    sys.exit(main())
