"""v3 五画面作品页：看见 → 想象 → 试走 → 决定 → 执行与揭晓。

页面只讲 FULL 与 OBS_ONLY（同一状态、同一时刻并排），真值形状只在揭晓处出现；
附录放主审计表与历史方法。所有画面都是保存的 qpos/相机/时间重新渲染的三维结果。

  python scripts/v3_page.py --protocol plans/v3_protocol.json
  python scripts/v3_page.py --serve --port 8093        # 带重仿真入口的本地服务器
"""
import argparse
import base64
import html
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEDIA = ROOT / 'media/v3'
PAGE = MEDIA / 'page'


def jload(p, d=None):
    p = pathlib.Path(p)
    if not p.is_file():
        return d
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


def img_uri(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    b = base64.b64encode(p.read_bytes()).decode()
    ext = p.suffix.lstrip('.').lower()
    mime = 'image/png' if ext == 'png' else f'image/{ext}'
    return f'data:{mime};base64,{b}'


def _rel(p):
    """页面在 media/v3/page/ 下，视频在 media/v3/ 下，所以统一用 ../<name>。"""
    try:
        return '../' + str(pathlib.Path(p).resolve().relative_to(MEDIA.resolve()))
    except Exception:
        return str(p)


def esc(x):
    return html.escape(str(x)) if x is not None else ''


def matrix_table(dec_path):
    rows = []
    p = pathlib.Path(dec_path)
    if p.is_file():
        for line in p.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        return '<p class="muted">没有预演矩阵</p>'
    cands = sorted({r['candidate'] for r in rows})
    actions = ['R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2', 'A0']
    head = ''.join(f'<th>{a}</th>' for a in actions)
    body = []
    for c in cands:
        cells = []
        for a in actions:
            r = next((x for x in rows if x['candidate'] == c and x['action'] == a), None)
            if not r:
                cells.append('<td class="na">—</td>')
            elif not r.get('ok', True):
                cells.append('<td class="err">err</td>')
            elif r.get('success'):
                cells.append(f"<td class='ok'>{r['reason'][:9]}</td>")
            else:
                cells.append(f"<td class='fail'>{r['reason'][:9]}</td>")
        body.append(f'<tr><th>{esc(c)}</th>{"".join(cells)}</tr>')
    return (f'<table class="matrix"><thead><tr><th></th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def build_state_section(state, results):
    sd = ROOT / 'runs/v3/states' / state['state_id']
    st = jload(sd / 'state.json', {})
    scr = jload(ROOT / 'runs/v3/screen' / f"{state['state_id']}.json", {})
    dec = {arm: jload(sd / 'decision' / f'decision_{arm}.json') for arm in ('FULL', 'OBS_ONLY')}
    ex = {arm: jload(sd / 'decision' / f'execution_{arm}.json') for arm in ('FULL', 'OBS_ONLY')}
    obs = sd / 'observation'
    gen = obs / 'gen'
    h = []
    h.append(f'<section class="state" id="{esc(state["state_id"])}">')
    h.append(f'<h2>{esc(state["rock_id"])} · h{state["level"]} · v{state["view"]} '
             f'<span class="muted">H={st.get("height_m", 0):.3f} m · 状态 {esc(state["state_id"])}</span></h2>')
    # 1 看见
    h.append('<div class="screen"><h3>1 看见</h3><div class="row">')
    for p, cap in ((obs / 'rgb.png', '机器人规划视角（唯一公共观测）'),
                   (gen / 'variants' / 'A1.png', '实际生成输入 A1（紧裁剪）'),
                   (gen / 'variants' / 'B1.png', '掩码合成 B1'),
                   (gen / 'variants' / 'C1.png', '带地面上下文 C1')):
        u = img_uri(p)
        if u:
            h.append(f'<figure><img src="{u}" alt="{esc(cap)}"><figcaption>{esc(cap)}</figcaption></figure>')
    h.append('</div>')
    vis = st.get('visible', {})
    h.append(f'<p class="muted">可见量：x_front={vis.get("x_front", 0):.3f} m · '
             f'W_vis={vis.get("W_vis", 0):.3f} m · H_vis={vis.get("H_vis", 0):.3f} m · '
             f'原生目标高度 {st.get("gen", {}).get("native_object_height_px", 0):.0f} px</p>')
    h.append('</div>')
    # 2 想象
    h.append('<div class="screen"><h3>2 想象</h3><div class="row">')
    v = MEDIA / '04_turntable_A1.mp4'
    if v.is_file():
        h.append(f'<figure><video src="{_rel(v)}" controls muted loop></video>'
                 f'<figcaption>候选 A1 转台（真实 Lux3D 输出）</figcaption></figure>')
    v = MEDIA / '05_overlay.mp4'
    if v.is_file():
        h.append(f'<figure><video src="{_rel(v)}" controls muted loop></video>'
                 f'<figcaption>蓝色=共同观测面，橙色=候选背面（半透明）</figcaption></figure>')
    h.append('</div></div>')
    # 3 试走
    h.append('<div class="screen"><h3>3 试走</h3>')
    h.append(matrix_table(sd / 'decision' / 'matrix_FULL.jsonl'))
    h.append('<p class="muted">每格是该候选在该动作上的真实预演结局（同 S0、同土壤、同 30 s）。</p></div>')
    # 4 决定
    h.append('<div class="screen"><h3>4 决定</h3><div class="grid2">')
    for arm, label in (('FULL', 'FULL（观测 + 生成未知区）'), ('OBS_ONLY', 'OBS_ONLY（只删生成未知区）')):
        d = (dec.get(arm) or {}).get('decision') or {}
        votes = d.get('votes') or {}
        h.append(f'<div class="card"><h4>{esc(label)}</h4>'
                 f'<p>选择 <b>{esc(d.get("chosen"))}</b> · 规则 {esc(d.get("rule"))} · '
                 f'过票阈值 {esc(d.get("threshold"))} · 有效候选 {esc(d.get("n_valid"))}'
                 f'（独立几何 {esc(d.get("n_unique_geometries"))}）</p>'
                 f'<p class="muted">票数：{esc(json.dumps(votes, ensure_ascii=False))}</p>'
                 f'<p class="muted">代价：{esc(json.dumps(d.get("mean_cost_s"), ensure_ascii=False))}</p>'
                 f'<p class="muted">原因：{esc(d.get("reason"))}</p></div>')
    h.append('</div></div>')
    # 5 执行与揭晓
    h.append('<div class="screen"><h3>5 执行与揭晓</h3>')
    v = MEDIA / '07_exec_full_vs_obs_only.mp4'
    if v.is_file():
        h.append(f'<video class="wide" src="{_rel(v)}" controls muted loop></video>')
    v = MEDIA / '08_truth_reveal.mp4'
    if v.is_file():
        h.append(f'<video class="wide" src="{_rel(v)}" controls muted loop></video>')
    h.append('<div class="grid2">')
    for arm in ('FULL', 'OBS_ONLY'):
        e = ex.get(arm) or {}
        h.append(f'<div class="card"><h4>{esc(arm)} 执行</h4>'
                 f'<p>动作 <b>{esc(e.get("action"))}</b> · 结局 <b>{esc(e.get("outcome"))}</b>'
                 f'（{esc(e.get("reason"))}）</p>'
                 f'<p class="muted">final_x={esc(e.get("final_x"))} m · '
                 f't_end={esc(e.get("t_end"))} s · 从 S0 起算</p></div>')
    h.append('</div>')
    tp = (scr.get('truth_plan') or {}).get('chosen')
    h.append(f'<p class="muted">筛选记录：真值规划选择 {esc(tp)}，观测规划选择 '
             f'{esc((scr.get("obs_plan") or {}).get("chosen"))}；'
             f'hidden_sensitive={esc(scr.get("hidden_sensitive"))}'
             f'（{esc(scr.get("layer"))}）。</p>')
    h.append('</div></section>')
    return '\n'.join(h)


def build_page(results):
    summ = results['summary']
    states = [s for s in results['states'] if s.get('arms')]
    pairs = summ.get('pairs') or []
    hero = next((p for p in pairs if p['FULL'] == 'pass' and p['OBS_ONLY'] != 'pass'), None)
    boundary = next((p for p in pairs if p['FULL'] != 'pass' and p['OBS_ONLY'] == 'pass'), None) \
        or next((p for p in pairs if p['FULL'] == p['OBS_ONLY']), None)
    picks = []
    # 逐个状态渲染的素材目前只覆盖主角；页面只展示素材完整的状态，
    # 其余状态在附录表里列决策/结局（不拿别人的视频顶替）。
    for p in (hero, boundary):
        if not p:
            continue
        if not (MEDIA / '07_exec_full_vs_obs_only.mp4').is_file():
            continue
        if p['state_id'] not in [x['state_id'] for x in picks]:
            picks.append(next(s for s in states if s['state_id'] == p['state_id']))
    if not picks:
        picks = states[:1]
    parts = []
    parts.append(f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>看见半块石头 — v3 真实扫描岩石 / FULL vs OBS_ONLY</title>
<style>
:root{{--bg:#0a0b0d;--fg:#e8e6e3;--muted:#8b8f96;--ok:#3fb950;--fail:#f85149;--err:#d29922;--card:#14161a}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,"PingFang SC","Microsoft YaHei",sans-serif}}
header{{padding:48px 6vw 24px}} h1{{font-size:34px;margin:0 0 8px}} h2{{font-size:22px;margin:40px 0 8px}}
h3{{font-size:16px;color:#9fd1ff;margin:18px 0 8px;letter-spacing:.06em}} h4{{margin:0 0 6px;font-size:15px}}
.muted{{color:var(--muted);font-size:13px}} .screen{{background:var(--card);border:1px solid #1e2126;border-radius:12px;padding:14px 16px;margin:12px 0}}
.row{{display:flex;gap:12px;flex-wrap:wrap}} figure{{margin:0;flex:1 1 220px;max-width:320px}}
img,video{{width:100%;border-radius:8px;display:block;background:#000}}
figcaption{{font-size:12px;color:var(--muted);margin-top:4px}}
video.wide{{margin:8px 0;max-height:70vh;object-fit:contain}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} .card{{background:#101215;border:1px solid #1e2126;border-radius:10px;padding:10px 12px}}
table.matrix{{border-collapse:collapse;font-size:12px;margin-top:6px}} .matrix th,.matrix td{{border:1px solid #24282e;padding:4px 7px;text-align:center}}
.ok{{color:var(--ok)}} .fail{{color:var(--fail)}} .na{{color:#555}} .err{{color:var(--err)}}
.big{{display:flex;gap:28px;flex-wrap:wrap;margin:18px 0}} .kpi{{background:var(--card);border:1px solid #1e2126;border-radius:12px;padding:14px 18px;min-width:160px}}
.kpi b{{font-size:26px;display:block}} footer{{padding:40px 6vw;color:var(--muted);font-size:13px}}
</style></head><body>
<header><h1>看见半块石头，机器人也要能想到整块</h1>
<p class="muted">真实 CC0 摄影测量扫描岩石 · 仿真中拍摄 · FULL（观测 + Lux3D 隐藏几何）vs OBS_ONLY（同一观测几何，只删生成未知区）</p></header>''')
    parts.append('<div class="big">')
    for label, val in (('真实岩石', summ['n_pool_rocks']), ('采集状态', summ['n_states_captured']),
                       ('隐藏敏感且可通行', summ['n_selected']),
                       ('完成双枪执行', summ['n_executed_states'])):
        parts.append(f'<div class="kpi"><b>{val}</b>{label}</div>')
    parts.append('</div>')
    parts.append('<div class="screen"><h3>主比较口径</h3>'
                 f'<p class="muted">FULL 结局分布 {esc(json.dumps(summ["outcomes"]["FULL"]))}；'
                 f'OBS_ONLY 结局分布 {esc(json.dumps(summ["outcomes"]["OBS_ONLY"]))}；'
                 f'结局相同 {summ["same_outcome"]}，FULL 更好 {summ["FULL_better_than_OBS"]}，'
                 f'OBS_ONLY 更好 {summ["OBS_better_than_FULL"]}；'
                 f'风险低估 {summ["risk_underestimate"]}，过度保守 {summ["over_conservative"]}。</p></div>')
    parts.append('<h2>主角与边界</h2>')
    for st in picks:
        parts.append(build_state_section(st, results))
    parts.append('<h2>附录：主审计表</h2><div class="screen"><table class="matrix"><thead><tr>'
                 '<th>状态</th><th>H</th><th>真值选择</th><th>观测选择</th><th>FULL</th><th>OBS_ONLY</th>'
                 '</tr></thead><tbody>')
    for s in states:
        sc = s.get('screen') or {}
        a = s['arms']
        parts.append(f'<tr><td>{esc(s["state_id"])}</td><td>{s["H"]:.3f}</td>'
                     f'<td>{(sc.get("truth_plan") or {}).get("chosen")}</td>'
                     f'<td>{(sc.get("obs_plan") or {}).get("chosen")}</td>'
                     f'<td>{(a["FULL"].get("execution") or {}).get("outcome")}</td>'
                     f'<td>{(a["OBS_ONLY"].get("execution") or {}).get("outcome")}</td></tr>')
    parts.append('</tbody></table></div>')
    parts.append('<footer>三维画面由保存的 qpos / 相机 / 时间重新渲染（1920×1080 · 30 fps）；'
                 '真值形状只在揭晓处出现，不用真值参考执行冒充本方法。'
                 'Lux3D 过程以真实 task_id / 时间线记录，未做屏幕录制。</footer></body></html>')
    return '\n'.join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--serve', action='store_true')
    ap.add_argument('--port', type=int, default=8093)
    a = ap.parse_args()
    res = jload(ROOT / 'runs/v3/report/v3_results.json')
    if not res:
        raise SystemExit('先跑 scripts/v3_report.py')
    PAGE.mkdir(parents=True, exist_ok=True)
    (PAGE / 'index.html').write_text(build_page(res))
    if not a.serve:
        print(json.dumps({'out': str(PAGE / 'index.html')}, ensure_ascii=False))
        return
    import http.server
    import socketserver
    import threading

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kw):
            super().__init__(*args, directory=str(MEDIA), **kw)

        def log_message(self, *args):
            pass

    with socketserver.TCPServer(('0.0.0.0', a.port), H) as httpd:
        print(f'serving {MEDIA} on :{a.port}', flush=True)
        httpd.serve_forever()


if __name__ == '__main__':
    main()
