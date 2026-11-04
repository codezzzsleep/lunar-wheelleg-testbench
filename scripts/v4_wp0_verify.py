"""WP0 验收：Release digest 全量核对 + 抽样下载 + 稀疏 clone 读 manifest。"""
import hashlib, json, pathlib, sys, tempfile, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parent.parent
API='https://api.github.com/repos/codezzzsleep/lunar-wheelleg-testbench'
TAG='v4-data'
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
def get(u):
    r=urllib.request.Request(u); r.add_header('Accept','application/vnd.github+json')
    with urllib.request.urlopen(r,timeout=120) as f: return json.loads(f.read().decode())
def main():
    man=json.loads((ROOT/'dist/v4/glb_manifest.json').read_text())
    rel=[r for r in get(f'{API}/releases') if r['tag_name']==TAG][0]
    assets={}; page=1
    while True:
        rows=get(f"{API}/releases/{rel['id']}/assets?per_page=100&page={page}")
        if not rows: break
        assets.update({a['name']:a for a in rows}); page+=1
    out={'release':TAG,'url':rel['html_url'],'assets':len(assets),'entries':len(man['entries']),
         'digest_ok':0,'digest_fail':[],'size_fail':[],'missing':[],'sample':{}}
    for e in man['entries']:
        name=e['release_asset'].replace('/','__'); a=assets.get(name)
        if not a: out['missing'].append(e['release_asset']); continue
        dg=(a.get('digest') or '').replace('sha256:','')
        if dg==e['sha256']: out['digest_ok']+=1
        else: out['digest_fail'].append({'asset':e['release_asset'],'api':dg,'manifest':e['sha256']})
        if a.get('size')!=e['bytes']: out['size_fail'].append(e['release_asset'])
    # 抽样下载覆盖三个来源
    picks=[]
    for pref in ('v3/','stage007/','stage013_input/','gen_v2/'):
        for e in man['entries']:
            if e['release_asset'].startswith(pref): picks.append(e); break
    tmp=pathlib.Path(tempfile.mkdtemp(prefix='v4s_'))
    for e in picks:
        a=assets[e['release_asset'].replace('/','__')]; p=tmp/'x'
        with urllib.request.urlopen(a['browser_download_url'],timeout=600) as r,p.open('wb') as f:
            while True:
                b=r.read(1<<20)
                if not b: break
                f.write(b)
        out['sample'][e['release_asset']]= (sha(p)==e['sha256'])
        p.unlink()
    out['pass']=bool(out['digest_ok']==len(man['entries']) and not out['missing']
                     and not out['digest_fail'] and not out['size_fail'] and all(out['sample'].values()))
    (ROOT/'dist/v4/verify.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({'pass':out['pass'],'digest_ok':out['digest_ok'],'missing':len(out['missing']),
                      'digest_fail':len(out['digest_fail']),'size_fail':len(out['size_fail']),
                      'sample':out['sample']},ensure_ascii=False))
    return 0 if out['pass'] else 1
if __name__=='__main__': sys.exit(main())
