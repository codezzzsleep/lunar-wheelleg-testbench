"""Archive rebuilt v6_rebuild GLBs in time order and inventory."""
import csv,hashlib,json,os,pathlib,shutil,time
ROOT=pathlib.Path(__file__).resolve().parent.parent
rows=[json.loads(l) for l in open(ROOT/'runs/v3/generation/ledger.jsonl') if l.strip()]
rows=[r for r in rows if str(r.get('id','')).startswith('v6_rebuild')]
created={}; downloaded={}; ident={}
for r in rows:
 i=r.get('id')
 if r.get('event')=='created': created[i]=r
 if r.get('event')=='downloaded': downloaded[i]=r
 if r.get('identity'): ident[i]=r['identity']
out=ROOT/'assets/v6/rebuild'; out.mkdir(parents=True,exist_ok=True); inv=[]
for i,r in downloaded.items():
 d=ROOT/'runs/v3/generation/cache'/ident[i]
 glb=d/'model.glb'
 if not glb.exists(): continue
 dst=out/ident[i]; dst.mkdir(exist_ok=True)
 if not (dst/'model.glb').exists(): os.link(glb,dst/'model.glb')
 if (d/'meta.json').exists() and not (dst/'meta.json').exists(): shutil.copy2(d/'meta.json',dst/'meta.json')
 h=hashlib.sha256((dst/'model.glb').read_bytes()).hexdigest()
 rec={'id':i,'state':i.split('_')[3] if False else '', 'identity':ident[i],'task_id':r.get('task_id'),'submitted_at':(created.get(i) or {}).get('at'),'downloaded_at':r.get('at'),'sha256':h,'bytes':(dst/'model.glb').stat().st_size,'path':str((dst/'model.glb').relative_to(ROOT)),'release':f'v6/rebuild/{i}.glb'}
 inv.append(rec)
p=ROOT/'dist/v6/rebuild_inventory.csv'
with p.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(inv[0].keys())); w.writeheader(); w.writerows(inv)
print('archived',len(inv))
