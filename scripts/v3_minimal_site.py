"""G6：生成不依赖旧 bundle 的最小静态交付页 dist/minimal/index.html。"""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                               text=True).strip()
rows = [
    ('A 控制接口', '通过', 'v3_selftest_command：pass, stand_err 0.0087, restore_diff 0.0'),
    ('B 基础周期', '通过', 'runs/v3/basic_cycle/*：8 run，168/168 检查'),
    ('C 预演保真', '部分', 'isolation5_r3：五臂 physical_failure，A-B 第 72 步分叉'),
    ('D 腿式能力', '未通过', 'CLIMB 未完成；D3 原始 1/2、扰动 2/3'),
    ('E 主角对照', '无正例', '14 例：双方成功 12、仅 FULL 成功 0、选择不同 1'),
    ('F 连续路线', '通过', '20 m：rigid 23.5482/100.26 s；nominal 23.5375/106.6 s'),
]
tr = '\n'.join(f'<tr><td>{a}</td><td class="s">{b}</td><td>{c}</td></tr>' for a, b, c in rows)
html = f'''<!doctype html>
<html lang="zh"><meta charset="utf-8"><title>Lunar wheel-leg testbench — G6</title>
<style>
body{{font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;max-width:920px;margin:40px auto;padding:0 20px;color:#1c1c1e}}
h1{{font-size:26px}} h2{{font-size:18px;margin-top:28px}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #ddd;padding:8px;vertical-align:top}}
.s{{font-weight:600}} code,pre{{background:#f5f5f7;border-radius:6px}} pre{{padding:10px;overflow:auto}}
.note{{color:#666;font-size:13px}}
</style>
<h1>Lunar wheel-leg testbench — G6 交付页</h1>
<p class="note">HEAD <code>{head}</code> · 2026-11-03 · 最小可复现交付（不依赖旧 bundle）</p>
<h2>状态矩阵</h2>
<table><tr><th>工作包</th><th>状态</th><th>证据</th></tr>
{tr}
</table>
<h2>复现</h2>
<pre>MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_route.py --soil nominal --out runs/v3/route/nominal_r1
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_selftest_command.py</pre>
<h2>详细文档</h2>
<ul>
<li><a href="../../docs/G6_DELIVERY.md">G6 交付页（Markdown）</a></li>
<li><a href="../../docs/G6_STATUS.md">状态矩阵</a></li>
<li><a href="../../docs/BOUNDARY.md">能力边界</a></li>
<li><a href="../../docs/EVIDENCE_INDEX.md">证据索引（57 run）</a></li>
<li><a href="../../docs/CONSISTENCY.md">一致性检查</a></li>
</ul>
<h2>不应被误读</h2>
<ul>
<li>D 未通过：CLIMB 未完成，D3 腿式未达 3/3。</li>
<li>E 无正例：没有“FULL 成功而 OBS 失败”的案例。</li>
<li>20 m 路线是纯轮式，不是腿式价值证据。</li>
<li>旧 bundle 未重建；发布通道缺 git-lfs/gh/token。</li>
</ul>
</html>
'''
out = ROOT / 'dist/minimal/index.html'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html)
print({'out': str(out), 'bytes': out.stat().st_size, 'head': head})
