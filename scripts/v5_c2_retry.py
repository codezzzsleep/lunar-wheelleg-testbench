"""Retry the six rock_07_h1v1 tasks once with new identities and retry_of."""
import json,pathlib,shutil,hashlib
ROOT=pathlib.Path(__file__).resolve().parent.parent; state='rock_07_h1v1'
d=ROOT/'runs/v3/states'/state/'observation'/'gen'/'variants'
old=json.loads((ROOT/'runs/v5/c2'/state/'tasks.json').read_text())['tasks']
new=[]
for i,t in enumerate(old,1):
 src=pathlib.Path(t['image']); dst=ROOT/'runs/v5/c2'/state/'retry1'/f'{src.stem}.png'; dst.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(src,dst)
 h=hashlib.sha256(dst.read_bytes()).hexdigest()
 new.append({'id':t['id']+'_retry1','state_id':state,'variant':t['variant']+'_retry1','repeat_idx':t['repeat_idx'],
  'image':str(dst),'image_sha256':h,'model':t['model'],'create_order':i,'estimated_credits':20.0,'retry_of':t['id']})
out=ROOT/'runs/v5/c2'/state/'tasks_retry1.json'; out.write_text(json.dumps({'schema':'v3-generation-tasks/v1','state':state,'n':6,'retry_of_batch':'tasks.json','tasks':new},ensure_ascii=False,indent=2)); print(out)
