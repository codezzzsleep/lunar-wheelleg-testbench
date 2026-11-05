"""M0 audit: enumerate Lux3D tasks, verify cached GLB/input shas, flag recoverable/lost."""
import csv,hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v3_generate as G
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def ident(t):
 parts=[t['variant'],str(t['model'].get('version','G1-Turbo')),str(int(t['model'].get('face_count',30000))),str(int(t.get('repeat_idx',0))),t['image_sha256']]
 return hashlib.sha256('\n'.join(parts).encode()).hexdigest()
tasks=[]
wp3=json.loads((ROOT/'runs/v4/wp3/tasks.json').read_text())['tasks']
for t in wp3: tasks.append({'source':'WP3','task':t})
for p in sorted((ROOT/'runs/v5/c2').glob('*/tasks*.json')):
 for t in json.loads(p.read_text())['tasks']: tasks.append({'source':'C2','task':t})
# ledger v3 tasks (generation tasks json if exists)
for p in [ROOT/'runs/v3/generation/tasks.json']:
 if p.exists():
  for t in json.loads(p.read_text())['tasks']: tasks.append({'source':'v3','task':t})
rows=[]; seen=set()
for e in tasks:
 t=e['task']; i=ident(t)
 if i in seen: continue
 seen.add(i)
 glb=ROOT/'runs/v3/generation/cache'/i/'model.glb'; meta=ROOT/'runs/v3/generation/cache'/i/'meta.json'
 img=pathlib.Path(t['image']) if pathlib.Path(t['image']).is_absolute() else ROOT/t['image']
 rec={'source':e['source'],'id':t['id'],'variant':t['variant'],'rock':t.get('rock'),'view':t.get('view_yaw_deg'),'crop':t.get('crop'),'identity':i,
      'glb_exists':glb.exists(),'input_exists':img.exists(),'input_sha_ok':img.exists() and sha(img)==t['image_sha256']}
 if glb.exists():
  rec['glb_sha256']=sha(glb)
  rec['glb_sha_ok']=None
  if meta.exists():
   m=json.loads(meta.read_text()); rec['task_id']=m.get('task_id'); rec['glb_sha_ok']=m.get('glb_sha256')==rec['glb_sha256']
 rec['status']='recovered' if rec['glb_exists'] and rec.get('glb_sha_ok') != False else ('regenerable' if rec['input_exists'] and rec['input_sha_ok'] else 'lost')
 rows.append(rec)
out=ROOT/'dist/v6'; out.mkdir(parents=True,exist_ok=True)
with (out/'m0_audit.csv').open('w',newline='') as f:
 fields=['source','id','variant','rock','view','crop','identity','task_id','glb_exists','input_exists','input_sha_ok','glb_sha256','glb_sha_ok','status']
 w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([{k:r.get(k) for k in fields} for r in rows])
from collections import Counter
print('tasks',len(rows),Counter(r['status'] for r in rows)); print(Counter(r['source'] for r in rows))
print('missing inputs',sum(1 for r in rows if not r['input_exists']))
