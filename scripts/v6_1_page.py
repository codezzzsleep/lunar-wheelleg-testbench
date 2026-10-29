"""
V6.1：批次只读报告页（静态，自包含，不需要服务器）。

从批次产物直接生成 media/report/index.html：
  · 批次身份（manifest 的 SHA、配置 SHA、new_create）
  · 资产资格表（可见面 IoU / P95 / freespace / 是否 strict / 是否规划合格）
  · 碰撞路线表（CoACD vs box，含双向距离）
  · 误差分层 S0–S4
  · 诊断运行（决策 / 规划 / 验证 / 合同结果 / 接触来源）
  · 明确的限制与状态

  .venv/bin/python scripts/v6_1_page.py --batch runs/unseen/delivery_v6_1/v6_1_20261029
"""
import argparse
import html
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def jl(p, default=None):
    p = pathlib.Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text())


def table(headers, rows, note=''):
    h = ''.join(f'<th>{html.escape(str(x))}</th>' for x in headers)
    body = ''
    for r in rows:
        body += '<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in r) + '</tr>'
    return (f'<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>'
            + (f'<p class="note">{note}</p>' if note else ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', default='runs/unseen/delivery_v6_1/v6_1_20261029')
    a = ap.parse_args()
    B = pathlib.Path(a.batch)
    man = jl(B / 'manifest.json', {})
    cfg = jl(ROOT / 'configs/unseen_v6_1_fusion.json', {})

    # 资产资格
    assets = []
    for d in sorted((B / 'fusion').glob('*')):
        m = jl(d / 'manifest.json')
        if not m:
            continue
        mt = m.get('metrics') or {}
        iou = mt.get('mask_iou'); p95 = mt.get('vis_pt_p95_mm'); free = mt.get('freespace_violation')
        ok = (iou is not None and p95 is not None and free is not None
              and iou >= 0.90 and p95 <= 5.0 and free <= 0.05)
        assets.append([d.name, m.get('parent_id'), f'{iou}', f'{p95}', f'{free}',
                       'Y' if (m.get('strict') or {}).get('pass') else 'N',
                       'Y' if ok else 'N', f"{m.get('volume_m3')}"])
    assets.sort(key=lambda r: (r[6] != 'Y', r[0]))

    # 碰撞路线
    coll = []
    q = B / 'collision'
    if (q / 'summary.json').exists():
        s = jl(q / 'summary.json')
        for r in s.get('rows', []):
            coll.append([r.get('route'), r.get('repr'), r.get('n'), r.get('iou'),
                         r.get('s2c_p95'), r.get('c2s_p95'), r.get('verdict')])
    for f in sorted(list(q.glob('*_metrics.json')) + list(q.glob('*/metrics.json'))):
        d = jl(f)
        if not d or d.get('representation') != 'box_union':
            continue
        if any(c[0] == d.get('label') for c in coll):
            continue
        g = d['geometry']
        coll.append([d.get('label'), 'box_union', d.get('n_boxes'), g.get('occupancy_iou'),
                     g['source_to_collision_mm']['p95'], g['collision_to_source_mm']['p95'],
                     d.get('verdict')])

    # 分层
    layers = []
    lp = B / 'layers' / 'F0' / 'layers.json'
    if lp.exists():
        for r in jl(lp).get('rows', []):
            hm = r.get('heatmap') or {}
            layers.append([r.get('step'), r.get('mask_iou'), r.get('vis_pt_p95_mm'),
                           r.get('freespace_violation'),
                           f"{r.get('freespace_n_px')}/{r.get('freespace_denom_px')}",
                           (hm.get('resid_pct_mm') or ['', '', '', '', ''])[2]])

    # 诊断运行
    runs = []
    for d in sorted((B / 'evaluation').glob('*')):
        sm = jl(d / 'summary.json')
        if not sm:
            continue
        ct = jl(d / 'contract.json', {})
        for m in sm.get('methods', []):
            runs.append([d.name, m.get('method'), m.get('selected_action'),
                         f"{m.get('success')}/{m.get('n_exec')}",
                         f"{m.get('validation_success')}/{m.get('validation_n')}",
                         m.get('mean_cost'), m.get('n_hypotheses'),
                         f"{ct.get('n_pass')}/{ct.get('n_checks')}" if ct else '—'])

    # 接触来源
    contacts = []
    for f in sorted((B / 'media').glob('contact_source_*.json')):
        d = jl(f)
        if not d:
            continue
        contacts.append([d.get('option'), d.get('seed'), d.get('n_contacts_all'),
                         d.get('n_contact_points'),
                         (d.get('counts') or {}).get('observed_face'),
                         (d.get('counts') or {}).get('parent_hidden'),
                         (d.get('counts') or {}).get('collision_added')])

    st = man.get('status') or {}
    css = """
    body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;color:#111;background:#fafafa}
    h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-left:4px solid #444;padding-left:8px}
    table{border-collapse:collapse;margin:8px 0 4px;background:#fff;font-size:13px}
    th,td{border:1px solid #ddd;padding:4px 8px;text-align:left}
    th{background:#f0f0f0}
    .note{color:#666;font-size:12px;margin:2px 0 12px}
    .warn{background:#fff4e5;border:1px solid #e0a458;padding:10px;border-radius:4px;font-size:13px}
    code{background:#eee;padding:1px 4px;border-radius:3px}
    """
    H = []
    H.append('<!doctype html><html lang="zh"><head><meta charset="utf-8">'
             '<title>V6.1 批次报告</title>'
             f'<style>{css}</style></head><body>')
    H.append('<h1>看不见的那一面 · V6.1 批次报告</h1>')
    H.append('<div class="warn"><b>状态</b>：'
             f"execution {st.get('execution_status')} / evidence {st.get('evidence_status')} / "
             f"capability {st.get('capability_status')} / benefit {st.get('benefit_status')}。"
             '本页只读已落盘产物；DIAG 运行是诊断，不是收益结论；'
             '可见面未过 strict 的资产不得进入正式规划。</div>')
    H.append('<h2>批次身份</h2>')
    H.append(table(['项', '值'], [
        ['batch_id', man.get('batch_id')],
        ['new_create', man.get('new_create')],
        ['review_baseline', man.get('review_baseline')],
        ['融合配置', f"pitch={cfg.get('pitch_m')} m, band={cfg.get('band_m')} m, "
                     f"eps={cfg.get('free_epsilon_m')} m, shell_offset={cfg.get('shell_offset_voxels')} voxel, "
                     f"mask_dilate={cfg.get('mask_dilate_px')} px"],
    ]))
    H.append('<h2>资产资格（三项全过才算规划合格）</h2>')
    H.append(table(['资产', '父候选', '可见面 IoU', '可见点 P95 (mm)', 'freespace',
                    'strict', '规划合格', '体积 (m³)'], assets,
                   '门窗：IoU ≥ 0.90、可见点 P95 ≤ 5 mm、freespace ≤ 0.05；体积不放宽任何门槛。'))
    H.append('<h2>碰撞表示（同一评价器）</h2>')
    H.append(table(['路线', '表示', '数量', '占据 IoU', '源→碰撞 P95 (mm)',
                    '碰撞→源 P95 (mm)', '判定'], coll,
                   'box 只在暴露面采样；CoACD 是凸分解，凹结构会被填平。'))
    H.append('<h2>误差首次出现层（F0 已知答案）</h2>')
    H.append(table(['步骤', 'IoU', '可见点 P95 (mm)', 'freespace', '违例/分母',
                    '有符号残差中位 (mm)'], layers,
                   'S0/S1 为零说明观测与评价自洽；误差首次出现在 S2（占据化 + 提取）。'))
    H.append('<h2>诊断运行（决策先落盘）</h2>')
    H.append(table(['目录', '方法', '选中动作', '规划', '验证', '平均代价', '假设数', '合同'],
                   runs, '合同列为完整性检查通过数；DIAG 目录名表明这是诊断运行。'))
    H.append('<h2>接触来源</h2>')
    H.append(table(['动作', 'seed', '总接触', '与障碍接触', '观测面', '父隐藏面', '碰撞新增区'],
                   contacts,
                   '只有与障碍 body 的接触被统计；地面接触不计入。'))
    H.append('<h2>限制</h2><ul>'
             '<li>可见面是构造出来的，不是 Lux3D 原始精度；H5-F 的可见面由观测约束得到。</li>'
             '<li>R01 是开发案例；四个父候选是同源变体，不等于四个独立物体。</li>'
             '<li>R03 对此任务不具区分度（盲走也 3/3）。</li>'
             '<li>执行是独立仿真，不是真机；整机月壤几何下陷未实现。</li>'
             '<li>box IoU 受源实体表面/体积比支配：紧凑源 0.99，薄片源 0.94。</li>'
             '</ul>')
    H.append('</body></html>')
    out = B / 'media' / 'report' / 'index.html'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(H))
    print(json.dumps({'page': str(out), 'n_assets': len(assets), 'n_collision': len(coll),
                      'n_layers': len(layers), 'n_runs': len(runs),
                      'n_contacts': len(contacts)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
