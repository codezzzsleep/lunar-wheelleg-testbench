"""把实际记录的轨迹渲染成可播放的页面（播放/暂停/进度/速度）。

数据来自真实运行的 rerun_trajectory.jsonl（EpisodeRunner 逐帧记录 qpos/qvel/action）。
明确边界：这是**基于已记录状态的可视回放**，不是物理原始的渲染视频。

  .venv/bin/python scripts/v7_player.py --traj runs/.../media/report/rerun_trajectory.jsonl \
      --out runs/.../media/report/player.html
"""
import argparse, json, pathlib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--traj', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', default='回放')
    a = ap.parse_args()
    frames = [json.loads(l) for l in pathlib.Path(a.traj).read_text().splitlines() if l.strip()]
    if not frames:
        raise SystemExit('轨迹为空：拒绝生成"假回放"页面')
    slim = [{'i': f.get('i'), 't': f.get('t'),
             'x': round(float(f['qpos'][0]), 5), 'y': round(float(f['qpos'][1]), 5),
             'z': round(float(f['qpos'][2]), 5) if len(f['qpos']) > 2 else 0.0,
             'a': [round(float(v), 4) for v in (f.get('action') or [])]} for f in frames]
    html = f"""<!doctype html><meta charset="utf-8"><title>{a.title}</title>
<style>
body{{background:#0f1116;color:#dfe3ea;font:14px/1.6 sans-serif;margin:20px}}
#stage{{background:#12151c;border:1px solid #232832;border-radius:8px;padding:10px}}
canvas{{background:#0b0d12;border:1px solid #232832;border-radius:6px;width:100%;max-width:900px}}
button{{background:#1c2330;color:#dfe3ea;border:1px solid #2a3342;border-radius:6px;padding:6px 12px;margin-right:8px;cursor:pointer}}
input[type=range]{{width:60%}} .k{{color:#8fd3ff}}
</style>
<div id="stage">
<h2 style="margin:0 0 6px">{a.title}</h2>
<div>帧数 <span class="k" id="nf"></span> · 仿真时间 <span class="k" id="st">0.00</span> s ·
动作 <span class="k" id="act">-</span></div>
<canvas id="cv" width="900" height="260"></canvas>
<div style="margin-top:8px">
  <button id="play">播放</button><button id="pause">暂停</button>
  <input type="range" id="seek" min="0" max="1000" value="0">
  速度 <select id="spd"><option>0.25</option><option selected>0.5</option><option>1</option><option>2</option><option>4</option></select>
</div>
</div>
<script>
const F = {json.dumps(slim, ensure_ascii=False)};
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
document.getElementById('nf').textContent = F.length;
let idx = 0, timer = null;
const xs = F.map(f=>f.x), ys = F.map(f=>f.y);
const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
function mapX(x){{ return 40 + (x - x0) / Math.max(1e-6, x1-x0) * (cv.width-80); }}
function mapY(y){{ return cv.height-30 - (y - y0) / Math.max(1e-6, y1-y0) * (cv.height-70); }}
function draw(){{
  ctx.clearRect(0,0,cv.width,cv.height);
  ctx.strokeStyle='#1c2330'; ctx.lineWidth=1;
  for(let i=0;i<=10;i++){{ const x=40+i*(cv.width-80)/10; ctx.beginPath(); ctx.moveTo(x,10); ctx.lineTo(x,cv.height-30); ctx.stroke(); }}
  ctx.strokeStyle='#2f6df6'; ctx.lineWidth=2; ctx.beginPath();
  F.forEach((f,i)=>{{ const X=mapX(f.x), Y=mapY(f.y); i?ctx.lineTo(X,Y):ctx.moveTo(X,Y); }});
  ctx.stroke();
  const f = F[idx];
  ctx.fillStyle='#ffcc4d'; ctx.beginPath(); ctx.arc(mapX(f.x), mapY(f.y), 6, 0, 6.283); ctx.fill();
  document.getElementById('st').textContent = Number(f.t).toFixed(2);
  document.getElementById('act').textContent = (f.a||[]).map(v=>v.toFixed(2)).join(', ') || '-';
  document.getElementById('seek').value = Math.round(idx/(F.length-1)*1000);
}}
function tick(){{
  const spd = Number(document.getElementById('spd').value);
  idx = Math.min(F.length-1, idx + Math.max(1, Math.round(spd)));
  draw();
  if(idx >= F.length-1){{ stop(); }}
}}
function play(){{ if(timer) return; timer = setInterval(tick, 50); }}
function stop(){{ clearInterval(timer); timer = null; }}
document.getElementById('play').onclick = ()=>{{ if(idx>=F.length-1) idx=0; play(); }};
document.getElementById('pause').onclick = stop;
document.getElementById('seek').oninput = e=>{{ stop(); idx = Math.round(e.target.value/1000*(F.length-1)); draw(); }};
draw();
</script>
<p style="color:#8a93a3;font-size:12px">这是基于已记录状态的<b>可视回放</b>（真实运行的逐帧 qpos），
不是物理原始的渲染视频；不同 seed 不拼成同一条轨迹。</p>
"""
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html)
    print(json.dumps({'out': a.out, 'frames': len(slim), 'duration_s': slim[-1]['t']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
