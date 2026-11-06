"""Preserve every found Lux3D asset in time order under assets/v6/archive (hardlinks)."""
import csv,hashlib,json,os,pathlib,time,shutil
ROOT=pathlib.Path(__file__).resolve().parent.parent; store=ROOT/'assets/v6/lux3d'; arch=ROOT/'assets/v6/archive'; arch.mkdir(parents=True,exist_ok=True)
def sha(p):
 h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()
ledger={}
for p in [ROOT/'runs/v3/generation/ledger.jsonl',ROOT/'runs/v4/wp3/ledger_first36.jsonl']:
 if not p.exists(): continue
 for l in p.read_text().splitlines():
  if not l.strip(): continue
  r=json.loads(l); i=r.get('identity')
  if not i: continue
  ledger.setdefault(i,[]).append(r)
audit={r['identity']:r for r in csv.DictReader(open(ROOT/'dist/v6/m0_audit.csv'))} if (ROOT/'dist/v6/m0_audit.csv').exists() else {}
rows=[]
for d in sorted(store.iterdir()):
 if not (d/'model.glb').exists(): continue
 i=d.name; meta={}
 if (d/'meta.json').exists(): meta=json.loads((d/'meta.json').read_text())
 ev=ledger.get(i,[])
 def evt(name):
  xs=[r.get('at') for r in ev if r.get('event')==name]
  return xs[-1] if xs else None
 stamp=meta.get('downloaded_at') or evt('downloaded') or evt('created') or time.strftime('%Y-%m-%dT%H:%M:%S%z',time.localtime((d/'model.glb').stat().st_mtime))
 try:
  from datetime import datetime
  epoch=datetime.strptime(stamp,'%Y-%m-%dT%H:%M:%S%z').timestamp()
 except Exception:
  epoch=(d/'model.glb').stat().st_mtime
 label=time.strftime('%Y%m%dT%H%M%S',time.localtime(epoch))
 ad=arch/f'{label}_{i}'; ad.mkdir(exist_ok=True)
 glb=ad/'model.glb'
 if not glb.exists(): os.link(d/'model.glb',glb)
 if (d/'meta.json').exists() and not (ad/'meta.json').exists(): shutil.copy2(d/'meta.json',ad/'meta.json')
 rec={'identity':i,'task_id':meta.get('task_id'),'submitted_at':evt('created'),'downloaded_at':stamp,'source':(audit.get(i) or {}).get('source','unknown'),
      'rock':(audit.get(i) or {}).get('rock'),'view':(audit.get(i) or {}).get('view'),'crop':(audit.get(i) or {}).get('crop'),
      'sha256':sha(glb),'bytes':glb.stat().st_size,'archive_path':str(glb.relative_to(ROOT)),'release_asset':f'v6/lux3d/{i}.glb'}
 (ad/'record.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2)); rows.append((epoch,rec))
rows.sort(key=lambda x:x[0])
inv=ROOT/'dist/v6/archive_inventory.csv'; inv.parent.mkdir(parents=True,exist_ok=True)
with inv.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['seq','archived_at']+list(rows[0][1].keys())); w.writeheader()
 for n,(e,r) in enumerate(rows,1): w.writerow({'seq':n,'archived_at':time.strftime('%Y-%m-%dT%H:%M:%S%z',time.localtime(e)),**r})
# rocks tar
rocks=ROOT/'assets/v6/rocks'; rocks.mkdir(parents=True,exist_ok=True)
src=pathlib.Path('/tmp/v6_assets_v3.tar.gz')
if src.exists() and not (rocks/'assets_v3_rocks.tar.gz').exists(): shutil.copy2(src,rocks/'assets_v3_rocks.tar.gz')
print('archived',len(rows),'oldest',rows[0][1]['downloaded_at'],'newest',rows[-1][1]['downloaded_at'])
