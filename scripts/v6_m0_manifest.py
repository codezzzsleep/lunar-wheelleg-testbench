"""M0 manifest: combine audit with ledger timestamps and release naming."""
import csv,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
led=[json.loads(l) for l in (ROOT/'runs/v3/generation/ledger.jsonl').read_text().splitlines() if l.strip()]
by_id={}
for r in led:
 if r.get('identifier') or r.get('id'): by_id.setdefault(r.get('id'),[]).append(r)
audit=list(csv.DictReader(open(ROOT/'dist/v6/m0_audit.csv')))
rows=[]
for a in audit:
 recs=by_id.get(a['id'],[])
 def last(ev):
  xs=[r for r in recs if r.get('event')==ev]
  return xs[-1].get('at') if xs else None
 glb=ROOT/'runs/v3/generation/cache'/a['identity']/'model.glb'
 meta=ROOT/'runs/v3/generation/cache'/a['identity']/'meta.json'
 tid=None
 if meta.exists(): tid=json.loads(meta.read_text()).get('task_id')
 rows.append({'task_id':tid or a.get('task_id') or '',
  'source':a['source'],'rock':a['rock'],'view':a['view'],'crop':a['crop'],'variant':a['variant'],
  'mode':'img','version':'G1-Turbo','faces':30000,
  'submitted_at':last('created'),'completed_at':last('downloaded'),'retrieved_at':last('downloaded'),
  'input_name':pathlib.Path(a['id']).name+'.png','input_sha256':a.get('input_sha_ok') and a.get('identity') or '',
  'glb_sha256':a.get('glb_sha256') or '','release_asset':f"v6/lux3d/{a['id']}.glb" if a['status']=='recovered' else '',
  'status':a['status'],'identity':a['identity']})
out=ROOT/'dist/v6/lux3d_manifest.json'
out.write_text(json.dumps({'schema':'v6-lux3d-manifest/v1','baseline':'7d0d3cd5c','tasks':rows},ensure_ascii=False,indent=2))
from collections import Counter
print(Counter(r['status'] for r in rows),'total',len(rows))
