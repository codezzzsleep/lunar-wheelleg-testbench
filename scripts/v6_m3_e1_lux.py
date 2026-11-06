"""M3 E1: build crops from the live observation and submit six Lux3D tasks."""
import json,pathlib,sys,hashlib,subprocess
import numpy as np
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'scripts'))
from v4_wp3_tasks import crop
obs=ROOT/'runs/v6/m3/E1/observation'; out=ROOT/'runs/v6/m3/E1'
rgb=np.asarray(Image.open(obs/'rgb.png').convert('RGB')); mask=np.asarray(Image.open(obs/'mask.png').convert('L'))>127
base,m=crop(rgb,mask); tasks=[]; order=0
for cname in ('raw','white','masked'):
 for rep in range(2):
  if cname=='raw': img=base.copy()
  elif cname=='white':
   img=base.copy(); img[~m]=255
  else:
   img=np.full_like(base,255); img[m]=base[m]
  p=out/'crops'/cname/f'rep{rep}.png'; p.parent.mkdir(parents=True,exist_ok=True); Image.fromarray(img).save(p)
  order+=1; tasks.append({'id':f'v6_m3_E1_{cname}_r{rep}','state_id':'m3_E1','variant':cname,'repeat_idx':rep,'image':str(p),'image_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'model':{'version':'G1-Turbo','face_count':30000},'create_order':order,'estimated_credits':20.0})
tj=out/'tasks.json'; tj.write_text(json.dumps({'schema':'v3-generation-tasks/v1','n':6,'tasks':tasks},indent=2)); print('tasks',len(tasks))
