"""
V7-R1 页面：两种模式（回放已有运行 / 用缓存资产重新仿真）+ 五个核心画面。

  · 回放：从已有 JSONL/JSON 记录渲染时间轴，不启动仿真、不消耗积分。
  · 重新运行：调用 scripts/v7_rerun.py（真实 MuJoCo），生成新的 run_id 与日志。
两种操作在界面上显式区分；页面只读，打开页面不会触发任何付费调用。
"""
import json, pathlib, html

ROOT = pathlib.Path(__file__).resolve().parent.parent
B = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1'
B0 = ROOT / 'runs/unseen/delivery_v7/v7_20261030'


def j(p, d=None):
    p = pathlib.Path(p)
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


def rows_tbl(headers, rows):
    h = ''.join(f'<th>{html.escape(str(x))}</th>' for x in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(c))}</td>' for c in r) + '</tr>'
                   for r in rows)
    return f'<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>'


def main():
    tasks = [j(p) for p in sorted((B0 / 'generation').glob('task_*.json'))]
    tasks = [t for t in tasks if t]
    cand = []
    for p in sorted((B / 'evaluation').glob('closed_loop_*/closed_loop.json')):
        d = j(p) or {}
        cand.append({'name': p.parent.name, 'branch': d.get('branch'),
                     'cells': d.get('n_cells'), 'chosen': (d.get('decision') or {}).get('chosen'),
                     'states': d.get('n_states'),
                     'success': sum(1 for e in d.get('execution') or [] if e.get('success')),
                     'n_exec': len(d.get('execution') or [])})
    six = []
    for p in sorted((B / 'evaluation').glob('six_R03_*/summary.json')):
        s = j(p) or {}
        for m in s.get('methods', []):
            six.append([s.get('soil_mode'), m.get('method'), m.get('selected_action'),
                        f"{m.get('success')}/{m.get('n_exec')}",
                        f"{(m.get('validation') or {}).get('success')}/{(m.get('validation') or {}).get('n')}",
                        (s.get('n_initial_states') or '')])
    page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>V7-R1 · 看不见的那一面</title><style>
body{{background:#0f1116;color:#dfe3ea;font:14px/1.65 -apple-system,Segoe UI,sans-serif;margin:24px}}
h1{{font-size:22px;margin:0 0 6px}} h2{{font-size:16px;color:#8fd3ff;margin:24px 0 8px}}
table{{border-collapse:collapse;margin:8px 0;font-size:13px}}
th,td{{border:1px solid #2a2f3a;padding:5px 9px}} th{{background:#171b23;color:#a9b3c4}}
.card{{border:1px solid #232832;border-radius:8px;padding:12px 14px;background:#12151c;margin:10px 0}}
code{{background:#171b23;padding:1px 5px;border-radius:4px}} .note{{color:#8a93a3;font-size:12px}}
.mode{{display:flex;gap:12px}} .mode > div{{flex:1}}
</style></head><body>
<h1>看不见的那一面 · V7-R1</h1>
<div class="note">批次 <code>v7_20261030_r1</code> · 审查基线 <code>4fe5281f</code> · 只读页面，不触发任何生成或付费调用</div>

<div class="card mode">
  <div><b>① 回放已有运行</b><div class="note">读取已落盘的轨迹/决策/执行记录，展示真实发生过的过程。
  入口：<code>closed_loop_*/closed_loop.json</code>、<code>matrix.jsonl</code>、<code>decision_events.jsonl</code>。</div></div>
  <div><b>② 用缓存资产重新运行</b><div class="note">对缓存候选实际跑一次 MuJoCo：
  <code>.venv/bin/python scripts/v7_rerun.py --batch {B.name} --case R03 --out runs/.../rerun_&lt;id&gt;</code>
  会生成新的 run_id、日志与结果，与回放分开列。</div></div>
</div>

<h2>看见 · 想象 · 预演 · 再观察 · 执行与揭晓</h2>
<div class="note">首视角与上传图 → 候选与未知区 → 动作矩阵/预演 → 真实行驶第二视角（或标 not_evaluated）→ 续行执行与真值揭晓。</div>

<h2>闭环分支（两条都实跑）</h2>
{rows_tbl(['运行', '分支', '矩阵格', '决策', '状态数', '真值续行成功'], [
  [c['name'], c['branch'], c['cells'], c['chosen'], c['states'], f"{c['success']}/{c['n_exec']}"]
  for c in cand])}

<h2>六方法主表（含验证初态）</h2>
{rows_tbl(['土壤', '方法', '动作', '规划成功', '验证成功', '规划初态数'], six) if six else '<div class="note">六方法结果尚未生成</div>'}

<h2>生成任务（回放用，不含付费操作）</h2>
{rows_tbl(['task_id', '对象', '模式', '采样', 'GLB SHA', '状态'], [
  [t.get('task_id'), t.get('object'), t.get('mode'), t.get('sample_id'),
   (t.get('glb_sha') or '—')[:12], t.get('status')] for t in tasks])}

<h2>限制</h2>
<ul class="note">
<li>可见面由观测约束构造，不等于 Lux3D 原始模型精度；H5-F = 观测约束 + 隐藏几何先验。</li>
<li>R01–R04 是已有对象，不是新增留出样本；同一对象多次采样是同源变体。</li>
<li>执行是独立真值仿真，不是实物机器人；月壤只接入阻力/牵引限制，无整机几何下陷。</li>
<li>A0 不计任务成功；安全停止与成功通行分列。</li>
<li>页面不显示完整隐藏真值直到揭晓步骤。</li>
</ul>
</body></html>"""
    out = B / 'media' / 'report'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'index.html').write_text(page)
    print(json.dumps({'page': str((out / 'index.html').relative_to(ROOT)),
                      'n_closed_loop': len(cand), 'n_six': len(six), 'n_tasks': len(tasks)},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
