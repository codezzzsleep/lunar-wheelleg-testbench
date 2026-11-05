"""Upload assets to GitHub Release v6-showcase (no secrets in repo)."""
import hashlib,json,pathlib,urllib.request,urllib.parse,sys,time
ROOT=pathlib.Path(__file__).resolve().parent.parent; API='https://api.github.com/repos/codezzzsleep/lunar-wheelleg-testbench'
def token():
 for line in (pathlib.Path.home()/'.config/gh/hosts.yml').read_text().splitlines():
  if 'oauth_token:' in line: return line.split('oauth_token:')[1].strip()
 raise SystemExit('no token')
def req(url,tok,method='GET',data=None,ctype=None):
 r=urllib.request.Request(url,data=data,method=method,headers={'Authorization':f'token {tok}','Accept':'application/vnd.github+json','User-Agent':'v6-upload'})
 if ctype: r.add_header('Content-Type',ctype)
 with urllib.request.urlopen(r,timeout=120) as f: return json.loads(f.read().decode() or '{}')
def release(tok):
 for r in req(f'{API}/releases?per_page=100',tok):
  if r['tag_name']=='v6-showcase': return r
 return req(f'{API}/releases',tok,'POST',json.dumps({'tag_name':'v6-showcase','name':'v6 showcase assets','draft':True}).encode(),'application/json')
def have(tok,rel):
 names=set(); page=1
 while True:
  rows=req(f"{API}/releases/{rel['id']}/assets?per_page=100&page={page}",tok)
  if not rows: break
  names|={r['name'] for r in rows}; page+=1
 return names
def upload(tok,rel,name,path):
 data=path.read_bytes()
 url=f"https://uploads.github.com/repos/codezzzsleep/lunar-wheelleg-testbench/releases/{rel['id']}/assets?name={urllib.parse.quote(name)}"
 r=urllib.request.Request(url,data=data,method='POST',headers={'Authorization':f'token {tok}','Content-Type':'application/octet-stream','User-Agent':'v6-upload'})
 with urllib.request.urlopen(r,timeout=600) as f: return json.loads(f.read().decode())
if __name__=='__main__':
 tok=token(); rel=release(tok); names=have(tok,rel); man=json.loads((ROOT/'dist/v6/lux3d_manifest.json').read_text())
 done=0; fail=0
 for row in man['tasks']:
  if row['status']!='recovered' or not row['release_asset']: continue
  name=row['release_asset'].replace('/','__')
  if name in names: continue
  glb=ROOT/'runs/v3/generation/cache'/row['identity']/'model.glb'
  try: upload(tok,rel,name,glb); done+=1; print('ok',name,flush=True)
  except Exception as e: fail+=1; print('fail',name,e,flush=True)
 print('uploaded',done,'failed',fail)
