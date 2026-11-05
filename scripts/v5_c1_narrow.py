"""C1 narrow-corridor variant: fresh reset S0, channel half width configurable."""
import argparse,json,pathlib,sys,hashlib
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_core,wheelleg_env,stage8_matrix2 as M,stage6_matrix as S6M
from v5_c1 import contacts,plan_for,perturb_snaps
from v4_wp2 import cost_from_record
ap=argparse.ArgumentParser(); ap.add_argument('--states',required=True); ap.add_argument('--channel',type=float,default=0.35); ap.add_argument('--out',default='runs/v5/c1_narrow'); a=ap.parse_args()
out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True); proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text()); actions=[x for x in cfg['actions'] if x!='CLIMB']; rows=[]
for name in a.states.split(','):
 d=ROOT/'runs/v3/states'/name; V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0); Vsh=V['shell']; obs=__import__('v3_register').load_observation(str(d/'observation'))
 tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g); sh=C.shadow_mask(V,g,obs); vis=C.visible_dims(d/'observation')
 spec_truth=json.loads((d/'scene_spec.json').read_text()); spec_truth['channel']={'center_y':0.0,'half_width':float(a.channel)}
 env0=wheelleg_env.WheelLegEnv(spec_truth,max_seconds=120); env0.reset(seed=0); snap=env0.save_state(); ref=(np.asarray(env0.data.qpos,float).copy(),np.asarray(env0.data.qvel,float).copy()); s0h=snap.get('state_hash')
 arms={}; details={}
 for arm in ('PERFECT','OBS_CONS','OBS_OPT'):
  occ=T if arm=='PERFECT' else ((Vsh|sh) if arm=='OBS_CONS' else Vsh)
  ad=out/name/arm; ad.mkdir(parents=True,exist_ok=True); spec,env,sha=M.make_scene(M.resample_walls(occ,V['origin'],float(V['pitch'])),ad,'arm'); spec['channel']={'center_y':0.0,'half_width':float(a.channel)}
  M.restore_common(env,snap,s0h,mode='project',ref=ref); snaps=perturb_snaps(env,snap,ref)
  low=float(g['xs'][(T&U).any(axis=(1,2))].max())+0.10 if (T&U).any() else 2.45; low=2.45 if arm=='OBS_CONS' else (0.95 if arm=='OBS_OPT' else low)
  plan=plan_for(arm,low); core={'spec':spec,'snapshot':snap,'visible':vis,'state':{'state_id':name,'state_hash':s0h}}
  runs=[]
  for si,s2 in enumerate(snaps):
   rr,_=v3_core.rehearse_on_spec(core,spec,s2,proto,mode='same_scene',options=actions,body_plan=plan,budget=120.0,record_cells=True,record_root=ad/f'p{si}'); runs.append(rr)
  combined=[]; detail=[]
  for act in actions:
   perms=[]; ok=True; cost=[]; ts=[]
   for si,rr in enumerate(runs):
    r=next((x for x in rr if x['action']==act),None); ent={'action':act,'perturb':si,'success':bool(r and r.get('success')),'reason':None if not r else r.get('reason'),'contacts':None,'cost':None if not r else r.get('cost'),'t_end':None if not r else r.get('t_end')}
    if r and r.get('trajectory_ref'):
     tp=r['trajectory_ref'].get('trajectory_path'); ent['contacts']=contacts(pathlib.Path(tp).parent if str(tp).endswith('index.json') else tp)
    if not ent['success'] or ent['contacts'] is None or (ent['contacts'] or 0)>0: ok=False
    if ent['cost'] is not None and ent['success'] and (ent['contacts'] or 0)==0: cost.append(ent['cost'])
    if ent['t_end'] is not None: ts.append(float(ent['t_end']))
    perms.append(ent)
   detail+=perms; combined.append({'action':act,'success':bool(ok),'cost':float(np.mean(cost)) if cost else 60.0,'candidate':arm,'reason':'3of3' if ok else 'failed','t_end':float(np.mean(ts)) if ts else 60.0,'final_x':None})
  safe={c['action'] for c in combined if c['success']}; dec=v3_core.aggregate(combined,[arm],{},'majority',proto,threshold_mode='majority',applic={x:(True,None) for x in actions},options=actions)
  arms[arm]={'chosen':dec['chosen'],'safe':safe,'combined':combined,'plan':plan}; details[arm]=detail
  (ad/'rehearsal_3of3.json').write_text(json.dumps({'state':name,'arm':arm,'entries':detail,'safe_actions':sorted(safe)},ensure_ascii=False,indent=2))
 p,o,opt=arms['PERFECT'],arms['OBS_CONS'],arms['OBS_OPT']
 both=o['safe']&opt['safe']
 if both:
  cands=sorted([r for r in o['combined'] if r['action'] in both and r['success']],key=lambda r:r['cost']); pick=cands[0]['action']
 else: pick='A0'
 for arm,ch in (('PERFECT',p['chosen']),('OBS_CONS',pick),('OBS_OPT',opt['chosen'])):
  ad=out/name/arm; ex=v3_core.truth_execute({'spec':spec_truth,'snapshot':snap,'visible':vis,'state':{'state_id':name,'state_hash':s0h}},ch,proto,ad/'exec','run',mode='same_scene',body_plan=arms[arm]['plan'],budget=120.0)
  rd=ad/'exec'/'record'/'run'; cc=contacts(rd); e=cost_from_record(rd); arms[arm].update({'outcome':ex.get('outcome'),'t_end':ex.get('t_end'),'chassis_contacts':cc,'energy_J':e.get('energy_J')})
  if cc is not None and cc>0: arms[arm]['outcome']='fail'
 typ=''
 if p['outcome']=='pass' and o['outcome']!='pass': typ='I'
 elif p['outcome']=='pass' and o['outcome']=='pass' and p['t_end'] is not None and o['t_end'] is not None and (o['t_end']-p['t_end'])>=max(3.0,0.3*o['t_end']): typ='II'
 row={'state':name,'channel':a.channel,'type':typ,'perfect':p['chosen'],'perfect_out':p['outcome'],'perfect_t':p['t_end'],'obs':pick,'obs_out':o['outcome'],'obs_t':o['t_end'],'obs_opt_out':opt['outcome'],'safe_solid':','.join(sorted(o['safe'])),'safe_both':','.join(sorted(both))}
 rows.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
with (out/'narrow_table.csv').open('w',newline='') as f:
 import csv; w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('I',sum(r['type']=='I' for r in rows),'II',sum(r['type']=='II' for r in rows))
