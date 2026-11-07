"""Submit V7 imgs request as real multi-image Lux3D tasks (ordered 'imgs')."""
import hashlib,json,pathlib,sys,time,zipfile
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import imagine,lux3d_client as LC
import argparse
ap=argparse.ArgumentParser(); ap.add_argument('request'); ap.add_argument('--adopt',default='{}'); a=ap.parse_args()
ADOPT=json.loads(a.adopt); req_path=pathlib.Path(a.request).resolve(); req=json.loads(req_path.read_text()); look=req_path.parent
cache=look/'lux_cache'; cache.mkdir(parents=True,exist_ok=True)
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def glb_from(files,d):
 g=next((f for f in files if f.suffix.lower()=='.glb'),None)
 if g: return g
 z=next((f for f in files if f.suffix.lower()=='.zip'),None)
 if not z: return None
 with zipfile.ZipFile(z) as zf:
  names=[n for n in zf.namelist() if n.lower().endswith('.glb')]
  if not names: return None
  out=d/pathlib.Path(names[0]).name; out.write_bytes(zf.read(names[0])); return out
tasks=[]
for it in req['items']:
 paths=[str(ROOT/p) for p in it['paths']]
 if it['id'] in ADOPT:
  tid=int(ADOPT[it['id']]); at='adopted'
 else:
  urls=[imagine.upload_image(p) for p in paths]
  t=LC.submit_img_to_3d_multi(urls,version=req.get('version','G1-Turbo'),face_count=int(req.get('faceCount',30000)))
  tid=int(t['taskId']); at=time.strftime('%Y-%m-%dT%H:%M:%S%z')
 LC.append_ledger({'event':'v7_multi_created','task_id':tid,'item':it['id'],'inputs':it['paths'],'n_images':2,'mode':req['mode'],'request':str(req_path.relative_to(ROOT)),'adopted':it['id'] in ADOPT})
 print(json.dumps({'created':it['id'],'task_id':tid,'n_images':2}),flush=True)
 d=LC.poll(tid,timeout_s=2400); st=d.get('status'); files=[]; glb=None
 if st in (3,'success','SUCCESS'):
  us=[o['content'] for o in d.get('outputs',[]) if o.get('content')]
  files=LC.download(us,cache/str(tid)) if us else []
  glb=glb_from(files,cache/str(tid))
 dd=glb.parent if glb else None
 if glb:
  dst=ROOT/'assets/v7/lux'/str(tid)/'tex_mesh.glb'; dst.parent.mkdir(parents=True,exist_ok=True)
  dst.write_bytes(glb.read_bytes()); gsha=sha(dst)
  LC.append_ledger({'event':'v7_multi_downloaded','task_id':tid,'item':it['id'],'glb':str(dst.relative_to(ROOT)),'glb_sha256':gsha,'n_images':2})
  tasks.append({'id':it['id'],'task_id':tid,'status':'ok','submitted_at':at,'finished_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'fetched_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'glb':str(dst.relative_to(ROOT)),'glb_sha256':gsha,'inputs':[it['paths'][0],it['paths'][1]],'api_field':'imgs','n_images':2})
 else:
  LC.append_ledger({'event':'v7_multi_failed','task_id':tid,'item':it['id'],'status':st,'n_images':2})
  tasks.append({'id':it['id'],'task_id':tid,'status':'failed','submitted_at':at,'finished_at':None,'fetched_at':None,'glb':None,'glb_sha256':None,'inputs':[it['paths'][0],it['paths'][1]],'api_field':'imgs','n_images':2})
pathlib.Path(ROOT/req['result_file']).write_text(json.dumps({'tasks':tasks},indent=2))
print(json.dumps({'ok':sum(t['status']=='ok' for t in tasks),'failed':sum(t['status']=='failed' for t in tasks)}))
