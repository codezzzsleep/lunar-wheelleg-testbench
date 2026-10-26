"""
月面上岗考场 · 本地可操作入口。

  .venv/bin/python scripts/app.py --port 8080
  # 打开 http://127.0.0.1:8080

三个操作区：
  1. 出题：选任务 M/K、资产、障碍高度、初始横向偏差；构建真实物理场景并显示解析结果
  2. 考核：选策略（共享底座零残差 / 固定原语 / 学习策略），同一场景同一初态跑真实仿真
  3. 复盘：本次回放的终态、通行方式、首次接触、失败阶段，并给出下一道练习题建议

设计约束（任务书第十节）：
  · 缓存资产组装、运行考核、查看历史训练是不同操作，标签分开；
  · 生成新资产需要本地拥有者显式发起，页面默认不触发任何付费请求；
  · 没有 checkpoint 或 worker 失败时明确报错，不显示虚假的全绿；
  · 离线可用：不依赖 API key。
"""
import argparse
import hashlib
import json
import pathlib
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import ppo                      # noqa: E402
import terrain                  # noqa: E402
import wheelleg_env             # noqa: E402

ASSETS = ROOT / 'assets/processed'
CHECKPOINTS = {}                # label -> path


def discover_checkpoints():
    out = {}
    for base in ('runs/v4M', 'runs/skill_v3', 'runs/skill_v2'):
        d = ROOT / base
        if not d.exists():
            continue
        for sub in sorted(d.iterdir()):
            ck = sub / 'checkpoints' / 'final.npz'
            if ck.exists():
                out[f'{base.split("/")[-1]}/{sub.name}'] = str(ck.relative_to(ROOT))
    return out


def asset_list():
    names = []
    for d in sorted(ASSETS.iterdir()):
        m = d / 'manifest.json'
        if not m.exists():
            continue
        j = json.loads(m.read_text())
        names.append({'name': d.name, 'height_m': j.get('height_m'),
                      'width_y_m': j.get('width_y_m'),
                      'parts': j.get('coacd_parts'),
                      'source': j.get('source_kind')})
    return names


def build_spec(req):
    task = str(req.get('task', 'M')).upper()
    asset = req['asset']
    h = float(req.get('height_m') or 0.085)
    lat0 = float(req.get('init_lateral_m') or 0.20)
    seed = int(req.get('seed') or 0)
    y = float(req.get('obstacle_y') or 0.0)
    spec = terrain.make_spec(
        kind='flat', seed=seed,
        objects=[{'asset': asset, 'x': 1.8, 'y': y, 'yaw_deg': 0.0,
                  'target_height_m': h}],
        goal_x=3.0, name=f'ui_{task}_{asset}')
    spec['split'] = 'ui'
    spec['family'] = asset
    spec['channel'] = {'center_y': 0.0, 'half_width': 0.42}
    spec['init_perturbation'] = {'lateral_m': lat0, 'yaw_rad': 0.08}
    spec['skill_cfg'] = {'task': task, 'require_contact': task == 'K',
                         'settle_seconds': 1.0, 'pass_clearance': 0.10}
    return spec


def simple_primitive(env, obs):
    """固定原语：受阻且未接触时抬前腿+伸后腿；其余保持零残差。"""
    a = np.zeros(wheelleg_env.ACT_DIM)
    vx = float(env.data.qvel[0])
    if vx < 0.35:
        a[0], a[1], a[2] = 0.8, -0.8, -0.3   # 前腿抬、后腿伸、降速
    return a


def run_episode(spec, policy, seed, max_seconds=12.0):
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=max_seconds,
                                   v_ref=1.0, tip_deg=60.0)
    obs, _ = env.reset(seed=seed)
    params = None
    if policy not in ('zero', 'primitive'):
        p = CHECKPOINTS.get(policy)
        if not p:
            raise ValueError(f'找不到策略 {policy}')
        params = dict(np.load(ROOT / p))
    frames, info, trace = [], {}, []
    t0 = 0
    done = False
    while not done:
        if policy == 'zero':
            a = np.zeros(wheelleg_env.ACT_DIM)
        elif policy == 'primitive':
            a = simple_primitive(env, obs)
        else:
            a = ppo.deterministic_action(params, obs)
        obs, r, te, tr, info = env.step(a)
        done = te or tr
        t0 += 1
        if t0 % 10 == 0:
            trace.append([round(float(env.data.qpos[0]), 2),
                          round(float(env.data.qpos[1]), 2),
                          round(float(env.data.qpos[2]), 2)])
    info['trace'] = trace
    info['policy'] = policy
    info['seed'] = seed
    return info


def failure_hint(info):
    """失败阶段 → 下一道练习题建议（规则，人工可复核）。"""
    r = info.get('reason')
    if r == 'success':
        return {'stage': '完成', 'advice': '可提高障碍高度或加入坡面继续练'}
    if r == 'out_of_bounds':
        return {'stage': '横向出界',
                'advice': '建议增加初始横向偏差与通道保持练习，不要靠改障碍几何'}
    if r == 'tipped':
        return {'stage': '倾覆',
                'advice': '建议降低障碍高度、增加低速接触与抬腿时机练习'}
    if r == 'bypass':
        return {'stage': '无接触通过（K 任务不算成功）',
                'advice': '建议把障碍移到轮线上，做单侧接触题'}
    if r == 'time_limit':
        return {'stage': '超时', 'advice': '建议排查卡住位置，增加通过后恢复练习'}
    return {'stage': str(r), 'advice': '记录该场景用于下一批练习'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path in ('/', '/index.html'):
            self._send(200, PAGE, 'text/html; charset=utf-8')
        elif path == '/api/assets':
            self._send(200, json.dumps({'assets': asset_list(),
                                        'checkpoints': sorted(CHECKPOINTS)},
                                       ensure_ascii=False))
        else:
            self._send(404, json.dumps({'error': 'not found'}))

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n) or b'{}')
            if self.path == '/api/run':
                spec = build_spec(req)
                info = run_episode(spec, req.get('policy', 'zero'),
                                   int(req.get('seed') or 0))
                info['hint'] = failure_hint(info)
                info['scene_id'] = terrain.scene_identity(spec)
                self._send(200, json.dumps(info, ensure_ascii=False))
            else:
                self._send(404, json.dumps({'error': 'not found'}))
        except Exception as e:
            self._send(500, json.dumps({'error': type(e).__name__,
                                        'detail': str(e)[:300],
                                        'trace': traceback.format_exc()[-600:]},
                                       ensure_ascii=False))


PAGE = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>月面上岗考场</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;font:14px/1.6 system-ui,-apple-system,"Noto Sans CJK SC",sans-serif;
      background:#0b0a0d;color:#e9e3da}
 header{padding:16px 22px;border-bottom:1px solid #24212a}
 h1{margin:0;font-size:18px;letter-spacing:.5px}
 .sub{color:#8f8794;font-size:12px;margin-top:4px}
 main{display:grid;grid-template-columns:340px 1fr;gap:18px;padding:18px 22px}
 .card{background:#141219;border:1px solid #24212a;border-radius:10px;padding:14px}
 .card h2{margin:0 0 10px;font-size:13px;color:#c9a86a;letter-spacing:1px}
 label{display:block;margin:8px 0 4px;color:#9b93a1;font-size:12px}
 select,input{width:100%;padding:6px 8px;background:#0e0c12;color:#e9e3da;
   border:1px solid #2c2836;border-radius:6px}
 button{margin-top:12px;width:100%;padding:9px;background:#c9a86a;color:#171318;
   border:0;border-radius:6px;font-weight:600;cursor:pointer}
 button:disabled{background:#4a4438;color:#8a8378;cursor:default}
 #out{white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px;
      color:#a8e6c8;background:#0e0c12;border:1px solid #24212a;border-radius:6px;
      padding:10px;min-height:60px}
 .row{display:flex;gap:10px}
 .row>*{flex:1}
 .tag{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
      background:#2a2432;color:#b9aecd;margin-right:6px}
 .warn{color:#e8b45a}
 .err{color:#ff8080}
 canvas{background:#0e0c12;border:1px solid #24212a;border-radius:8px;width:100%}
</style>
<header>
  <h1>月面上岗考场</h1>
  <div class="sub">任务条件 → 真实物理场景 → 策略考核 → 失败复盘与下一道练习题</div>
</header>
<main>
 <div>
  <div class="card">
    <h2>① 出题</h2>
    <label>任务
      <select id="task"><option value="M">M 安全通行（可绕行/跨骑/接触）</option>
      <option value="K">K 接触越障（必须接触）</option></select></label>
    <label>资产（缓存，不触发生成）
      <select id="asset"></select></label>
    <label>障碍高度（米）<input id="h" type="number" value="0.085" step="0.005"></label>
    <label>初始横向偏差（米）<input id="lat" type="number" value="0.20" step="0.05"></label>
    <label>障碍横向位置（米，0=居中）<input id="oy" type="number" value="0.0" step="0.02"></label>
    <label>初态 seed<input id="seed" type="number" value="0" step="1"></label>
  </div>
  <div class="card" style="margin-top:14px">
    <h2>② 考核</h2>
    <label>策略
      <select id="policy">
        <option value="zero">共享底座 + 零越障残差</option>
        <option value="primitive">共享底座 + 固定原语</option>
      </select></label>
    <button id="run">运行真实仿真</button>
    <div class="sub" style="margin-top:8px">
      <span class="tag">缓存资产</span>组装场景不收费
    </div>
  </div>
 </div>
 <div>
  <div class="card">
    <h2>③ 结果与复盘</h2>
    <div id="out">尚未运行。选好条件后点“运行真实仿真”。</div>
  </div>
  <div class="card" style="margin-top:14px">
    <h2>轨迹（x 前进 / y 横向）</h2>
    <canvas id="cv" width="900" height="240"></canvas>
  </div>
 </div>
</main>
<script>
const $=id=>document.getElementById(id);
async function load(){
  const r=await fetch('/api/assets'); const d=await r.json();
  $('asset').innerHTML=d.assets.map(a=>
    `<option value="${a.name}">${a.name} · h=${a.height_m}m · ${a.parts}块</option>`).join('');
  const pol=$('policy');
  for(const c of d.checkpoints){ const o=document.createElement('option');
    o.value=c; o.textContent='学习策略 '+c; pol.appendChild(o); }
}
function draw(tr){
  const cv=$('cv'), g=cv.getContext('2d');
  g.clearRect(0,0,cv.width,cv.height);
  g.strokeStyle='#24212a'; g.beginPath(); g.moveTo(0,cv.height/2);
  g.lineTo(cv.width,cv.height/2); g.stroke();
  g.strokeStyle='#3a3348'; g.setLineDash([4,4]);
  g.beginPath(); g.moveTo(0,cv.height/2-42*2); g.lineTo(cv.width,cv.height/2-42*2);
  g.moveTo(0,cv.height/2+42*2); g.lineTo(cv.width,cv.height/2+42*2); g.stroke();
  g.setLineDash([]);
  if(!tr||!tr.length) return;
  const xs=tr.map(p=>p[0]), ys=tr.map(p=>p[1]);
  const x0=Math.min(...xs), x1=Math.max(...xs,3.0);
  g.strokeStyle='#a8e6c8'; g.lineWidth=2; g.beginPath();
  tr.forEach((p,i)=>{
    const px=(p[0]-x0)/(x1-x0+1e-6)*(cv.width-20)+10;
    const py=cv.height/2-p[1]*240;
    i?g.lineTo(px,py):g.moveTo(px,py);
  });
  g.stroke();
}
$('run').onclick=async()=>{
  const btn=$('run'); btn.disabled=true; btn.textContent='运行中…';
  $('out').textContent='运行真实仿真（MuJoCo，50Hz 控制）…';
  try{
    const body={task:$('task').value,asset:$('asset').value,
      height_m:+$('h').value,init_lateral_m:+$('lat').value,
      obstacle_y:+$('oy').value,seed:+$('seed').value,policy:$('policy').value};
    const r=await fetch('/api/run',{method:'POST',body:JSON.stringify(body)});
    const d=await r.json();
    if(d.error){ $('out').innerHTML='<span class="err">运行失败：'+d.error+'</span>\n'+d.detail; }
    else{
      $('out').textContent =
`任务        ${d.task}   场景 ${d.scene_id}
策略        ${d.policy}   初态 seed ${d.seed}
结局        ${d.reason}
通行方式    ${d.contact_style||'—'}   接触 ${d.contact_any?'是':'否'}  首次接触 ${d.first_contact_s??'—'} s
终态        x=${d.x}  m   横向偏差=${d.lateral_offset} m   倾角=${d.tilt_deg}°
完成线      x=${d.pass_x} m   保持起点 ${d.passed_at??'—'} s
失败阶段    ${d.hint.stage}
建议        ${d.hint.advice}`;
      draw(d.trace);
    }
  }catch(e){ $('out').innerHTML='<span class="err">请求失败：'+e+'</span>'; }
  btn.disabled=false; btn.textContent='运行真实仿真';
};
load().then(()=>{ if(new URLSearchParams(location.search).get('autorun')) $('run').click(); });
</script></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--host', default='127.0.0.1')
    a = ap.parse_args()
    global CHECKPOINTS
    CHECKPOINTS = discover_checkpoints()
    print(f'已发现 {len(CHECKPOINTS)} 个学习策略 checkpoint')
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f'月面上岗考场已启动： http://{a.host}:{a.port}')
    srv.serve_forever()


if __name__ == '__main__':
    main()
