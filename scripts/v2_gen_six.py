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
    full = obs_dir/'rgb.png'
    if full.is_file():
        # C：从完整观测图裁出**真正的更大范围**（含更多地面），不是补纯色边
        im = Image.open(full); w, h = im.size
        box = (0, 0, w, int(h*0.98))
        cp = out/'C_ground.png'
        im.crop(box).save(cp)
        made['C'] = cp
    return made

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True); ap.add_argument('--rock', required=True)
    ap.add_argument('--state', default='')
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
    prev = {}
    if (out / 'tasks.json').is_file():
        try:
            for t in json.loads((out / 'tasks.json').read_text()).get('tasks', []):
                prev[t.get('name')] = t
        except Exception:
            prev = {}

    def files_ok(t):
        fs = t.get('files') or []
        return bool(fs) and all((ROOT / f['path']).is_file() for f in fs)

    def poll_and_save(t, tid):
        tag = f'v2-six:{a.rock}:{a.state}:{t["name"]}'
        d = LC.poll(tid, timeout_s=1800, interval=10)
        t['status'] = d.get('status')
        t['consumed_credits'] = (d.get('consumedCredits')
                                 if d.get('consumedCredits') is not None
                                 else d.get('consumed_credits'))
        urls = [o['content'] for o in (d.get('outputs') or []) if o.get('content')]
        if urls:
            saved = LC.download(urls, out / 'raw' / t['name'])
            t['files'] = [{'path': str(p.relative_to(ROOT)), 'sha256': sha(p)}
                          for p in saved]
            t['ok'] = True
            t.pop('error', None)
        else:
            t['ok'] = False
            t['error'] = 'no outputs'
        if not t.get('ledger_completed'):
            LC.append_ledger({'event': 'completed', 'brief': tag, 'task_id': tid,
                              'status': t['status'],
                              'consumed_credits': t['consumed_credits'],
                              'ok': t['ok'],
                              'local_dir': str((out / 'raw' / t['name']).relative_to(ROOT))})
            t['ledger_completed'] = True
        return t

    def submit(t):
        for attempt in range(40):
            try:
                url = imagine.upload_image(str(ROOT / t['image']))
                r = LC.submit_img_to_3d(url, version=a.version,
                                        face_count=a.face_count)
                return r['taskId']
            except Exception as e:
                msg = f'{type(e).__name__}: {e}'
                if '并发上限' in msg or 'concurrency' in msg.lower():
                    time.sleep(20 + min(attempt, 10) * 2)
                    continue
                raise
        raise RuntimeError('创建任务重试耗尽：并发上限持续未释放')

    n = 0
    for k in ('A', 'B', 'C'):
        if k not in var:
            continue
        for s in range(a.samples):
            n += 1
            t = {'name': f'{k}{s+1}', 'group': k, 'sample_index': s,
                 'image': rec['inputs'][k]['path'],
                 'image_sha256': rec['inputs'][k]['sha256'],
                 'version': a.version, 'face_count': a.face_count}
            old = prev.get(t['name'])
            if old and old.get('ok') and files_ok(old):
                rec['tasks'].append(old)
                print(json.dumps({'name': t['name'], 'status': 'reused',
                                  'task_id': old.get('task_id')}, ensure_ascii=False),
                      flush=True)
                continue
            if old:
                t.update({k2: old.get(k2) for k2 in
                          ('task_id', 'status', 'consumed_credits', 'files', 'ok',
                           'error', 'ledger_completed')})
            try:
                if not t.get('task_id'):
                    tid = submit(t)
                    t['task_id'] = tid
                    tag = f'v2-six:{a.rock}:{a.state}:{t["name"]}'
                    LC.append_ledger({'event': 'submitted', 'brief': tag,
                                      'task_id': tid, 'estimated_credits': 1,
                                      'image_sha256': t['image_sha256'],
                                      'observation_sha': obs_sha,
                                      'note': 'image-to-3d; 1 credit/task 按既有账本口径'})
                else:
                    tid = t['task_id']
                poll_and_save(t, tid)
            except Exception as e:
                t['ok'] = False
                t['error'] = f'{type(e).__name__}: {e}'[:300]
            rec['tasks'].append(t)
            (out / 'tasks.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
            print(json.dumps({k2: t.get(k2) for k2 in
                              ('name', 'task_id', 'status', 'ok')},
                             ensure_ascii=False), flush=True)
    rec['n_tasks'] = len(rec['tasks'])
    rec['n_ok'] = sum(1 for t in rec['tasks'] if t.get('ok'))
    (out / 'tasks.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({'n_tasks': rec['n_tasks'], 'n_ok': rec['n_ok']},
                     ensure_ascii=False))

if __name__ == '__main__':
    main()
