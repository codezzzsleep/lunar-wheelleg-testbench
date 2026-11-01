"""五个画面的作品页：看见 → 想象 → 试走 → 决定 → 真走与揭晓。

数据全部来自**同一次运行**（family_compare 的同一状态目录），不拼接不同运行的片段：

  看见：该状态的观测图像与公开可见量
  想象：同一状态下各家族的几何来源与它们各自的选择
  试走：每个家族的预演格数与安全集合
  决定：被选动作、决策 SHA
  真走与揭晓：该家族的真实执行轨迹与独立真值结果

  python scripts/v7_story_page.py --run <family_compare 目录> --out <html>
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(path):
    p = ROOT / path if not pathlib.Path(path).is_absolute() else pathlib.Path(path)
    return json.loads(p.read_text()) if p.is_file() else None


def frames_of(traj_path):
    p = ROOT / traj_path
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if isinstance(r.get('qpos'), list) and r['qpos']:
            out.append({'t': r.get('t'), 'x': round(float(r['qpos'][0]), 4),
                        'y': round(float(r['qpos'][1]), 4),
                        'z': round(float(r['qpos'][2]), 4) if len(r['qpos']) > 2 else 0.0,
                        'a': [round(float(v), 3) for v in (r.get('action') or [])],
                        'phase': r.get('phase')})
    return out


def build(run_dir):
    table = load(pathlib.Path(run_dir) / 'table.json')
    if not table:
        raise SystemExit(f'缺 table.json：{run_dir}')
    state = table['state_hash']
    obs = table.get('observation') or {}
    obs_dir = ROOT / (obs.get('dir') or '')
    vis = table.get('visible') or {}
    rows = []
    for r in table['rows']:
        fam_dir = pathlib.Path(run_dir) / r['family']
        traj = (fam_dir / 'trajectory.jsonl')
        if not traj.is_absolute():
            traj = ROOT / traj
        plan = load(fam_dir / 'plan.json') or {}
        rows.append({'family': r['family'], 'kind': r['kind'], 'chosen': r['chosen'],
                     'outcome': r['outcome'], 'cells': r.get('cells'),
                     'safe_set': r.get('safe_set') or [], 'final_x': r.get('final_x'),
                     'sim_time_s': r.get('sim_time_s'),
                     'has_traj': traj.is_file(),
                     'traj': (str(traj.relative_to(ROOT))
                              if traj.is_file() and traj.is_relative_to(ROOT)
                              else (str(traj) if traj.is_file() else None)),
                     'frames': len(frames_of(traj)) if traj.is_file() else 0,
                     'planner': plan.get('version'),
                     'decision': load(fam_dir / 'decision.json')})
    chosen = next((r for r in rows if r['outcome'] == 'pass'), None) or rows[0]
    traj_frames = frames_of(chosen['traj']) if chosen.get('traj') else []
    return {'table': table, 'rows': rows, 'chosen': chosen, 'frames': traj_frames,
            'state': state, 'obs_dir': str(obs_dir.relative_to(ROOT)) if obs_dir.is_dir() else None,
            'vis': vis}


def html(ctx):
    t = ctx['table']
    rows = ctx['rows']
    vis = ctx['vis']
    obs_dir = ctx['obs_dir']
    img = ''
    if obs_dir and (ROOT / obs_dir / 'rgb.png').is_file():
        import base64
        b = (ROOT / obs_dir / 'rgb.png').read_bytes()
        img = ('data:image/png;base64,' + base64.b64encode(b).decode())[:2_000_000]
    fam_rows = ''.join(
        f"<tr class=\"{'pass' if r['outcome']=='pass' else ('abandon' if r['outcome']=='safe_abandon' else 'fail')}\">"
        f"<td>{r['family']}</td><td>{r['kind']}</td><td>{r['chosen']}</td>"
        f"<td>{r['outcome']}</td><td>{r['cells'] if r['cells'] is not None else '—'}</td>"
        f"<td>{', '.join(r['safe_set']) or '—'}</td>"
        f"<td>{r['final_x'] if r['final_x'] is not None else '—'}</td></tr>" for r in rows)
    frames = ctx['frames']
    data = json.dumps(frames, ensure_ascii=False)
    chosen = ctx['chosen']
    return f"""<!doctype html><meta charset="utf-8"><title>看不见的那一面 · 五画面</title>
<style>
body{{background:#0e1117;color:#e6e9ef;font:15px/1.7 -apple-system,Segoe UI,sans-serif;margin:0}}
header{{padding:22px 28px;border-bottom:1px solid #202633}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8b95a7;font-size:13px}}
section{{padding:22px 28px;border-bottom:1px solid #1a1f2a}}
h2{{font-size:16px;margin:0 0 10px;color:#9fd2ff}}
.num{{display:inline-block;width:22px;height:22px;border-radius:50%;background:#1c2735;
      color:#9fd2ff;text-align:center;line-height:22px;font-size:12px;margin-right:8px}}
table{{border-collapse:collapse;font-size:13px;width:100%;max-width:1000px}}
th,td{{border-bottom:1px solid #1c222d;padding:6px 10px;text-align:left}}
th{{color:#8b95a7;font-weight:500}}
tr.pass td{{color:#7ee0a1}} tr.fail td{{color:#ff9d9d}} tr.abandon td{{color:#c9b26b}}
img{{max-width:640px;border:1px solid #232a36;border-radius:6px}}
canvas{{background:#0a0d13;border:1px solid #232a36;border-radius:6px;width:100%;max-width:760px}}
button{{background:#1b2431;color:#dfe3ea;border:1px solid #2a3342;border-radius:6px;
       padding:6px 12px;margin-right:8px;cursor:pointer}}
.kv{{color:#9aa4b6;font-size:13px}} code{{color:#9fd2ff}}
</style>
<header><h1>看不见的那一面 · 轮腿机器人「先想后走」</h1>
<div class="sub">状态 {ctx['state'][:16]} · 配置 {t['config']} · 土壤 {t['soil']} · seed {t['seed']} ·
预算 {t['budget_s']} s · 同一状态、同一可见量、同一规划器</div></header>

<section><h2><span class="num">1</span>看见</h2>
<div class="kv">x_front {vis.get('x_front')} m · W_vis {vis.get('W_vis')} m · H_vis {vis.get('H_vis')} m ·
可见像素 {vis.get('n_pixels')}</div>
{'<img src="' + img + '" alt="该状态的观测图像">' if img else '<div class="kv">（该状态未保存 rgb.png）</div>'}
<div class="kv">观测包：<code>{obs_dir}</code></div></section>

<section><h2><span class="num">2</span>想象</h2>
<div class="kv">同一观测下，不同假设对「看不见的那一面」给出不同几何：方盒子、镜像、2.5D 高程图（挡未知/补平）、
Lux3D 候选，以及只给参考用的真值几何。</div>
<table><tr><th>家族</th><th>几何来源</th><th>选择</th><th>结局</th><th>预演格</th><th>安全集合</th><th>终点 x</th></tr>
{fam_rows}</table></section>

<section><h2><span class="num">3</span>试走</h2>
<div class="kv">每个建模家族都在同一状态上真实预演（动作 × 土壤），再按最坏情形聚合；
安全集合为空即无法保证通行，只能安全放弃。</div>
<div class="kv">被展示的家族：<b>{chosen['family']}</b> · 预演格 {chosen['cells']} ·
安全集合 {', '.join(chosen['safe_set']) or '—'}</div></section>

<section><h2><span class="num">4</span>决定</h2>
<div class="kv">决策先落盘，再执行。选择 <b>{chosen['chosen']}</b>，
决策文件 SHA 见运行目录 <code>decision.json</code>。</div></section>

<section><h2><span class="num">5</span>真走与揭晓</h2>
<div class="kv">下面是<b>同一运行</b>的真实执行轨迹（不是动画），终点 x={chosen['final_x']}，
结局 {chosen['outcome']}，模拟时长 {chosen['sim_time_s']} s。</div>
<canvas id="cv" width="760" height="220"></canvas>
<div style="margin-top:8px">
<button id="play">播放</button><button id="pause">暂停</button>
<input id="seek" type="range" min="0" max="1000" value="0" style="width:420px">
<span id="st" class="kv">0.00 s</span></div></section>

<script>
const F = {data};
const cv = document.getElementById('cv'), g = cv.getContext('2d');
const st = document.getElementById('st'), seek = document.getElementById('seek');
let t0 = F.length ? F[0].t : 0, t1 = F.length ? F[F.length-1].t : 1, cur = 0, timer = null;
function draw(i) {{
  const f = F[i] || F[0]; if (!f) return;
  g.clearRect(0,0,cv.width,cv.height);
  g.strokeStyle = '#1c2330'; g.beginPath();
  for (let x=0;x<cv.width;x+=40){{g.moveTo(x,0);g.lineTo(x,cv.height);}} g.stroke();
  const X = v => 40 + (v/4.2)*(cv.width-80);
  const Y = v => cv.height-40 - v*80;
  g.fillStyle = '#2b3a4d'; g.fillRect(X(1.75), Y(0.10), 60, 14);
  g.fillStyle = '#9fd2ff'; g.beginPath(); g.arc(X(f.x), Y(f.z), 7, 0, 6.283); g.fill();
  g.fillStyle = '#8b95a7'; g.font = '12px monospace';
  g.fillText('x=' + f.x.toFixed(2) + ' m  t=' + f.t.toFixed(2) + ' s  phase=' + (f.phase||'-'), 40, 20);
}}
function setTime(t) {{
  let i = 0; while (i < F.length-1 && F[i].t < t) i++;
  cur = i; draw(i); st.textContent = F[i].t.toFixed(2) + ' s';
}}
document.getElementById('play').onclick = () => {{
  if (timer) return;
  timer = setInterval(() => {{
    let i = cur + 3; if (i >= F.length) {{ i = F.length-1; clearInterval(timer); timer = null; }}
    cur = i; draw(i); st.textContent = F[i].t.toFixed(2) + ' s';
    seek.value = Math.round(1000 * (F[i].t - t0) / Math.max(1e-6, (t1 - t0)));
  }}, 40);
}};
document.getElementById('pause').onclick = () => {{ clearInterval(timer); timer = null; }};
seek.oninput = (e) => {{
  const t = t0 + (t1 - t0) * (Number(e.target.value) / 1000);
  setTime(t);
}};
draw(0);
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    ctx = build(a.run)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html(ctx), encoding='utf-8')
    print(json.dumps({'out': a.out, 'families': len(ctx['rows']),
                      'frames': len(ctx['frames']), 'chosen': ctx['chosen']['family']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
