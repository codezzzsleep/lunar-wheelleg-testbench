import json,pathlib,sys,hashlib
import numpy as np
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
from v4_wp3_tasks import crop
enc=sys.argv[1]; tag=sys.argv[2] if len(sys.argv)>2 else enc.replace('/','_')
obs=pathlib.Path(sys.argv[3]) if len(sys.argv)>3 else ROOT/'runs/v6/m3'/enc/'observation'; out=ROOT/'runs/v6/m3'/enc
rgb=np.asarray(Image.open(obs/'rgb.png').convert('RGB')); mask=np.asarray(Image.open(obs/'mask.png').convert('L'))>127
base,m=crop(rgb,mask); tasks=[]; order=0
for cname in ('raw','white','masked'):
 for rep in range(2):
  if cname=='raw': img=base.copy()
  elif cname=='white': img=base.copy(); img[~m]=255
  else: img=np.full_like(base,255); img[m]=base[m]
  p=out/'crops'/cname/f'rep{rep}.png'; p.parent.mkdir(parents=True,exist_ok=True); Image.fromarray(img).save(p); order+=1
  tasks.append({'id':f'v6_m3_{tag}_{cname}_r{rep}','state_id':f'm3_{enc}','variant':cname,'repeat_idx':rep,'image':str(p),'image_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'model':{'version':'G1-Turbo','face_count':30000},'create_order':order,'estimated_credits':20.0})
(out/'tasks.json').write_text(json.dumps({'schema':'v3-generation-tasks/v1','n':6,'tasks':tasks},indent=2)); print('tasks',len(tasks))
