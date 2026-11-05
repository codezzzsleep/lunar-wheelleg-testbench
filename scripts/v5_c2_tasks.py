"""Build 6 Lux3D tasks for a state's own observation variants (C2 supplement)."""
import json,pathlib,sys,hashlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
state=sys.argv[1] if len(sys.argv)>1 else 'rock_07_h1v1'
d=ROOT/'runs/v3/states'/state/'observation'/'gen'/'variants'
vj=json.loads((d/'variants.json').read_text())
tasks=[]
for order,(var,rec) in enumerate(sorted(vj['variants'].items()),1):
 p=ROOT/rec['path'] if not str(rec['path']).startswith('/') else pathlib.Path(rec['path'])
 if not p.exists(): p=d/f'{var}.png'
 tasks.append({'id':f'v5_{state}_{var}','state_id':state,'variant':var,'repeat_idx':int(rec.get('repeat_idx',0)),
  'image':str(p),'image_sha256':rec['sha256'],'model':{'version':'G1-Turbo','face_count':30000},'create_order':order,'estimated_credits':20.0})
out=ROOT/'runs/v5/c2'/state/'tasks.json'; out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'schema':'v3-generation-tasks/v1','state':state,'n':len(tasks),'tasks':tasks},ensure_ascii=False,indent=2))
print(json.dumps({'n':len(tasks),'out':str(out),'first':tasks[0]['image']}))
