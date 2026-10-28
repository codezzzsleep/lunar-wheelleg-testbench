"""
五步页面：选案例 → 机器人视角 → 背面假设 → 物理预演 → 决定 → 执行与揭晓。

  .venv/bin/python scripts/app_unseen.py --port 8090
  # 打开 http://127.0.0.1:8090

只读已跑过的 e2e 产物，不在页面里触发付费或重新生成；
没有跑过案例时页面明确显示"未运行"，不伪造数据。
"""
import argparse
import json
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
E2E = ROOT / 'runs/unseen/e2e'
RECOVERY = ROOT / 'runs/unseen/recovery_r3'
# 本批新增运行：只读缓存，页面不触发任何付费动作
REGISTRY = RECOVERY / 'page_runs.json'


def _registry():
    if REGISTRY.exists():
        try:
            return json.loads(REGISTRY.read_text())
        except Exception:
            return []
    return []


def list_cases():
    out = []
    if E2E.exists():
        for d in sorted(E2E.iterdir()):
            s = d / 'summary.json'
            if s.exists():
                try:
                    out.append({'run': d.name, 'kind': 'e2e',
                                **json.loads(s.read_text())})
                except Exception:
                    out.append({'run': d.name, 'kind': 'e2e',
                                'error': 'summary 无法解析'})
    for r in _registry():
        d = RECOVERY / r['run']
        if d.exists():
            out.append({'run': r['run'], 'kind': r.get('kind', 'recovery'),
                        'case_id': r.get('case_id', r['run']),
                        'hyp_source': r.get('hyp_source', '')})
    return out


def _load_recovery(d, run):
    """把 recovery_r3 下的两种批次归一化成页面需要的字段。"""
    def rj(name, default=None):
        p = d / name
        return json.loads(p.read_text()) if p.exists() else default

    def rjl(name):
        p = d / name
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    if (d / 'summary.json').exists() and (d / 'decisions.json').exists():
        # 六方法矩阵
        summ = rj('summary.json', {})
        decs = rj('decisions.json', [])
        recs = rjl('records.jsonl')
        return {'run': run, 'kind': 'six', 'summary': summ,
                'observation': rj('observation.json'),
                'decision': {'chosen': None, 'methods': summ.get('methods'),
                             'rule': '每方法自选动作，再在同一真值上执行'},
                'six': {'methods': summ.get('methods', []),
                        'decisions': decs, 'truth_sha': summ.get('truth_sha'),
                        'initial_states': summ.get('initial_states')},
                'rehearsal': recs, 'execution': [],
                'has_rgb': (d / 'rgb.png').exists(),
                'has_mask': (d / 'mask.png').exists(),
                'views': [], 'replay': []}
    # H5 单例管线
    return {'run': run, 'kind': 'h5',
            'summary': rj('summary.json', {}),
            'observation': rj('observation.json'),
            'decision': rj('decision.json', {}),
            'rehearsal': rjl('rehearsal.jsonl'),
            'execution': rjl('execution.jsonl'),
            'h5loop': rj('h5_loop.json'),
            'has_rgb': (d / 'rgb.png').exists(),
            'has_mask': (d / 'mask.png').exists(),
            'views': [], 'replay': []}


def load_run(run):
    d = E2E / run
    if not d.exists():
        d = RECOVERY / run
        if not d.exists():
            raise FileNotFoundError(run)
        return _load_recovery(d, run)
    def rd(name, default=None):
        p = d / name
        if not p.exists():
            return default
        if name.endswith('.jsonl'):
            return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        return json.loads(p.read_text())
    return {
        'run': run,
        'summary': rd('summary.json'),
        'observation': rd('observation.json'),
        'decision': rd('decision.json'),
        'rehearsal': rd('rehearsal.jsonl', []),
        'execution': rd('execution.jsonl', []),
        'has_rgb': (d / 'rgb.png').exists(),
        'has_mask': (d / 'mask.png').exists(),
        'views': sorted(p.name for p in (d / 'view').glob('*.png')) if (d / 'view').exists() else [],
        'replay': sorted(p.name for p in (d / 'replay').glob('*.png')) if (d / 'replay').exists() else [],
    }


PAGE = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>看不见的那一面</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;font:14px/1.65 system-ui,-apple-system,"Noto Sans CJK SC",sans-serif;
      background:#0b0a0d;color:#e9e3da}
 header{padding:16px 22px;border-bottom:1px solid #24212a}
 h1{margin:0;font-size:18px}
 .sub{color:#8f8794;font-size:12px;margin-top:4px}
 main{display:grid;grid-template-columns:300px 1fr;gap:16px;padding:16px 22px}
 .card{background:#141219;border:1px solid #24212a;border-radius:10px;padding:14px;margin-bottom:14px}
 .card h2{margin:0 0 10px;font-size:13px;color:#c9a86a;letter-spacing:1px}
 select,button{width:100%;padding:8px;background:#0e0c12;color:#e9e3da;
   border:1px solid #2c2836;border-radius:6px}
 button{margin-top:10px;background:#c9a86a;color:#171318;border:0;font-weight:600;cursor:pointer}
 img{max-width:46%;max-height:300px;border-radius:8px;border:1px solid #24212a;background:#0e0c12;margin-right:8px}
 table{border-collapse:collapse;width:100%;font-size:12px}
 th,td{border-bottom:1px solid #24212a;padding:5px 6px;text-align:left}
 th{color:#8f8794;font-weight:500}
 .ok{color:#7fe0b0}.bad{color:#ff9a9a}.dim{color:#8f8794}
 .step{display:flex;gap:10px;align-items:baseline;margin-bottom:6px}
 .n{background:#2a2432;color:#c9a86a;border-radius:99px;padding:1px 8px;font-size:11px}
 pre{white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px;
     background:#0e0c12;border:1px solid #24212a;border-radius:6px;padding:10px}
</style>
<header><h1>看不见的那一面 · 轮腿机器人「先想后走」</h1>
<div class="sub">机器人只看得到障碍正面；系统生成多种背面假设，预演每个走法，选最稳健的，再揭晓真相</div></header>
<main>
 <div>
  <div class="card"><h2>选择案例</h2>
    <select id="run"></select>
    <button id="go">打开案例</button>
    <div class="sub" id="note" style="margin-top:8px"></div>
  </div>
  <div class="card"><h2>来源声明</h2>
    <div class="sub" id="src"></div>
  </div>
 </div>
 <div>
  <div class="card"><h2><span class="step"><span class="n">1</span>机器人视角</span></h2>
    <div id="obs" class="dim">未选择案例</div>
    <div id="imgs"></div>
  </div>
  <div class="card"><h2><span class="step"><span class="n">2</span>背面假设与预演</span></h2>
    <div id="hyp" class="dim">—</div>
  </div>
  <div class="card"><h2><span class="step"><span class="n">3</span>决定</span></h2>
    <div id="dec" class="dim">—</div>
  </div>
  <div class="card"><h2><span class="step"><span class="n">2b</span>候选背面（三维侧视）</span></h2>
    <div id="hyp3d" class="dim">—</div>
  </div>
  <div class="card" id="sixcard" style="display:none"><h2><span class="step"><span class="n">5</span>六方法对照（共同真值）</span></h2>
    <div id="six" class="dim">—</div>
  </div>
  <div class="card" id="h5card" style="display:none"><h2><span class="step"><span class="n">6</span>真实 Lux3D 候选链</span></h2>
    <div id="h5" class="dim">—</div>
  </div>
  <div class="card"><h2><span class="step"><span class="n">4</span>真值执行与揭晓</span></h2>
    <div id="exec" class="dim">—</div>
    <div id="reveal" style="margin-top:10px"></div>
    <div id="replay" style="margin-top:10px"></div>
  </div>
 </div>
</main>
<script>
const $=id=>document.getElementById(id);
async function boot(){
  const r=await fetch('/api/cases'); const d=await r.json();
  const sel=$('run');
  if(!d.cases.length){ sel.innerHTML='<option>（还没有跑过案例）</option>';
    $('note').textContent='先运行 scripts/unseen_pipeline.py 生成一个案例'; return; }
  sel.innerHTML=d.cases.map(c=>`<option value="${c.run}">${c.case_id} · ${c.run}</option>`).join('');
}
async function open_(){
  const run=$('run').value;
  const r=await fetch('/api/run?name='+encodeURIComponent(run));
  const d=await r.json();
  if(d.error){ $('obs').innerHTML='<span class="bad">'+d.error+'</span>'; return; }
  const s=d.summary||{}, o=(d.observation||{}).visible||{};
  $('src').innerHTML = `假设来源：<b>${s.hyp_source||'?'}</b><br>${s.hyp_source_note||''}`;
  $('obs').innerHTML = `可见像素 ${ (d.observation||{}).visible?.n_pixels ?? '—' }　
    前沿 x=${o.x_front?.toFixed(3) ?? '—'} m　可见宽 ${o.W_vis?.toFixed(3) ?? '—'} m　
    可见高 ${o.H_vis?.toFixed(3) ?? '—'} m`;
  $('imgs').innerHTML = (d.has_rgb? `<img src="/img/${run}/rgb.png">`:'') +
                        (d.has_mask? `<img src="/img/${run}/mask.png" style="margin-top:8px">`:'');
  const rows=d.rehearsal||[];
  const by={}; rows.forEach(m=>{const k=m.hypothesis_id+'|'+m.option;
    (by[k]=by[k]||[]).push(m.success?1:0);});
  let t='<table><tr><th>假设</th><th>动作</th><th>成功/总</th></tr>';
  Object.keys(by).sort().forEach(k=>{const [h,o]=k.split('|');
    const v=by[k]; t+=`<tr><td>${h}</td><td>${o}</td><td>${v.reduce((a,b)=>a+b,0)}/${v.length}</td></tr>`;});
  t+='</table>'; $('hyp').innerHTML=t;
  const dec=d.decision||{};
  $('dec').innerHTML = `<b>选择 ${dec.chosen||'—'}</b>　
    ${dec.no_robust_option? '<span class="bad">没有稳健通行动作</span>':'<span class="ok">存在稳健动作</span>'}<br>
    <span class="dim">规则 ${dec.rule||'—'}　候选 ${ (dec.hypotheses||[]).length } 个　初态 ${dec.n_seeds||'—'} 个</span><br>
    <span class="dim">${dec.reason_text||''}</span>
    <pre>${JSON.stringify(dec.stats||{},null,1).slice(0,900)}</pre>`;
  const hv=(d.views||[]).filter(n=>n.startsWith('hyp_'));
  $('hyp3d').innerHTML = hv.length
    ? hv.map(n=>`<figure style="display:inline-block;width:31%;margin:0 1% 0 0">
        <img src="/img/${run}/view/${n}" style="max-height:150px">
        <figcaption class="dim" style="font-size:11px">${n.replace('hyp_','').replace('.png','')}</figcaption>
      </figure>`).join('')
    : '<span class="dim">尚无候选三维视图</span>';
  const ex=d.execution||[];
  const chosen=ex.filter(m=>m.option===dec.chosen), blind=ex.filter(m=>m.option==='R1');
  const rate=a=>a.length? a.filter(m=>m.success).length+'/'+a.length : '—';
  $('exec').innerHTML = `<table><tr><th>在真值上的执行</th><th>成功</th></tr>
    <tr><td>系统选择（${dec.chosen}）</td><td class="${chosen.every(m=>m.success)?'ok':'bad'}">${rate(chosen)}</td></tr>
    <tr><td>盲走（R1）</td><td class="${blind.every(m=>m.success)?'ok':'bad'}">${rate(blind)}</td></tr></table>
    <div class="dim" style="margin-top:6px">决策只用了观测与假设；真值在这之后才展示</div>`;
  const rev=(d.views||[]).filter(n=>n.startsWith('truth_'));
  $('reveal').innerHTML = rev.length
    ? `<div class="sub">揭晓：真值障碍（侧视，含背面）</div>
       <img src="/img/${run}/view/${rev[0]}" style="max-height:200px">`
    : '<span class="dim">尚无真值揭晓图</span>';
  if(d.kind==='six'){ $('sixcard').style.display=''; $('six').innerHTML=fmtSix(d); }
  else { $('sixcard').style.display='none'; }
  if(d.kind==='h5' || d.h5loop){ $('h5card').style.display=''; $('h5').innerHTML=fmtH5(d); }
  else { $('h5card').style.display='none'; }
  const rp=d.replay||[];
  $('replay').innerHTML = rp.length
    ? `<div class="sub">选定动作回放（${rp.length} 帧）</div>` +
      rp.map(n=>`<img src="/img/${run}/replay/${n}" style="max-height:120px">`).join('')
    : '<span class="dim">尚无回放帧</span>';
}
function fmtSix(d){
  const s=(d.six||{}).methods||[];
  if(!s.length) return '<span class="dim">该运行没有六方法表</span>';
  let t='<table><tr><th>方法</th><th>自选动作</th><th>执行</th><th>成功</th><th>刹停</th><th>失败</th><th>均代价</th></tr>';
  s.forEach(m=>{
    const cls=m.success===m.n_exec&&m.n_exec>0?'ok':(m.success===0?'bad':'');
    t+=`<tr><td>${m.method}</td><td>${m.selected_action??'—'}</td><td>${m.n_exec}</td>
        <td class="${cls}">${m.success}</td><td>${m.abort}</td><td>${m.fail}</td>
        <td>${m.mean_cost??'—'}</td></tr>`;
  });
  t+='</table>';
  t+=`<div class="dim" style="margin-top:6px">共同真值 ${ (d.six.truth_sha||'').slice(0,12) }…
      初态 ${JSON.stringify(d.six.initial_states)}　预演不计入执行成绩</div>`;
  return t;
}
function fmtH5(d){
  const h=d.h5loop;
  if(!h) return '<span class="dim">该运行没有 H5 单例记录</span>';
  const c=(h.candidate_meta)||{};
  const same = h.candidate_world_sha===h.truth_asset_sha;
  let t=`<table>
    <tr><th>候选</th><td>${h.candidate_id||'—'}（task ${h.candidate_task_id??'—'}）</td></tr>
    <tr><th>候选 world SHA</th><td>${(h.candidate_world_sha||'').slice(0,16)}…</td></tr>
    <tr><th>真值 SHA</th><td>${(h.truth_asset_sha||'').slice(0,16)}…</td></tr>
    <tr><th>是否独立真值</th><td class="${same?'bad':'ok'}">${same?'否（同一资产，不能算独立闭环）':'是'}</td></tr>
    <tr><th>初态</th><td>${(h.initial_states||[]).length} 个，互异=${h.initial_states_distinct}</td></tr>
    <tr><th>决策</th><td>${(h.decision||{}).chosen_option||'—'}（先冻结：${(h.decision_sha256||'').slice(0,12)}…）</td></tr>
  </table>`;
  const ex=h.execution||[];
  const h5=ex.filter(e=>e.method==='H5'), b0=ex.filter(e=>e.method==='B0_blind');
  const rate=a=>a.length?a.filter(e=>e.success).length+'/'+a.length:'—';
  t+=`<table style="margin-top:8px"><tr><th>在独立真值上</th><th>成功</th></tr>
      <tr><td>H5 选定动作</td><td>${rate(h5)}</td></tr>
      <tr><td>盲走 B0</td><td>${rate(b0)}</td></tr></table>`;
  if(h5.length&&b0.length&&h5.filter(e=>e.success).length===b0.filter(e=>e.success).length)
    t+='<div class="dim" style="margin-top:6px">本例 H5 与盲走结果相同：不宣称收益</div>';
  return t;
}
$('go').onclick=open_;
boot().then(()=>{ const q=new URLSearchParams(location.search).get('run');
  if(q){ $('run').value=q; open_(); } else if($('run').options.length){ open_(); } });
</script></html>"""


class H(BaseHTTPRequestHandler):
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
        p = self.path.split('?', 1)[0]
        q = dict(x.split('=', 1) for x in self.path.split('?', 1)[1].split('&')
                 if '=' in x) if '?' in self.path else {}
        if p in ('/', '/index.html'):
            return self._send(200, PAGE, 'text/html; charset=utf-8')
        if p == '/api/cases':
            return self._send(200, json.dumps({'cases': list_cases()}, ensure_ascii=False))
        if p == '/api/run':
            try:
                return self._send(200, json.dumps(load_run(q.get('name', '')),
                                                  ensure_ascii=False))
            except Exception as e:
                return self._send(404, json.dumps({'error': f'{type(e).__name__}: {e}'}))
        if p.startswith('/img/'):
            parts = p.split('/')
            f = E2E.joinpath(*parts[2:])
            if f.exists() and f.is_file():
                return self._send(200, f.read_bytes(), 'image/png')
            return self._send(404, 'missing', 'text/plain')
        return self._send(404, json.dumps({'error': 'not found'}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8090)
    ap.add_argument('--host', default='127.0.0.1')
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f'看不见的那一面：http://{a.host}:{a.port}')
    srv.serve_forever()


if __name__ == '__main__':
    main()
