"""B3: showcase manifest (paths, sha256, source command) without copying large binaries."""
import hashlib,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
def ident_of(t):
 parts=[t['variant'],str(t['model'].get('version','G1-Turbo')),str(int(t['model'].get('face_count',30000))),str(int(t.get('repeat_idx',0))),t['image_sha256']]
 return hashlib.sha256('\n'.join(parts).encode()).hexdigest()
def sha(p):
 h=hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()
items=[]
def add(path,kind,source):
 p=ROOT/path
 if p.exists() and p.is_file(): items.append({'path':path,'kind':kind,'sha256':sha(p),'bytes':p.stat().st_size,'source':source})
add('runs/v5/c0/known_answer.csv','C0 known answers','python3 scripts/v5_c0_ka.py')
add('runs/v5/c0/v3_refuse.csv','C0 v3 re-fusion','python3 scripts/v5_c0_refuse.py')
add('configs/v5_admission.json','C0 admission','frozen calibration')
add('runs/v5/c3/checkup.csv','C3 checkup','python3 scripts/v5_c3.py')
add('runs/v5/ka8/ka8.json','A KA8','python3 scripts/v5_ka8.py')
add('runs/v5/a_r3/a_table_all.csv','A four-width table','python3 scripts/v5_a_r3.py; python3 scripts/v5_a_merge.py')
add('runs/v5/c2_a/moon_rock_02_h2v1_0.9/result.json','C2 A negative','python3 scripts/v5_c2_r2.py --state moon_rock_02_h2v1 --channel 0.9')
add('runs/v5/b1/moon_rock_05_h2v1_1.2/result.json','B1 open field','python3 scripts/v5_c2_r2.py --state moon_rock_05_h2v1 --channel 1.2')
add('runs/v5/c2_narrow/rock_07_h0v0/result.json','C2 narrow negative','python3 scripts/v5_c2.py --states rock_07_h0v0 --channel 0.35')
for p in sorted((ROOT/'runs/v4/wp7').glob('*.json')):
 if p.name.endswith('.json'): add(str(p.relative_to(ROOT)),'WP7 scene',p.name)
# C3 six GLBs per rock from task identities
tasks=json.loads((ROOT/'runs/v4/wp3/tasks.json').read_text())['tasks']
seen=set()
for t in tasks:
 if int(t.get('view_yaw_deg',0))!=0: continue
 import sys; sys.path.insert(0,str(ROOT/"scripts")); import v3_generate as VG
 ident=ident_of(t); g=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
 if g.exists() and t['rock'] not in seen:
  pass
# list all yaw0 GLBs that exist
for t in tasks:
 if int(t.get('view_yaw_deg',0))!=0: continue
 import sys; sys.path.insert(0,str(ROOT/"scripts")); import v3_generate as VG
 g=ROOT/'runs/v3/generation/cache'/ident_of(t)/'model.glb'
 if g.exists():
  rel=str(g.relative_to(ROOT))
  if not any(i['path']==rel for i in items): items.append({'path':rel,'kind':'C3 GLB','sha256':sha(g),'bytes':g.stat().st_size,'source':'Lux3D G1-Turbo, tasks runs/v4/wp3/tasks.json'})
out=ROOT/'dist/v5/showcase'; out.mkdir(parents=True,exist_ok=True)
(out/'manifest.json').write_text(json.dumps({'schema':'v5-showcase/v1','generated':__import__('time').strftime('%Y-%m-%dT%H:%M:%S%z'),'items':items,'missing':{'B2':'two-encounter route not rebuilt after sandbox recycle'},'notes':'GLB binaries are referenced from the repo cache; upload target is Release v5-showcase'},ensure_ascii=False,indent=2))
print('items',len(items),'bytes',sum(i['bytes'] for i in items))
