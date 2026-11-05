"""C1 (R1 fixes): robust 3-perturbation screening, U_shadow OBS_CONS, per-state visible dims."""
import argparse,csv,json,pathlib,sys,hashlib,math
import numpy as np,trimesh,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_core,wheelleg_env,stage8_matrix2 as M,stage6_matrix as S6M
from v4_wp2 import cost_from_record
def plan_for(arm,low):
 p={'raise_z':0.06,'ramp_steps':40,'speed':0.4,'lower_at_x':round(low,3),'end_x':2.6,'stop_tilt_deg':12.0,'far_edge_source':arm}
 p['plan_id']=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:16]; return p
def contacts(rd):
 p=pathlib.Path(rd)
 if not p.is_absolute(): p=ROOT/p
 try: return int(S6M.chassis_contacts_from_record({'trajectory_path':str(p/'index.json')}))
 except Exception as e: return None
def perturb_snaps(env,snap,ref):
 out=[]
 for dx,dyaw in ((0.02,0.0),(-0.02,0.0),(0.0,2.0)):
  e=env; e.restore_state(snap,mode='project'); e.data.qpos[0]=ref[0][0]+dx; e.data.qvel[:]=ref[1]
  q=e.data.qpos[3:7].copy(); a=math.radians(dyaw)/2; dq=np.array([math.cos(a),0,0,math.sin(a)])
  w1,x1,y1,z1=q; w2,x2,y2,z2=dq
  e.data.qpos[3:7]=[w1*w2-x1*x2-y1*y2-z1*z2, w1*x2+x1*w2+y1*z2-z1*y2, w1*y2-x1*z2+y1*w2+z1*x2, w1*z2+x1*y2-y1*x2+z1*w2]
  mujoco.mj_forward(e.model,e.data); out.append(e.save_state())
 return out
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--states',default=None); ap.add_argument('--limit',type=int,default=0); ap.add_argument('--out',default='runs/v5/c1'); a=ap.parse_args()
 out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True)
 proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text()); actions=[x for x in cfg['actions'] if x!='CLIMB']
 if a.states: names=a.states.split(',')
 else:
  sel=json.loads((ROOT/'runs/v3/selected.json').read_text())['selected']; allst=[d.name for d in sorted((ROOT/'runs/v3/states').iterdir()) if d.is_dir()]
  names=sel+[s for s in allst if s not in sel]
 if a.limit: names=names[:a.limit]
 rows=[]
 for name in names:
  d=ROOT/'runs/v3/states'/name
  V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0); Vsh=V['shell']; obs=v3_register.load_observation(str(d/'observation')) if False else __import__('v3_register').load_observation(str(d/'observation'))
  tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
  sh=C.shadow_mask(V,g,obs); vis=C.visible_dims(d/'observation')
  snap=json.loads((d/'state_snapshot.json').read_text()); spec_truth=json.loads((d/'scene_spec.json').read_text()); s0h=json.loads((d/'state.json').read_text()).get('state_hash')
  env0=wheelleg_env.WheelLegEnv(spec_truth,max_seconds=120); env0.reset(seed=0); env0.restore_state(snap,mode='same_scene'); ref=(np.asarray(env0.data.qpos,float).copy(),np.asarray(env0.data.qvel,float).copy())
  arms={}
  for arm in ('PERFECT','OBS_CONS','OBS_OPT'):
   occ=T if arm=='PERFECT' else ((Vsh|sh) if arm=='OBS_CONS' else Vsh)
   ad=out/name/arm; ad.mkdir(parents=True,exist_ok=True); spec,env,sha=M.make_scene(M.resample_walls(occ,V['origin'],float(V['pitch'])),ad,'arm')
   M.restore_common(env,snap,s0h,mode='project',ref=ref); snaps=perturb_snaps(env,snap,ref)
   low=float(g['xs'][(T&U).any(axis=(1,2))].max())+0.10 if (T&U).any() else 2.45
   low=2.45 if arm=='OBS_CONS' else (0.95 if arm=='OBS_OPT' else low)
   plan=plan_for(arm,low); core={'spec':spec,'snapshot':snap,'visible':vis,'state':{'state_id':name,'state_hash':s0h}}
   runs=[]
   for si,s2 in enumerate(snaps):
    rr,_=v3_core.rehearse_on_spec(core,spec,s2,proto,mode='same_scene',options=actions,body_plan=plan,budget=120.0,record_cells=True,record_root=ad/f'p{si}')
    runs.append(rr)
   combined=[]
   for act in actions:
    ok=True; cost=[]; unassessed=False
    for rr in runs:
     r=next((x for x in rr if x['action']==act),None)
     if r is None or not r.get('success'): ok=False; break
     tref=r.get('trajectory_ref')
     if not tref: ok=False; unassessed=True; break
     tp=tref.get('trajectory_path') if isinstance(tref,dict) else tref
     c=contacts(pathlib.Path(tp).parent if str(tp).endswith('index.json') else tp)
     if c is None: ok=False; unassessed=True; break
     if c>0: ok=False; break
     cost.append(r.get('cost',60))
    ts=[]
    for rr in runs:
     r=next((x for x in rr if x['action']==act),None)
     if r and r.get('t_end') is not None: ts.append(float(r['t_end']))
    combined.append({'action':act,'success':bool(ok),'cost':float(np.mean(cost)) if cost else 60.0,'candidate':arm,'reason':'3of3' if ok else ('unassessed' if unassessed else 'failed'),'t_end':float(np.mean(ts)) if ts else 60.0,'final_x':None})
   dec=v3_core.aggregate(combined,[arm],{},'majority',proto,threshold_mode='majority',applic={x:(True,None) for x in actions},options=actions)
   ch=dec['chosen']
   tcore={'spec':spec_truth,'snapshot':snap,'visible':vis,'state':{'state_id':name,'state_hash':s0h}}
   ex=v3_core.truth_execute(tcore,ch,proto,ad/'exec','run',mode='same_scene',body_plan=plan,budget=120.0)
   rd=ad/'exec'/'record'/'run'; cc=contacts(rd); e=cost_from_record(rd)
   outcom=ex.get('outcome');
   if cc is not None and cc>0: outcom='fail'; ex['reason']='chassis_contact'
   arms[arm]={'chosen':ch,'outcome':outcom,'t_end':ex.get('t_end'),'chassis_contacts':cc,'energy_J':e.get('energy_J'),'distance_m':e.get('distance_m'),'pred_safe':bool(ch in dec.get('safe_set',[]))}
  p,o,opt=arms['PERFECT'],arms['OBS_CONS'],arms['OBS_OPT']
  typ=''
  if p['outcome']=='pass' and o['outcome']!='pass': typ='I'
  elif p['outcome']=='pass' and o['outcome']=='pass' and p['t_end'] is not None and o['t_end'] is not None and (o['t_end']-p['t_end'])>=max(3.0,0.3*o['t_end']): typ='II'
  agree=bool(p['pred_safe']==(p['outcome']=='pass'))
  row={'state':name,'type':typ,'perfect_action':p['chosen'],'perfect_out':p['outcome'],'perfect_t':p['t_end'],'obs_action':o['chosen'],'obs_out':o['outcome'],'obs_t':o['t_end'],'obs_opt_out':opt['outcome'],'perfect_rehearsal_agree':agree,'chassis_contacts':None if o['chassis_contacts'] is None else o['chassis_contacts'],'u_shadow_vox':int(sh.sum()),'x_front':round(vis['x_front'],3),'W_vis':round(vis['W_vis'],3),'H_vis':round(vis['H_vis'],3)}
  rows.append(row); print(json.dumps(row,ensure_ascii=False),flush=True); (out/'value_rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 if rows:
  with (out/'value_table.csv').open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
 print('states',len(rows),'I',sum(r['type']=='I' for r in rows),'II',sum(r['type']=='II' for r in rows))
if __name__=='__main__': sys.exit(main())
