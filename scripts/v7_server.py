"""本机页面后端：让报告页真的能"对缓存案例重新仿真"（任务书 §11.1）。

只做三件事：
  GET  /                → 报告页
  POST /api/rerun       → 起一次真实 MuJoCo 重仿真（新 run_id、新日志、新结果）
  GET  /api/status/<id> → running / done / failed + 新 run_id + 日志尾

不触发生成、不联网、不花钱；默认只监听 127.0.0.1。

  .venv/bin/python scripts/v7_server.py --port 8765
"""
import argparse, json, os, pathlib, subprocess, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
BATCH = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1'
JOBS = {}
LOCK = threading.Lock()


def start_job(payload):
    job_id = uuid.uuid4().hex[:12]
    case = str(payload.get('case', 'R03'))
    action = str(payload.get('action', 'R1'))
    seed = int(payload.get('seed', 0))
    hyp = str(payload.get('hypothesis', 'runs/unseen/delivery_v7/v7_20261030/processed/V7_R03_s2/collision'))
    out = BATCH / 'evaluation' / f'rerun_page_{job_id}'
    cmd = [sys.executable, str(ROOT / 'scripts/v7_rerun.py'), '--case', case,
           '--hypothesis', hyp, '--action', action, '--seed', str(seed), '--out', str(out)]
    env = dict(os.environ, MUJOCO_GL=os.environ.get('MUJOCO_GL', 'osmesa'),
               LD_LIBRARY_PATH=os.environ.get('LD_LIBRARY_PATH', ''))
    job = {'id': job_id, 'state': 'running', 'case': case, 'action': action, 'seed': seed,
           'started': time.time(), 'out': str(out.relative_to(ROOT)), 'log': [], 'run_id': None}
    with LOCK:
        JOBS[job_id] = job

    def run():
        try:
            p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=900)
            tail = (p.stdout + p.stderr).strip().splitlines()[-25:]
            job['log'] = tail
            last = {}
            for line in reversed(tail):
                line = line.strip()
                if line.startswith('{') and line.endswith('}'):
                    try:
                        last = json.loads(line); break
                    except json.JSONDecodeError:
                        continue
            job['run_id'] = last.get('run_id')
            job['success'] = last.get('success')
            job['n_frames'] = last.get('n_frames')
            job['state'] = 'done' if p.returncode == 0 else 'failed'
        except Exception as e:  # noqa: BLE001
            job['state'] = 'failed'
            job['log'] = [f'{type(e).__name__}: {e}']
        finally:
            job['finished'] = time.time()

    threading.Thread(target=run, daemon=True).start()
    return job


CONTROL_HTML = """
<h2>重新仿真（真实后端，非动画）</h2>
<div class="note">点按钮会真的启动一次 MuJoCo 重仿真：新 run_id、新日志、新结果。
不触发生成、不联网、不花钱。</div>
<div style="margin:8px 0">
  案例 <select id="cCase"><option>R03</option><option>R02</option><option>R01</option><option>R04</option></select>
  动作 <select id="cAct"><option>R1</option><option>D1</option><option>S1</option><option>R2</option><option>L1</option><option>L2</option><option>D2</option></select>
  seed <input id="cSeed" type="number" value="0" style="width:60px">
  <button id="btnRun">开始重新仿真</button>
</div>
<div id="runState" class="note">状态：未开始</div>
<pre id="runLog" style="display:none;max-height:220px;overflow:auto;font-size:12px"></pre>
<script>
(function () {
  var st = document.getElementById('runState'), lg = document.getElementById('runLog');
  document.getElementById('btnRun').onclick = function () {
    var body = {case: document.getElementById('cCase').value,
                action: document.getElementById('cAct').value,
                seed: Number(document.getElementById('cSeed').value)};
    st.textContent = '状态：已提交，等待启动…';
    lg.style.display = 'block'; lg.textContent = '';
    fetch('/api/rerun', {method: 'POST', headers: {'Content-Type': 'application/json'},
                         body: JSON.stringify(body)})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (job) {
        st.textContent = '状态：运行中 · job ' + job.id;
        var t0 = Date.now();
        var poll = setInterval(function () {
          fetch('/api/status/' + job.id).then(function (r) { return r.json(); }).then(function (s) {
            lg.textContent = (s.log || []).join('\n');
            if (s.state === 'running') {
              st.textContent = '状态：运行中 · job ' + s.id + ' · ' + Math.round((Date.now() - t0) / 1000) + 's';
            } else {
              clearInterval(poll);
              st.textContent = s.state === 'done'
                ? '状态：完成 · 新 run_id ' + (s.run_id || '?') + ' · 帧数 ' + (s.n_frames == null ? '?' : s.n_frames)
                : '状态：失败（见日志）';
            }
          });
        }, 1500);
      })
      .catch(function (e) { st.textContent = '状态：失败（后端没起？' + e.message + '）'; });
  };
})();
</script>
"""


def inject_rerun(html):
    """把可操作控件插到 <h2>限制</h2> 之前；页面本身不依赖后端。"""
    marker = '<h2>限制</h2>'
    return html.replace(marker, CONTROL_HTML + marker, 1)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ('/', '/index.html'):
            f = BATCH / 'media/report/index.html'
            if not f.exists():
                return self._send(404, '报告页不存在，先跑 v7_page_r1.py', 'text/plain; charset=utf-8')
            return self._send(200, inject_rerun(f.read_text()), 'text/html; charset=utf-8')
        if p.path.startswith('/api/status/'):
            jid = p.path.rsplit('/', 1)[-1]
            with LOCK:
                job = JOBS.get(jid)
            if not job:
                return self._send(404, json.dumps({'error': 'unknown job'}))
            return self._send(200, json.dumps(job, ensure_ascii=False))
        if p.path == '/api/cases':
            return self._send(200, json.dumps({'cases': ['R01', 'R02', 'R03', 'R04'],
                                               'actions': ['R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2']}))
        return self._send(404, 'not found', 'text/plain')

    def do_POST(self):
        if self.path != '/api/rerun':
            return self._send(404, 'not found', 'text/plain')
        n = int(self.headers.get('Content-Length') or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b'{}')
        except json.JSONDecodeError:
            payload = {}
        job = start_job(payload)
        return self._send(200, json.dumps(job, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='127.0.0.1')
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(json.dumps({'listening': f'http://{a.host}:{a.port}/',
                      'jobs_api': '/api/rerun  /api/status/<id>'}, ensure_ascii=False))
    srv.serve_forever()


if __name__ == '__main__':
    main()
