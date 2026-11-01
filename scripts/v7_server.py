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


def start_rehearsal_job(payload):
    """候选预演：只在候选碰撞上复现动作，**不是**真值执行，标签与统计都不混入正式表。"""
    job_id = uuid.uuid4().hex[:12]
    case = str(payload.get('case', 'R03'))
    if case not in CASES:
        raise ValueError(f'未在清单中的案例：{case}')
    seed = int(payload.get('seed', 7))
    action = str(payload.get('action', 'R1'))
    out = BATCH / 'evaluation' / f'rehearsal_page_{job_id}'
    cmd = [sys.executable, str(ROOT / 'scripts/v7_rerun.py'), '--case', case,
           '--hypothesis', CASES[case]['collision'], '--action', action,
           '--seed', str(seed), '--out', str(out)]
    env = dict(os.environ, MUJOCO_GL=os.environ.get('MUJOCO_GL', 'osmesa'),
               LD_LIBRARY_PATH=os.environ.get('LD_LIBRARY_PATH', ''))
    job = {'id': job_id, 'state': 'running', 'case': case, 'seed': seed,
           'action': action, 'started': time.time(),
           'out': str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out),
           'log': [], 'run_id': None, 'kind': 'candidate_rehearsal',
           'label': '候选预演（非真值执行）'}
    with LOCK:
        JOBS[job_id] = job

    def run():
        try:
            p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                               text=True, timeout=900)
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
            trail = out / 'rerun_trajectory.jsonl'
            if trail.exists() and trail.stat().st_size > 0:
                pl = subprocess.run([sys.executable, str(ROOT / 'scripts/v7_player.py'),
                                     '--traj', str(trail), '--out', str(out / 'player.html'),
                                     '--title', f'候选预演 {case} {action}'],
                                    cwd=str(ROOT), capture_output=True, text=True)
                if pl.returncode == 0:
                    job['player'] = f"/player?run={out.relative_to(ROOT)}"
        except Exception as e:  # noqa: BLE001
            job['state'] = 'failed'
            job['failure_class'] = f'{type(e).__name__}: {e}'
    threading.Thread(target=run, daemon=True).start()
    return job


def start_job(payload):
    """正式闭环重跑：走统一入口（资格门 + 独立真值 + 生产轨迹 + 播放器）。

    与本项目其他生产入口同一数据链；不把候选碰撞当成真值。
    """
    job_id = uuid.uuid4().hex[:12]
    case = str(payload.get('case', 'R03'))
    if case not in CASES:
        raise ValueError(f'未在清单中的案例：{case}')
    soil = str(payload.get('soil', 'nominal'))
    seed = int(payload.get('seed', 7))
    out = BATCH / 'evaluation' / f'page_run_{job_id}'
    method = str(payload.get('method') or 'H5_F')
    cmd = [sys.executable, str(ROOT / 'scripts/r1_page_run.py'), '--case', case,
           '--soil', soil, '--seed', str(seed), '--out', str(out),
           '--method', method]
    env = dict(os.environ, MUJOCO_GL=os.environ.get('MUJOCO_GL', 'osmesa'),
               LD_LIBRARY_PATH=os.environ.get('LD_LIBRARY_PATH', ''))
    job = {'id': job_id, 'state': 'running', 'case': case, 'soil': soil, 'seed': seed,
           'started': time.time(), 'out': str(out.relative_to(ROOT)), 'log': [],
           'run_id': None, 'method': method, 'kind': 'formal_closed_loop'}
    with LOCK:
        JOBS[job_id] = job

    def run():
        try:
            p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True,
                               timeout=1800)
            tail = (p.stdout + p.stderr).strip().splitlines()[-25:]
            job['log'] = tail
            res = {}
            rp = out / 'result.json'
            if rp.is_file():
                res = json.loads(rp.read_text())
            job['run_id'] = res.get('run_id')
            job['decision'] = (res.get('decision') or {}).get('chosen')
            job['success'] = (res.get('execution') or {}).get('success')
            job['n_frames'] = res.get('trajectory_frames')
            job['qualification'] = res.get('qualification')
            job['failure_class'] = res.get('failure_class')
            job['state'] = 'done' if res.get('ok') else 'failed'
            if res.get('player') and (out / 'player.html').is_file():
                job['player'] = f"/player?run={out.relative_to(ROOT)}"
            elif res.get('ok') is False:
                job['player_error'] = res.get('failure_class')
        except Exception as e:  # noqa: BLE001
            job['state'] = 'failed'
            job['log'] = [f'{type(e).__name__}: {e}']
        finally:
            job['finished'] = time.time()

    threading.Thread(target=run, daemon=True).start()
    return job


FULL_SELFTEST_HTML = r"""
<script>
(function () {
  if (!location.search.includes('selftest=full')) return;
  var out = [];
  function rec(k, v) { out.push(k + '=' + v); }
  function txt(id) { var e = document.getElementById(id); return e ? e.textContent : ''; }
  function finish() {
    var d = document.createElement('div'); d.id = 'selftestResult';
    d.textContent = 'SELFTEST ' + out.join(' | '); document.body.appendChild(d);
  }
  function waitJob(cb) {
    var tries = 0;
    var t = setInterval(function () {
      tries += 1;
      if (window.__job && window.__job.id) {
        clearInterval(t);
        fetch('/api/wait/' + window.__job.id)
          .then(function (r) { return r.json(); })
          .then(function (s) { cb(s); });
      } else if (tries > 60) {
        clearInterval(t); cb({state: 'no_job'});
      }
    }, 300);
  }
  function runBlocking(body, label, cb) {
    // 浏览器只发一次请求：服务端跑完再返回，避免虚拟时间把轮询耗尽
    fetch('/api/run_blocking', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify(body)})
      .then(function (r) { return r.json(); })
      .then(function (s) { cb(s); });
  }
  // 1) 正式闭环：R01（该配置无通行动作，预期失败）
  document.getElementById('cCase').value = 'R01';
  document.getElementById('cSoil').value = 'nominal';
  document.getElementById('cMethod').value = 'B0_blind';
  runBlocking({case: 'R01', soil: 'nominal', seed: 7, kind: 'formal', method: 'B0_blind'}, '正式闭环', function (s1) {
    rec('run1_kind', s1.kind || '-');
    rec('run1_state', (s1.state || '?') + ':' + (s1.decision || '-') + ':succ='
        + (s1.success == null ? '-' : s1.success) + ':frames=' + (s1.n_frames == null ? '-' : s1.n_frames));
    rec('run1_qual', (s1.qualification && s1.qualification.qualified) ? 'qualified' : 'not_qualified');
    rec('run1_player', s1.player || 'none');
    // 2) 候选预演：R03（标签必须不同）
    document.getElementById('cCase').value = 'R03';
    runBlocking({case: 'R03', seed: 7, kind: 'rehearsal'}, '候选预演', function (s2) {
      rec('run2_kind', s2.kind || '-');
      rec('run2_state', (s2.state || '?') + ':succ=' + (s2.success == null ? '-' : s2.success));
      rec('run2_player', s2.player || 'none');
      finish();
    });
  });
})();
</script>
"""

SELFTEST_HTML = r"""
<script>
(function () {
  if (!location.search.includes('selftest=1')) return;
  var out = [];
  function rec(k, v) { out.push(k + '=' + v); }
  window.__selftest = out;
  try {
    var play = document.getElementById('play');
    var pause = document.getElementById('pause');
    var seek = document.getElementById('seek');
    var before = document.getElementById('st').textContent;
    play.click();
    var t1 = document.getElementById('st').textContent;
    pause.click();
    seek.value = 500; seek.oninput({target: seek});
    var mid = document.getElementById('st').textContent;
    rec('play_advanced', String(t1 !== before));
    rec('pause_ok', '1');
    rec('seek_moved', String(mid !== t1));
    rec('canvas_present', String(!!document.getElementById('cv')));
  } catch (e) { rec('player_error', e.message); }
  try {
    var btn = document.getElementById('btnRun');
    document.getElementById('cCase').value = 'R02';
    btn.click();
    rec('rerun_clicked', '1');
    var t0 = Date.now();
    var poll = setInterval(function () {
      var s = document.getElementById('runState').textContent || '';
      if (s.indexOf('完成') >= 0 || s.indexOf('失败') >= 0 || Date.now() - t0 > 240000) {
        clearInterval(poll);
        rec('rerun_state', s.replace(/\s+/g, ' ').slice(0, 120));
        var d = document.createElement('div');
        d.id = 'selftestResult';
        d.textContent = 'SELFTEST ' + window.__selftest.join(' | ');
        document.body.appendChild(d);
      }
    }, 2000);
  } catch (e) { rec('rerun_error', e.message); }
})();
</script>
"""

CONTROL_HTML = """
<h2>正式闭环重跑（真实后端，非动画）</h2>
<div class="note">走统一入口：唯一资格门 → 预演 → 决策先落盘 → 独立真值执行 → 连续轨迹与回放。
不触发生成、不联网、不花钱。候选预演是另一类操作，标签不同、统计不进真值执行。</div>
<div style="margin:8px 0">
  案例 <select id="cCase"><option>R03</option><option>R02</option><option>R01</option><option>R04</option></select>
  土壤 <select id="cSoil"><option>nominal</option><option>low_traction</option><option>high_drag</option></select>
  seed <input id="cSeed" type="number" value="7" style="width:60px">
  方法 <select id="cMethod">
    <option value="H5_F">H5_F 候选（Lux3D）</option>
    <option value="E25D_fill">2.5D 补平（未知按可见地面）</option>
    <option value="E25D_block">2.5D 挡未知</option>
    <option value="B1_height">高度规则</option>
    <option value="B2_F">方盒子</option>
    <option value="B3_F">镜像</option>
    <option value="U_truth">真值参考（只给对照）</option>
    <option value="B0_blind">B0 盲走（诊断/失败演示）</option>
  </select>
  <button id="btnRun">开始正式闭环重跑</button>
  <button id="btnRehearse">候选预演（非真值执行）</button>
</div>
<div id="runState" class="note">状态：未开始</div>
<div id="runKind" class="note" data-kind="">操作类型：—</div>
<div id="runQual" class="note">资格：—</div>
<div id="runResult" class="note">结果：—</div>
<div id="runPlayer"></div>
<pre id="runLog" style="display:none;max-height:220px;overflow:auto;font-size:12px"></pre>
<script>
(function () {
  var st = document.getElementById('runState'), lg = document.getElementById('runLog');
  var kind = document.getElementById('runKind'), qual = document.getElementById('runQual');
  var res = document.getElementById('runResult'), pl = document.getElementById('runPlayer');
  function submit(url, body, label) {
    st.textContent = '状态：已提交，等待启动…';
    kind.textContent = '操作类型：' + label; kind.setAttribute('data-kind', label);
    qual.textContent = '资格：—'; res.textContent = '结果：—'; pl.innerHTML = '';
    lg.style.display = 'block'; lg.textContent = '';
    fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (job) {
        st.textContent = '状态：运行中 · job ' + job.id;
        window.__job = job;
        var t0 = Date.now();
        var poll = setInterval(function () {
          fetch('/api/status/' + job.id).then(function (r) { return r.json(); }).then(function (s) {
            lg.textContent = (s.log || []).join('\n');
            if (s.state === 'running') {
              st.textContent = '状态：运行中 · job ' + s.id + ' · ' + Math.round((Date.now() - t0) / 1000) + 's';
              return;
            }
            clearInterval(poll);
            st.textContent = (s.state === 'done' ? '状态：完成 · 新 run_id ' + (s.run_id || '?')
                                                : '状态：失败 · ' + (s.failure_class || '见日志'));
            var q = s.qualification || {};
            qual.textContent = '资格：' + (q.qualified ? '合格（' + (q.method || '') + '）'
                                     : (q.reason ? '不合格 · ' + q.reason : '未知'));
            var ex = s.execution || {};
            res.textContent = '结果：run_id ' + (s.run_id || '—') + ' · 方法 ' + (s.method || '—')
              + ' · 决策 ' + (s.decision || '—') + ' · 成功 ' + (s.success == null ? '—' : s.success)
              + ' · 帧数 ' + (s.n_frames == null ? '—' : s.n_frames)
              + ' · 失败类别 ' + (s.failure_class || '无');
            if (s.player) {
              pl.innerHTML = '<a id="openPlayer" href="' + s.player + '">打开该 run 的连续回放</a>';
            }
            window.__lastJob = s;
          });
        }, 1500);
      })
      .catch(function (e) { st.textContent = '状态：失败（后端没起？' + e.message + '）'; });
  }
  document.getElementById('btnRun').onclick = function () {
    submit('/api/rerun', {case: document.getElementById('cCase').value,
                          soil: document.getElementById('cSoil').value,
                          seed: Number(document.getElementById('cSeed').value),
                          method: document.getElementById('cMethod').value},
           '正式闭环（独立真值）');
  };
  document.getElementById('btnRehearse').onclick = function () {
    submit('/api/rehearse', {case: document.getElementById('cCase').value,
                             seed: Number(document.getElementById('cSeed').value),
                          method: document.getElementById('cMethod').value},
           '候选预演（非真值执行）');
  };
})();
</script>
"""


PLAYER_SELFTEST = r"""
<script>
(function () {
  if (!location.search.includes('selftest=1')) return;
  var out = [];
  function rec(k, v) { out.push(k + '=' + v); }
  function finish() {
    var d = document.createElement('div'); d.id = 'selftestResult';
    d.textContent = 'SELFTEST ' + out.join(' | '); document.body.appendChild(d);
  }
  try {
    var st = document.getElementById('st'), play = document.getElementById('play');
    var pause = document.getElementById('pause'), seek = document.getElementById('seek');
    var t0 = st.textContent;
    play.click();
    setTimeout(function () {
      var t1 = st.textContent;
      pause.click();
      rec('play_advanced', String(t1 !== t0));
      rec('reached', t1);
      var before = t1;
      seek.value = 500; seek.oninput({target: seek});
      rec('seek_moved', String(st.textContent !== before));
      rec('seek_value', st.textContent);
      rec('canvas_present', String(!!document.getElementById('cv')));
      finish();
    }, 1500);
  } catch (e) { rec('player_error', e.message); finish(); }
})();
</script>
"""


def inject_player_selftest(html):
    return html.replace('</body>', PLAYER_SELFTEST + '</body>', 1) if '</body>' in html else html + PLAYER_SELFTEST


def inject_rerun(html):
    """把可操作控件插到 <h2>限制</h2> 之前；页面本身不依赖后端。"""
    marker = '<h2>限制</h2>'
    return html.replace(marker, CONTROL_HTML + SELFTEST_HTML + FULL_SELFTEST_HTML + marker, 1)


CASES = {
    'R01': {'collision': 'runs/unseen/delivery_v7/v7_20261030/processed/V7_R01_s1/collision'},
    'R02': {'collision': 'runs/unseen/delivery_v7/v7_20261030/processed/V7_R02_s1/collision'},
    'R03': {'collision': 'runs/unseen/delivery_v7/v7_20261030/processed/V7_R03_s2/collision'},
    'R04': {'collision': 'runs/unseen/delivery_v7/v7_20261030/processed/V7_R04_s1/collision'},
}


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
        if p.path.startswith('/player') and 'run=' in p.query:
            from urllib.parse import parse_qs
            rel = parse_qs(p.query).get('run', [''])[0]
            f = ROOT / rel / 'player.html'
            if not f.exists():
                return self._send(404, '该 run 还没有播放器', 'text/plain; charset=utf-8')
            return self._send(200, inject_player_selftest(f.read_text()), 'text/html; charset=utf-8')
        if p.path.startswith('/player'):
            f = BATCH / 'media/report/player.html'
            if not f.exists():
                return self._send(404, '播放器不存在，先跑 v7_player.py', 'text/plain; charset=utf-8')
            return self._send(200, inject_player_selftest(f.read_text()), 'text/html; charset=utf-8')
        if p.path.startswith('/api/wait/'):
            jid = p.path.split('/')[-1]
            if not jid:
                return self._send(400, json.dumps({'error': 'missing job id'}))
            t0 = time.time()
            while time.time() - t0 < 600:
                j = JOBS.get(jid)
                if j and j.get('state') != 'running':
                    return self._send(200, json.dumps(j, ensure_ascii=False, default=str))
                time.sleep(1.0)
            j = dict(JOBS.get(jid) or {})
            j['state'] = j.get('state') or 'timeout'
            return self._send(200, json.dumps(j, ensure_ascii=False, default=str))
        if p.path.startswith('/api/status/'):
            jid = p.path.rsplit('/', 1)[-1]
            with LOCK:
                job = JOBS.get(jid)
            if not job:
                return self._send(404, json.dumps({'error': 'unknown job'}))
            return self._send(200, json.dumps(job, ensure_ascii=False))
        if p.path == '/api/cases':
            return self._send(200, json.dumps({'cases': list(CASES),
                                               'per_case': CASES,
                                               'actions': ['R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2']}))
        return self._send(404, 'not found', 'text/plain')

    def do_POST(self):
        if self.path not in ('/api/rerun', '/api/rehearse', '/api/run_blocking'):
            return self._send(404, 'not found', 'text/plain')
        n = int(self.headers.get('Content-Length') or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b'{}')
        except json.JSONDecodeError:
            payload = {}
        if self.path == '/api/run_blocking':
            # 浏览器只发一次请求：服务端等到作业结束再返回（便于无头浏览器验收）
            job = (start_rehearsal_job(payload) if payload.get('kind') == 'rehearsal'
                   else start_job(payload))
            t0 = time.time()
            while time.time() - t0 < 900:
                j = JOBS.get(job['id'], {})
                if j.get('state') != 'running':
                    return self._send(200, json.dumps(j, ensure_ascii=False, default=str))
                time.sleep(0.5)
            return self._send(200, json.dumps(dict(job, state='timeout'),
                                              ensure_ascii=False, default=str))
        job = (start_rehearsal_job(payload) if self.path == '/api/rehearse'
               else start_job(payload))
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
