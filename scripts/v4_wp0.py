"""WP0: build GLB/results manifest and publish to a GitHub Release."""
import argparse, hashlib, json, pathlib, re, sys, time, urllib.request, urllib.error, os
from concurrent.futures import ThreadPoolExecutor
ROOT=pathlib.Path(__file__).resolve().parent.parent
API='https://api.github.com/repos/codezzzsleep/lunar-wheelleg-testbench'

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def token():
    for line in (pathlib.Path.home()/'.config/gh/hosts.yml').read_text().splitlines():
        if 'oauth_token:' in line: return line.split('oauth_token:')[1].strip()
    raise SystemExit('no token')

def ledger_map():
    out={}
    p=ROOT/'runs/v3/generation/ledger.jsonl'
    if p.exists():
        for l in p.read_text().splitlines():
            if not l.strip(): continue
            r=json.loads(l)
            if str(r.get('id','')).startswith('stage013_') and r.get('event')=='downloaded':
                out[r['identity']]=r
    return out

def build():
    E=[]
    for d in sorted((ROOT/'runs/v3/generation/cache').iterdir()):
        if not d.is_dir(): continue
        meta={}
        if (d/'meta.json').exists(): meta=json.loads((d/'meta.json').read_text())
        sid=meta.get('state_id') or ''
        if meta:
            rock=sid.split('_h')[0] if '_h' in sid else None
            view='h'+sid.split('_h')[1] if '_h' in sid else None
            variant=meta.get('variant') or ''
            crop={'A':'tight_raw','B':'tight_masked_white','C':'context_raw'}.get(variant[:1])
            task=meta.get('task_id')
        else:
            rock,view,variant,crop,task='moon_rock_05','truth_v2',None,'input_batch',None
        for fn,kind in (('model.glb','glb'),('results.zip','results_zip')):
            p=d/fn
            if p.exists():
                E.append({'task_id':task,'identity':d.name,'kind':kind,'path':str(p.relative_to(ROOT)),
                          'sha256':sha(p),'bytes':p.stat().st_size,'source_rock':rock,'view':view,
                          'crop':crop,'variant':variant,'release_asset':f'v3/{d.name}/{fn}'})
    for f in sorted((ROOT/'runs/v3/stage007/lux3d/generation').glob('task_*/mesh/*.glb')):
        task=f.parents[1].name.replace('task_','')
        E.append({'task_id':task,'identity':f'stage007_{task}','kind':'glb',
                  'path':str(f.relative_to(ROOT)),'sha256':sha(f),'bytes':f.stat().st_size,
                  'source_rock':'moon_rock_05','view':'front_stage7','crop':'target_1536',
                  'variant':'s1c-s6','release_asset':f'stage007/{task}/tex_mesh.glb'})
    led=ledger_map()
    for d in sorted((ROOT/'runs/v3/generation/cache').iterdir()):
        if not d.is_dir() or (d/'meta.json').exists(): continue
        r=led.get(d.name,{})
        for fn,kind in (('model.glb','glb'),('results.zip','results_zip')):
            p=d/fn
            if p.exists():
                E.append({'task_id':r.get('task_id'),'identity':d.name,'kind':kind,
                          'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size,
                          'source_rock':'moon_rock_05','view':'truth_v2','crop':str(r.get('id','')).replace('stage013_',''),
                          'variant':r.get('id'),'release_asset':f'stage013_input/{d.name}/{fn}'})
    for p in sorted((ROOT/'runs/unseen/delivery_v7/v7_20261030_r1/gen_v2/P58_S2').glob('raw/*/results.zip')):
        name=p.parent.name
        E.append({'task_id':None,'identity':f'P58_S2_{name}','kind':'results_zip',
                  'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size,
                  'source_rock':'P58','view':'S2','crop':'raw','variant':name,
                  'release_asset':f'gen_v2/P58_S2/{name}/results.zip'})
    out={'schema':'v4-glb-manifest/v1','generated_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
         'entries':E,'counts':{'total':len(E),'glb':sum(e['kind']=='glb' for e in E),
         'results_zip':sum(e['kind']=='results_zip' for e in E),'bytes':sum(e['bytes'] for e in E)}}
    p=ROOT/'dist/v4/glb_manifest.json'; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    return out

def req(url, tok, method='GET', data=None, ctype=None):
    r=urllib.request.Request(url,method=method,data=data)
    r.add_header('Authorization',f'bearer {tok}')
    r.add_header('Accept','application/vnd.github+json')
    if ctype: r.add_header('Content-Type',ctype)
    with urllib.request.urlopen(r,timeout=600) as f:
        return json.loads(f.read().decode())

def ensure_release(tok):
    for r in req(f'{API}/releases',tok):
        if r.get('tag_name')=='v4-data': return r
    return req(f'{API}/releases',tok,'POST',json.dumps({'tag_name':'v4-data','name':'v4 data (GLB/results)','draft':True}).encode(),'application/json')

def existing_names(tok, rel):
    out=set(); page=1
    while True:
        rows=req(f"{API}/releases/{rel['id']}/assets?per_page=100&page={page}",tok)
        out |= {a['name'] for a in rows}
        if len(rows)<100: break
        page+=1
    return out

def upload_one(tok, rel, e):
    name=e['release_asset'].replace('/','__')
    p=ROOT/e['path']; data=p.read_bytes()
    url=f"https://uploads.github.com/repos/codezzzsleep/lunar-wheelleg-testbench/releases/{rel['id']}/assets?name={name}"
    for k in range(4):
        try:
            req(url,tok,'POST',data,'application/octet-stream'); return 'ok'
        except Exception as ex:
            if k==3: return f'FAIL {ex}'
            time.sleep(5*(k+1))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--build',action='store_true'); ap.add_argument('--upload',action='store_true')
    a=ap.parse_args()
    man=build(); print(json.dumps(man['counts']))
    if a.upload:
        tok=token(); rel=ensure_release(tok); print('release',rel['id'])
        log=ROOT/'dist/v4/upload_log.jsonl'
        have=existing_names(tok,rel)
        todo=[(i,e) for i,e in enumerate(man['entries']) if e['release_asset'].replace('/','__') not in have]
        print('todo',len(todo),'existing',len(have),flush=True)
        def work(item):
            i,e=item; st=upload_one(tok,rel,e)
            with log.open('a') as f: f.write(json.dumps({'i':i,'asset':e['release_asset'],'status':st,'sha256':e['sha256']})+'\n')
            print(i,st,e['release_asset'],flush=True); return st
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(work,todo))
    return 0
if __name__=='__main__': sys.exit(main())
