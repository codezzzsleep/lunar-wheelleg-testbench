"""五画面页（石头网格版）：看见→想象→试走→决定→真走与揭晓。"""
import argparse, base64, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent

def img(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return ''
    return 'data:image/png;base64,' + base64.b64encode(p.read_bytes()).decode()

def frames(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        q = r.get('qpos')
        if isinstance(q, list) and q:
            out.append({'t': r.get('t'), 'x': round(float(q[0]), 3),
                        'z': round(float(q[2]), 3) if len(q) > 2 else 0.0})
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--state', default='P06|S1')
    a = ap.parse_args()
    g = pathlib.Path(a.grid)
    d = json.loads((g / 'summary.json').read_text())
    st = next(s for s in d['states'] if s['state'] == a.state)
    rid, sid = a.state.split('|')
    obs = g / rid / sid / 'obs' / 'rgb.png'
    fam_rows = ''.join(
        f"<tr class=\"{'pass' if f['success'] else ('ab' if f['chosen']=='A0' else 'fail')}\">"
        f"<td>{n}</td><td>{f['chosen']}</td>"
        f"<td>{'通行' if f['success'] else ('安全放弃' if f['chosen']=='A0' else '失败')}</td>"
        f"<td>{f['cells'] if f['cells'] is not None else '—'}</td>"
        f"<td>{f['errors']}</td></tr>" for n, f in st['families'].items())
    truth = st['families']['U_truth']
    fr = frames(g / rid / sid / 'U_truth' / 'trajectory.jsonl')
    data = json.dumps(fr)
    html = f"""<!doctype html><meta charset="utf-8"><title>石头网格 · {a.state}</title>
<style>body{{background:#0e1117;color:#e6e9ef;font:15px/1.7 system-ui;margin:0}}
section{{padding:20px 28px;border-bottom:1px solid #1c222d}}h2{{color:#9fd2ff;font-size:16px}}
table{{border-collapse:collapse;font-size:13px}}td,th{{border-bottom:1px solid #1c222d;padding:5px 10px}}
tr.pass td{{color:#7ee0a1}}tr.fail td{{color:#ff9d9d}}tr.ab td{{color:#c9b26b}}
img{{max-width:620px;border:1px solid #232a36;border-radius:6px}}
canvas{{background:#0a0d13;border:1px solid #232a36;border-radius:6px}}</style>
<section><h2>1 看见</h2><div>状态 {a.state} · 类别 {st['class']} · 可见量 H={st['applied'].get('soil_label')}</div>
<img src="{img(obs)}" alt="observation"></section>
<section><h2>2 想象</h2><div>同一观测下的八种几何假设：规则、方盒、镜像、2.5D×2、H5_raw、H5_F、真值。</div></section>
<section><h2>3 试走</h2><table><tr><th>家族</th><th>决策</th><th>结果</th><th>预演格</th><th>错误</th></tr>{fam_rows}</table></section>
<section><h2>4 决定</h2><div>真值参考选择 <b>{truth['chosen']}</b>，结果：{'通行' if truth['success'] else '未通行'}。</div></section>
<section><h2>5 真走与揭晓</h2><canvas id="cv" width="700" height="180"></canvas>
<div><button id="p">播放</button><button id="s">暂停</button></div>
<script>const F={data};const c=document.getElementById('cv'),x=c.getContext('2d');let i=0,t=null;
function d(i){{const f=F[i]||F[0];if(!f)return;x.clearRect(0,0,700,180);
x.fillStyle='#9fd2ff';x.beginPath();x.arc(40+f.x*150,140-f.z*200,7,0,6.283);x.fill();
x.fillStyle='#8b95a7';x.font='12px monospace';x.fillText('x='+f.x+' t='+f.t,40,20);}}
document.getElementById('p').onclick=()=>{{if(t)return;t=setInterval(()=>{{i=(i+3)%Math.max(1,F.length);d(i);}},40);}};
document.getElementById('s').onclick=()=>{{clearInterval(t);t=null;}};d(0);</script>"""
    pathlib.Path(a.out).write_text(html, encoding='utf-8')
    print(json.dumps({'out': a.out, 'frames': len(fr), 'state': a.state}))

if __name__ == '__main__':
    main()
