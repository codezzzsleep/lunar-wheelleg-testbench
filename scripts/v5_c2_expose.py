"""Auto-expose a state's variants and build 6 Lux3D tasks (review R1)."""
import json,pathlib,hashlib,sys
import numpy as np
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent; state=sys.argv[1] if len(sys.argv)>1 else 'rock_07_h1v1'
d=ROOT/'runs/v3/states'/state/'observation'/'gen'/'variants'; vj=json.loads((d/'variants.json').read_text()); new=[]
for i,(var,rec) in enumerate(sorted(vj['variants'].items()),1):
 src=d/f'{var}.png'; im=np.asarray(Image.open(src).convert('RGB')).astype(np.float32); m=float(im.mean())
 dst=ROOT/'runs/v5/c2'/state/'exposed'/f'{var}.png'; dst.parent.mkdir(parents=True,exist_ok=True)
 out=np.clip(im*(130.0/max(m,1e-6)),0,255).astype(np.uint8) if m<100 else im.astype(np.uint8)
 Image.fromarray(out).save(dst); h=hashlib.sha256(dst.read_bytes()).hexdigest()
 new.append({'id':f'v5_{state}_{var}_exposed','state_id':state,'variant':var+'_exposed','repeat_idx':int(rec.get('repeat_idx',0)),
  'image':str(dst),'image_sha256':h,'model':{'version':'G1-Turbo','face_count':30000},'create_order':i,'estimated_credits':20.0,'exposure_normalized':bool(m<100),'original_mean':round(m,1)})
out=ROOT/'runs/v5/c2'/state/'tasks_exposed.json'; out.write_text(json.dumps({'schema':'v3-generation-tasks/v1','state':state,'n':6,'exposure_rule':'mean<100 -> mean 130','tasks':new},ensure_ascii=False,indent=2)); print(out)
