"""Auto-expose low-brightness Lux3D inputs (review R1) and build new tasks."""
import json,pathlib,hashlib
import numpy as np
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent; state='rock_07_h1v1'
old=json.loads((ROOT/'runs/v5/c2'/state/'tasks.json').read_text())['tasks']; new=[]
for i,t in enumerate(old,1):
 src=pathlib.Path(t['image']); im=np.asarray(Image.open(src).convert('RGB')).astype(np.float32); m=float(im.mean())
 dst=ROOT/'runs/v5/c2'/state/'exposed'/f'{src.stem}.png'; dst.parent.mkdir(parents=True,exist_ok=True)
 if m<100:
  target=130.0; out=np.clip(im*(target/max(m,1e-6)),0,255).astype(np.uint8)
 else: out=im.astype(np.uint8)
 Image.fromarray(out).save(dst); h=hashlib.sha256(dst.read_bytes()).hexdigest()
 new.append({'id':t['id']+'_exposed','state_id':state,'variant':t['variant']+'_exposed','repeat_idx':t['repeat_idx'],
  'image':str(dst),'image_sha256':h,'model':t['model'],'create_order':i,'estimated_credits':20.0,'exposure_normalized':True,'original_mean':round(m,1)})
out=ROOT/'runs/v5/c2'/state/'tasks_exposed.json'; out.write_text(json.dumps({'schema':'v3-generation-tasks/v1','state':state,'n':6,'exposure_rule':'mean<100 -> scale to mean 130','tasks':new},ensure_ascii=False,indent=2)); print(out)
