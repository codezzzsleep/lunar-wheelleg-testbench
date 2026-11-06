"""Archive the 144 regenerated WP3 GLBs locally with task/time inventory."""
import csv,hashlib,json,os,pathlib,shutil
ROOT=pathlib.Path(__file__).resolve().parent.parent
rows=[json.loads(l) for l in open('runs/v3/generation/ledger.jsonl') if l.strip()]
rows=[r for r in rows if str(r.get('id','')).startswith('v4_')]
created={}; dl={}
for r in rows:
 i=r.get('id')
 if r.get('event')=='created': created[i]=r
 if r.get('event')=='downloaded': dl[i]=r
out=ROOT/'assets/v6/wp3'; out.mkdir(parents=True,exist_ok=True); inv=[]
for i,r in dl.items():
 ident=next((x.get('identity') for x in rows if x.get('id')==i and x.get('identity')), None)
 if not ident: continue
 src=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
 if not src.exists(): continue
 dst=out/ident; dst.mkdir(exist_ok=True)
 if not (dst/'model.glb').exists(): os.link(src,dst/'model.glb')
 if (src.parent/'meta.json').exists() and not (dst/'meta.json').exists(): shutil.copy2(src.parent/'meta.json',dst/'meta.json')
 h=hashlib.sha256((dst/'model.glb').read_bytes()).hexdigest()
 task=i.replace('v4_','',1)
 parts=task.split('_'); rock='_'.join(parts[:2]) if parts[0].startswith('moon') else 'rock_07'
 inv.append({'id':i,'identity':ident,'task_id':r.get('task_id'),'submitted_at':(created.get(i) or {}).get('at'),'downloaded_at':r.get('at'),'sha256':h,'bytes':(dst/'model.glb').stat().st_size,'path':str((dst/'model.glb').relative_to(ROOT)),'release':f'v6/wp3/{i}.glb','rock':rock})
inv.sort(key=lambda x:x['downloaded_at'])
p=ROOT/'dist/v6/wp3_inventory.csv'; p.parent.mkdir(parents=True,exist_ok=True)
with p.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(inv[0].keys())); w.writeheader(); w.writerows(inv)
print('archived',len(inv))
