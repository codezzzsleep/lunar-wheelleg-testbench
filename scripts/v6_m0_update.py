"""Update M0 manifest with WP3 recovered and v6_rebuild entries."""
import csv,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
led=[json.loads(l) for l in open(ROOT/'runs/v3/generation/ledger.jsonl') if l.strip()]
dl={r['id'] for r in led if r.get('event')=='downloaded' and r.get('id')}
man=json.loads((ROOT/'dist/v6/lux3d_manifest.json').read_text())
for t in man['tasks']:
 if t['source']=='WP3' and t['id'] in dl: t['status']='regenerated'; t['release_asset']=f"v6/wp3/{t['id']}.glb"
for r in led:
 if not str(r.get('id','')).startswith('v6_rebuild') or r.get('event')!='downloaded': continue
 man['tasks'].append({'task_id':r.get('task_id'),'source':'rebuild','rock':'','view':'','crop':'','variant':r.get('id'),'mode':'img','version':'G1-Turbo','faces':30000,'submitted_at':None,'completed_at':r.get('at'),'retrieved_at':r.get('at'),'input_name':'','input_sha256':'','glb_sha256':r.get('glb_sha256',''),'release_asset':f"v6/rebuild/{r['id']}.glb",'status':'regenerated','identity':r.get('identity')})
(ROOT/'dist/v6/lux3d_manifest.json').write_text(json.dumps(man,ensure_ascii=False,indent=2))
from collections import Counter
print(len(man['tasks']),Counter(t['status'] for t in man['tasks']))
