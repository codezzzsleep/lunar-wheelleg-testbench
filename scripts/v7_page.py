"""
V7 静态报告页：把批次里的真实记录渲染成可读页面（只读，不触发任何生成）。

    .venv/bin/python scripts/v7_page.py \
        --batch runs/unseen/delivery_v7/v7_20261030 \
        --out runs/unseen/delivery_v7/v7_20261030/media/report/index.html
"""
import argparse
import html
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def j(p, default=None):
    p = pathlib.Path(p)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def tbl(headers, rows, cls=''):
    h = ''.join(f'<th>{html.escape(str(x))}</th>' for x in headers)
    body = ''
    for r in rows:
        cells = ''
        for x in r:
            v = '' if x is None else str(x)
            bad = any(k in v for k in ('✗', 'FAIL', '失败', 'NOT'))
            good = any(k in v for k in ('✓', 'PASS', '通过'))
            cls_td = ' class="bad"' if bad else (' class="good"' if good else '')
            cells += f'<td{cls_td}>{html.escape(v)}</td>'
        body += f'<tr>{cells}</tr>'
    return (f'<table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', default='runs/unseen/delivery_v7/v7_20261030')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    B = ROOT / a.batch
    out = ROOT / (a.out or f'{a.batch}/media/report/index.html')
    man = j(B / 'manifest.json', {}) or {}
    bud = man.get('budget', {})
    tasks = []
    for f in sorted((B / 'generation').glob('task_*.json')):
        d = j(f)
        if d:
            tasks.append(d)

    # 候选
    cand_rows = []
    for f in sorted((B / 'processed').glob('*/process.json')):
        d = j(f) or {}
        fm = d.get('fusion_metrics') or {}
        cg = d.get('collision_geometry') or {}
        ok = '✓ 通过' if d.get('qualified') else '✗ 未通过'
        cand_rows.append([d.get('candidate'), d.get('fusion_pitch_m'),
                          fm.get('mask_iou'), fm.get('vis_pt_p95_mm'),
                          fm.get('freespace_violation'), cg.get('occupancy_iou'), ok])

    # 六方法
    six_rows = []
    six_list = []
    for d in sorted((B / 'evaluation').glob('six_*')):
        sm = j(d / 'summary.json')
        if not sm:
            continue
        six_list.append((d.name, sm))
    if six_list:
        name, sm = six_list[0]
        for m in sm.get('methods', []):
            six_rows.append([m.get('method'), m.get('selected_action'),
                             f"{m.get('success')}/{m.get('n_exec')}"])

    # 月壤对照
    soil_modes = []
    for mode in ('low_traction', 'high_drag'):
        sm = j(B / 'evaluation' / f'six_R03_{mode}' / 'summary.json')
        if sm:
            soil_modes.append((mode, {m.get('method'): (m.get('selected_action'), m.get('success'), m.get('n_exec'))
                                      for m in sm.get('methods', [])}))
    soil_tbl = ''
    if soil_modes:
        base = {m.get('method'): (m.get('selected_action'), m.get('success'), m.get('n_exec'))
                for m in (six_list[0][1].get('methods', []) if six_list else [])}
        rows = []
        for method in base:
            r = [method, f"{base[method][0]} {base[method][1]}/{base[method][2]}"]
            for mode, mp in soil_modes:
                v = mp.get(method)
                r.append(f"{v[0]} {v[1]}/{v[2]}" if v else '—')
            rows.append(r)
        soil_tbl = tbl(['方法', 'rigid'] + [m for m, _ in soil_modes], rows)

    # 生成任务
    task_rows = [[t.get('task_id'), t.get('object'), t.get('mode'), t.get('sample_id'),
                  (t.get('glb_sha') or '—')[:12], t.get('estimate_upper')] for t in tasks]

    # freespace 诊断
    diag_rows = []
    for f in sorted((B / 'diag').glob('fs_*')):
        d = j(f / 'manifest.json')
        if not d:
            continue
        m = d.get('metrics') or {}
        try:
            cfg = j(f / 'effective_config.json', {}) or {}
            pitch = cfg.get('pitch_m')
        except Exception:
            pitch = None
        diag_rows.append([d.get('parent_id'), (f"{pitch*1000:.1f} mm" if pitch else '—'),
                          m.get('mask_iou'), m.get('vis_pt_p95_mm'),
                          m.get('freespace_violation'),
                          '面数超限' if m.get('error') else '已测'])

    # 主动观察
    drive = j(B / 'observation/drive_R01/drive_observe.json', {}) or {}
    screen = j(B / 'observation/second_view_screen.json', {}) or {}
    drive_rows = []
    for r in (drive.get('runs') or [])[:3]:
        drive_rows.append([r.get('seed'), r.get('move_seconds'), r.get('cam_baseline_m'),
                          r.get('bearing_change_deg'), r.get('view1_mask_px'),
                          r.get('view2_mask_px'), r.get('usable')])
    screen_rows = []
    for r in (screen.get('rows') or []):
        o1 = r.get('obs1_front') or {}; o2 = r.get('obs2_driven') or {}
        screen_rows.append([r.get('candidate'), o1.get('mask_iou'), o1.get('freespace_violation'),
                            o2.get('mask_iou'), o2.get('freespace_violation'),
                            '保留' if r.get('kept_by_second_view') else '不保留'])
    status = man.get('status', {})
    parts = [f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>V7 · 看不见的那一面</title>
<style>
:root{{color-scheme:dark}}
body{{background:#0f1116;color:#dfe3ea;font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:26px 0 8px;color:#8fd3ff}}
.meta{{color:#8a93a3;font-size:12px;margin-bottom:16px}}
table{{border-collapse:collapse;margin:8px 0 18px;font-size:13px}}
th,td{{border:1px solid #2a2f3a;padding:5px 9px;text-align:left}}
th{{background:#171b23;color:#a9b3c4;font-weight:600}}
td.good{{color:#7ee787}} td.bad{{color:#ff8a80}}
.card{{border:1px solid #232832;border-radius:8px;padding:14px 16px;background:#12151c;margin:10px 0}}
code{{background:#171b23;padding:1px 5px;border-radius:4px}}
.note{{color:#8a93a3;font-size:12px}}
</style></head><body>
<h1>看不见的那一面 · V7 批次</h1>
<div class="meta">批次 <code>{html.escape(man.get('batch_id',''))}</code> ·
基线 <code>{html.escape(str(man.get('review_baseline','')))}</code> ·
协议 <code>{html.escape(str(man.get('protocol',{}).get('path','')))}</code></div>
<div class="card"><b>四类状态</b>：
execution <code>{html.escape(str(status.get('execution_status','')))}</code> ·
evidence <code>{html.escape(str(status.get('evidence_status','')))}</code> ·
capability <code>{html.escape(str(status.get('capability_status','')))}</code> ·
benefit <code>{html.escape(str(status.get('benefit_status','')))}</code></div>

<h2>1. 预算与生成任务</h2>
<div class="card">本批新增授权 <b>{bud.get('tasks_created') and man.get('new_create_authorized_credits')}</b> 积分；
已建任务 <b>{len(tasks)}</b>，占用上界 <b>{bud.get('held_credits_upper')}</b>；实际扣费 <code>unknown</code>。
历史账本 <code>runs/unseen/generation/ledger.jsonl</code> 只读保留。</div>
""" + tbl(['任务 ID', '对象', '模式', '采样', 'GLB SHA', '上界'], task_rows) + """

<h2>2. 生成候选与三门槛（10 个任务，8 个可测）</h2>
<div class="note">门槛：可见 IoU ≥ 0.90、可见点 P95 ≤ 5 mm、freespace ≤ 0.05、碰撞 IoU ≥ 0.95。</div>
""" + tbl(['候选', '网格 m', 'IoU', 'P95 mm', 'freespace', '碰撞 IoU', '资格'], cand_rows) + """

<h2>2b. 主动观察闭环（真实行驶 → 第二视角 → 筛候选）</h2>
""" + (tbl(['seed', '行驶 s', '相机基线 m', '视线角 °', '首视角 px', '第二视角 px', '可用'], drive_rows) if drive_rows else '') + """
<div class="note">停稳判据：v_lin ≤0.05、v_ang ≤0.1、倾角 ≤8°、保持 0.4 s。第二视角来自真实 qpos/qvel 恢复后取景。</div>
""" + (tbl(['候选', '首视角 IoU', '首视角 freespace', '第二视角 IoU', '第二视角 freespace', '第二视角结论'], screen_rows) if screen_rows else '') + """
<div class="note">固定候选几何与位姿，只用第二相机评价，未重新配准。</div>

<h2>3. 六方法正式比较（R03，rigid）</h2>
""" + tbl(['方法', '选择动作', '成功'], six_rows) + """
<div class="note">六个方法全部成功，因此成功数不能证明生成假设有用；只有动作选择（D1 vs R1）有区分。</div>

<h2>3b. 月壤 rigid / soil 对照（R03）</h2>
""" + soil_tbl + """
<div class="note">月壤改变了盒先验（退化为 A0）与真值上限（D1→R1）的选择；H5 动作不变且仍成功，
但在低牵引/高阻力下与真值上限不一致。</div>

<h2>4. freespace 侵入定位（第一轮）</h2>
""" + (tbl(['变体', '网格', 'IoU', 'P95 mm', 'freespace', '状态'], diag_rows) if diag_rows else '<div class="note">诊断结果未回传</div>') + """
<div class="note">壳体偏移已排除；收窄 band 会恶化；细网格对照被 MuJoCo 20 万面上限挡住，根因<b>尚未定位</b>。</div>

<h2>5. 限制</h2>
<ul class="note">
<li>可见面由观测约束构造，不等于 Lux3D 原始模型精度。</li>
<li>R01 是开发诊断对象，不计作留出对象；R02/R03/R04 才是新增独立对象。</li>
<li>四个候选来自同一对象的多次采样，属同源变体，不是独立物体。</li>
<li>执行是独立仿真，不是真实机器人；月壤只接入阻力/牵引限制模型，无整机几何下陷。</li>
</ul>
</body></html>"""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(parts))
    print(json.dumps({'page': str(out.relative_to(ROOT)), 'n_candidates': len(cand_rows),
                      'n_tasks': len(tasks), 'n_six': len(six_rows),
                      'n_diag': len(diag_rows)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
