"""Rebuild M0 manifest from audit + ledger recovery sets."""
import csv,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
audit=list(csv.DictReader(open(ROOT/'dist/v6/m0_audit.csv')))
led=[json.loads(l) for l in open(ROOT/'runs/v3/generation/ledger.jsonl') if l.strip()]
dl={r['id']:r for r in led if r.get('event')=='downloaded' and r.get('id')}
tasks=[]
for a in audit:
 st=a['status']
 if a['source']=='WP3' and a['id'] in dl: st='regenerated'; rel=f"v6/wp3/{a['id']}.glb"
 elif a['source']=='v3' and a['id'] in dl: st='recovered'; rel=f"v6/lux3d/{a['identity']}.glb"
 else: rel=''
 tasks.append({'id':a['id'],'task_id':a.get('task_id') or '','source':a['source'],'rock':a.get('rock',''),'view':a.get('view',''),'crop':a.get('crop',''),'variant':a.get('variant',''),'mode':'img','version':'G1-Turbo','faces':30000,'submitted_at':None,'completed_at':None,'retrieved_at':None,'input_name':'','input_sha256':'','glb_sha256':a.get('glb_sha256',''),'release_asset':rel,'status':st,'identity':a.get('identity','')})
for i,r in dl.items():
 if not str(i).startswith('v6_rebuild'): continue
 tasks.append({'id':i,'task_id':r.get('task_id') or '','source':'rebuild','rock':'','view':'','crop':'','variant':i,'mode':'img','version':'G1-Turbo','faces':30000,'submitted_at':None,'completed_at':r.get('at'),'retrieved_at':r.get('at'),'input_name':'','input_sha256':'','glb_sha256':r.get('glb_sha256',''),'release_asset':f"v6/rebuild/{i}.glb",'status':'regenerated','identity':r.get('identity','')})
(ROOT/'dist/v6/lux3d_manifest.json').write_text(json.dumps({'schema':'v6-lux3d-manifest/v1','baseline':'7d0d3cd5c','tasks':tasks},ensure_ascii=False,indent=2))
from collections import Counter
print(len(tasks),Counter(t['status'] for t in tasks),Counter(t['source'] for t in tasks if t['status']!='lost'))
