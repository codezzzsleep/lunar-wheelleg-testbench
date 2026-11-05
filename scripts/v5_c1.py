"""C1: value screening on real-rock states (PERFECT/OBS_CONS/OBS_OPT)."""
import argparse,csv,json,pathlib,sys,hashlib,time
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_core,wheelleg_env,stage8_matrix2 as M,stage6_matrix as S6M
from v4_wp2 import cost_from_record
def plan_for(arm,low):
 p={'raise_z':0.06,'ramp_steps':40,'speed':0.4,'lower_at_x':round(low,3),'end_x':2.6,'stop_tilt_deg':12.0,'far_edge_source':arm}
 p['plan_id']=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:16]; return p
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--states',default=None); ap.add_argument('--limit',type=int,default=0); ap.add_argument('--out',default='runs/v5/c1')
 a=ap.parse_args(); out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True)
 proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text()); actions=[x for x in cfg['actions'] if x!='CLIMB']
 if a.states: names=a.states.split(',')
 else:
  sel=json.loads((ROOT/'runs/v3/selected.json').read_text())['selected']; allst=[d.name for d in sorted((ROOT/'runs/v3/states').iterdir()) if d.is_dir()]
  names=sel+[s for s in allst if s not in sel]
 if a.limit: names=names[:a.limit]
 rows=[]
 for name in names:
  d=ROOT/'runs/v3/states'/name
  if not d.exists(): print('missing',name); continue
  V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0); Vsh=V['shell']
  tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
  snap=json.loads((d/'state_snapshot.json').read_text())
  spec_truth=json.loads((d/'scene_spec.json').read_text())
  env0=wheelleg_env.WheelLegEnv(spec_truth,max_seconds=120); env0.reset(seed=0); env0.restore_state(snap,mode='same_scene')
  ref=(np.asarray(env0.data.qpos,float).copy(),np.asarray(env0.data.qvel,float).copy())
  s0h=json.loads((d/'state.json').read_text()).get('state_hash')
  occs={'PERFECT':T,'OBS_CONS':Vsh|False,'OBS_OPT':Vsh|False}
  for arm in ('PERFECT','OBS_CONS','OBS_OPT'):
   od=out/name/arm; od.mkdir(parents=True,exist_ok=True)
   spec,env,sha=M.make_scene(M.resample_walls(occs[arm],V['origin'],float(V['pitch'])),od,'arm')
   M.restore_common(env,snap,s0h,mode='project',ref=ref)
   if arm=='PERFECT':
    ax=(T&U).any(axis=(1,2)); low=float(g['xs'][ax].max())+0.10 if ax.any() else 2.45
   elif arm=='OBS_CONS': low=2.45
   else: low=0.95
   plan=plan_for(arm,low)
   core={'spec':spec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},'state':{'state_id':name,'state_hash':s0h}}
   rr,_=v3_core.rehearse_on_spec(core,spec,snap,proto,mode='project',options=actions,body_plan=plan,budget=120.0,record_cells=True,record_root=od/'record')
   for r in rr:
    r['candidate']=arm
    tref=r.get('trajectory_ref')
    if tref:
     c=S6M.chassis_contacts_from_record(tref); r['chassis_contacts']=c
     if c>0 and r.get('success'): r['success']=False; r['reason']='chassis_obstacle_contact'
    else: r['chassis_contacts']=None; r['success']=False; r['reason']='safety_unevaluated'
    if arm=='OBS_CONS' and r['action'] in ('D1','D2') and r.get('success'):
     r['success']=False; r['reason']='U_in_detour_band'
   dec=v3_core.aggregate(rr,[arm],{},'majority',proto,threshold_mode='majority',applic={x:(x!='CLIMB',None) for x in actions},options=actions)
   ch=dec['chosen']
   tcore={'spec':spec_truth,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},'state':{'state_id':name,'state_hash':s0h}}
   ex=v3_core.truth_execute(tcore,ch,proto,od/'exec','run',mode='same_scene',body_plan=plan,budget=120.0)
   c=cost_from_record(od/'exec'/'record'/'run')
   row={'state':name,'arm':arm,'chosen':ch,'outcome':ex.get('outcome'),'reason':ex.get('reason'),'t_end':ex.get('t_end'),'chassis_contacts':ex.get('chassis_contacts'),'distance_m':c.get('distance_m'),'energy_J':c.get('energy_J'),'stops':c.get('stops'),'plan_id':plan['plan_id']}
   rows.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
   (out/'value_rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 # classify
 by={}
 for r in rows: by.setdefault(r['state'],{})[r['arm']]=r
 vals=[]
 for st,arms in by.items():
  p,o=arms.get('PERFECT'),arms.get('OBS_CONS')
  if not p or not o: continue
  if p['outcome']=='pass' and o['outcome']!='pass': typ='I'
  elif p['outcome']=='pass' and o['outcome']=='pass' and p['t_end'] is not None and o['t_end'] is not None and (o['t_end']-p['t_end'])>=max(3.0,0.30*o['t_end']): typ='II'
  else: typ=''
  vals.append({'state':st,'type':typ,'perfect_t':p['t_end'],'obs_t':o['t_end'],'perfect_out':p['outcome'],'obs_out':o['outcome'],'perfect_action':p['chosen'],'obs_action':o['chosen']})
 if vals:
  fields=list(vals[0].keys())
  with (out/'value_table.csv').open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(vals)
 print('states',len(by),'value I',sum(v['type']=='I' for v in vals),'II',sum(v['type']=='II' for v in vals))
if __name__=='__main__': sys.exit(main())
