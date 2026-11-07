"""Finish V7 shadow Lux3D: copy GLBs, write lux_result.json, list retry tasks."""
import argparse,glob,hashlib,json,pathlib,shutil
ROOT=pathlib.Path(__file__).resolve().parent.parent
LEDGER=ROOT/'runs/v3/generation/ledger.jsonl'; TASKS=ROOT/'runs/v7/shadow_exp/tasks_all.json'
def rows(): return [json.loads(l) for l in open(LEDGER) if l.strip()]
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--finish',action='store_true'); ap.add_argument('--retry',action='store_true'); ap.add_argument('--out',default='runs/v7/shadow_exp/retry_tasks.json'); a=ap.parse_args()
 tasks={t['id']:t for t in json.loads(TASKS.read_text())['tasks']}; R=rows()
 state={}; info={}
 for r in R:
  i=str(r.get('id',''))
  if i not in tasks and not i.endswith('_retry'): continue
  e=r.get('event'); state[i]=e
  info.setdefault(i,{}).update({e:r})
 if a.retry:
  retry=[]; order=0
  for i,t in tasks.items():
   if state.get(i) in ('failed','upload_failed','poll_error','uncertain','created'):
    order+=1; nt=dict(t); nt['id']=i+'_retry'; nt['retry_of']=i; nt['create_order']=1000+order; retry.append(nt)
  pathlib.Path(a.out).write_text(json.dumps({'schema':'v3-generation-tasks/v1','n':len(retry),'tasks':retry},indent=2)); print('retry tasks',len(retry)); return
 if not a.finish: return
 done=0; failed=0
 for f in sorted(glob.glob(str(ROOT/'runs/v7/shadow_exp'/'*'/'*'/'lux_request.json'))):
  req=json.loads(pathlib.Path(f).read_text()); res=[]
  for it in req['items']:
   tid=f"v7_shadow_{pathlib.Path(f).parent.parent.name}_{pathlib.Path(f).parent.name}_{it['id']}"
   ev=info.get(tid,{}) or info.get(tid+'_retry',{}); dl=ev.get('downloaded')
   if dl:
    ident=dl.get('identity'); cache=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
    dst=ROOT/'assets/v7/lux'/str(dl['task_id'])/'tex_mesh.glb'; dst.parent.mkdir(parents=True,exist_ok=True)
    if not dst.exists(): shutil.copy2(cache,dst)
    sha=hashlib.sha256(dst.read_bytes()).hexdigest(); done+=1
    res.append({'id':it['id'],'task_id':dl['task_id'],'status':'ok','submitted_at':(ev.get('created') or ev.get('uploaded') or {}).get('at'),'finished_at':dl.get('at'),'fetched_at':dl.get('at'),'glb':str(dst.relative_to(ROOT)),'glb_sha256':sha,'inputs':[it['path']]})
   else:
    failed+=1; res.append({'id':it['id'],'task_id':(ev.get('failed') or {}).get('task_id'),'status':'failed','submitted_at':(ev.get('created') or {}).get('at'),'finished_at':(ev.get('failed') or {}).get('at'),'fetched_at':None,'glb':None,'glb_sha256':None,'inputs':[it['path']]})
  pathlib.Path(req['result_file']).write_text(json.dumps({'tasks':res},indent=2))
 print('ok',done,'failed',failed)
if __name__=='__main__': main()
