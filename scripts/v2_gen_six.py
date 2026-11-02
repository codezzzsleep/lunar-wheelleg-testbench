"""v2 六候选生成：同一首视角观测组，三种呈现 × 两次采样。

A1/A2 纹理裁剪；B1/B2 掩码合成；C1/C2 带更多地面上下文。
身份 = 观测 SHA + 输入图 SHA + version + sample_index。
失败与重复留在生成分母，不自动重提。

  python scripts/v2_gen_six.py --obs <observation dir> --rock P06 --out <dir>
"""
import argparse, hashlib, json, os, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import lux3d_client as LC

def sha(p):
    h = hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()

def load_env():
    for p in (ROOT/'.env', pathlib.Path('/var/lib/deepseek-harness/Aholo3D/.env')):
        if p.is_file():
            for line in p.read_text().splitlines():
                if line.strip() and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())

def variants(obs_dir, out):
    """三种呈现：A 纹理裁剪、B 掩码合成、C 更多地面上下文。"""
    from PIL import Image
    obs_dir = pathlib.Path(obs_dir); out.mkdir(parents=True, exist_ok=True)
    made = {}
    a = obs_dir/'crop_raw.png'
    if a.is_file():
        made['A'] = a
    b = obs_dir/'crop_white.png'
    if not b.is_file(): b = obs_dir/'masked_only.png'
    if b.is_file(): made['B'] = b
    if a.is_file():
        im = Image.open(a); w, h = im.size
        # C：向下扩展保留更多地面上下文
        big = Image.new('RGB', (w, int(h*1.45)), (16, 16, 20))
        big.paste(im, (0, 0))
        cp = out/'C_ground.png'; big.save(cp); made['C'] = cp
    return made

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True); ap.add_argument('--rock', required=True)
    ap.add_argument('--out', required=True); ap.add_argument('--version', default='G1-Turbo')
    ap.add_argument('--samples', type=int, default=2)
    ap.add_argument('--face-count', type=int, default=30000)
    a = ap.parse_args()
    load_env()
    out = ROOT/a.out; out.mkdir(parents=True, exist_ok=True)
    obs_dir = ROOT/a.obs
    obs_sha = sha(obs_dir/'observation.json')
    var = variants(obs_dir, out/'inputs')
    import imagine
    rec = {'schema':'v2-six-candidates/v1','rock':a.rock,'observation':a.obs,
           'observation_sha':obs_sha,'version':a.version,'tasks':[],'inputs':{}}
    for k, p in var.items():
        rec['inputs'][k] = {'path': str(pathlib.Path(p).relative_to(ROOT)), 'sha256': sha(p)}
    n = 0
    for k in ('A','B','C'):
        if k not in var: continue
        for s in range(a.samples):
            n += 1
            t = {'name': f'{k}{s+1}', 'group': k, 'sample_index': s,
                 'image': rec['inputs'][k]['path'], 'image_sha256': rec['inputs'][k]['sha256'],
                 'version': a.version, 'face_count': a.face_count}
            try:
                url = imagine.upload_image(str(ROOT/t['image']))
                r = LC.submit_img_to_3d(url, version=a.version, face_count=a.face_count)
                tid = r['taskId']; t['task_id'] = tid
                d = LC.poll(tid, timeout_s=1800, interval=10)
                t['status'] = d.get('status')
                urls = [o['content'] for o in (d.get('outputs') or []) if o.get('content')]
                if urls:
                    saved = LC.download(urls, out/'raw'/t['name'])
                    t['files'] = [{'path': str(p.relative_to(ROOT)), 'sha256': sha(p)} for p in saved]
                    t['ok'] = True
                else:
                    t['ok'] = False; t['error'] = 'no outputs'
            except Exception as e:
                t['ok'] = False; t['error'] = f'{type(e).__name__}: {e}'[:300]
            rec['tasks'].append(t)
            (out/'tasks.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
            print(json.dumps({k2: t.get(k2) for k2 in ('name','task_id','status','ok')},
                             ensure_ascii=False), flush=True)
    rec['n_tasks'] = len(rec['tasks'])
    rec['n_ok'] = sum(1 for t in rec['tasks'] if t.get('ok'))
    (out/'tasks.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({'n_tasks': rec['n_tasks'], 'n_ok': rec['n_ok']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
