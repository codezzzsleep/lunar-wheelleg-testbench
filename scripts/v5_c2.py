"""C2: real candidates -> admission -> FULL -> matrix -> decision -> truth execution."""
import argparse,json,pathlib,sys,hashlib,csv
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_core,v3_register,v3_generate,wheelleg_env,stage8_matrix2 as M,stage6_matrix as S6M
from v4_wp2 import cost_from_record
WHEEL={'R1','R2','D1','D2','L1','L2'}
def plan_for(arm,low):
 p={'raise_z':0.06,'ramp_steps':40,'speed':0.4,'lower_at_x':round(low,3),'end_x':2.6,'stop_tilt_deg':12.0,'far_edge_source':arm}
 p['plan_id']=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:16]; return p
def choose(dec,rows):
 ch=dec['chosen']
 if ch in WHEEL: return ch,'majority_wheel'
 safe=[r for r in rows if r.get('success') and r['action'] in WHEEL and r['action']!='A0']
 costs={r['action']:r.get('cost',60) for r in safe}
 if ch=='BODY_CLEARANCE':
  body=next((r for r in rows if r['action']=='BODY_CLEARANCE' and r.get('success')),None)
  if body and costs:
   best=min(costs,key=costs.get)
   if costs[best] <= 0.95*body.get('cost',60): return best,'wheel_priority_5pct'
 return ch,'majority'
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--states',default='moon_rock_05_h2v1'); ap.add_argument('--out',default='runs/v5/c2'); ap.add_argument('--channel',type=float,default=None); ap.add_argument('--tasks',default=None); a=ap.parse_args()
 out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True); proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text()); actions=[x for x in cfg['actions'] if x!='CLIMB']; adcfg=json.loads((ROOT/'configs/v5_admission.json').read_text())
 table=[]
 for name in a.states.split(','):
  d=ROOT/'runs/v3/states'/name; od=out/name; od.mkdir(parents=True,exist_ok=True)
  V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0); Vsh=V['shell']
  tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
  spec_truth=json.loads((d/'scene_spec.json').read_text())
  if a.channel: spec_truth['channel']={'center_y':0.0,'half_width':float(a.channel)}
  if a.channel:
   e0=wheelleg_env.WheelLegEnv(spec_truth,max_seconds=120); e0.reset(seed=0); snap=e0.save_state(); s0h=snap.get('state_hash'); ref0=(np.asarray(e0.data.qpos,float).copy(),np.asarray(e0.data.qvel,float).copy())
  else:
   snap=json.loads((d/'state_snapshot.json').read_text()); s0h=json.loads((d/'state.json').read_text()).get('state_hash'); ref0=None
  obs=v3_register.load_observation(str(d/'observation'))
  # per-state KA1/KA5/KA6
  ev_t=v3_register.evaluate_matrix(tm,obs,np.eye(4)); m_t=C.admission_metrics(tm,np.eye(4),V,g,ev_t)
  ka1=bool(adcfg['scale_ratio']['min']<=m_t['scale_ratio']<=adcfg['scale_ratio']['max'] and m_t['hidden_frac']>=adcfg['hidden_frac_min'] and m_t['shell_contact']>=adcfg['shell_contact_min'] and m_t['free_intrusion_frac']<=adcfg['free_intrusion_max'] and m_t['contour_iou']>=adcfg['contour_iou_min'])
  rear=float(g['xs'][T.any(axis=(1,2))].max()); cents=tm.vertices[tm.faces].mean(axis=1); keepf=cents[:,0]<=rear-0.10
  cut=trimesh.Trimesh(tm.vertices.copy(),tm.faces[keepf],process=False); Pc=R.column_fill_top(cut,g); hmc=R.hidden_metrics(Pc,T,U,g)
  ka5=bool(hmc['rear_err_m'] is not None and abs(hmc['rear_err_m']+0.10)<=0.003)
  ka6=bool(ev_t.get('mask_iou',0)>=0.95)
  (od/'ka_checks.json').write_text(json.dumps({'KA1':ka1,'KA5':ka5,'KA6':ka6,'KA5_rear':hmc['rear_err_m'],'KA6_iou':ev_t.get('mask_iou')},ensure_ascii=False,indent=2))
  print('KA',name,ka1,ka5,ka6)
  cands=[]; admitted=[]
  items=[]
  for cd in sorted((d/'candidates').glob('*')):
   mp=cd/'parent_world'/'body.stl'
   if mp.exists(): items.append((cd.name,str(mp),None))
  if not items and a.tasks:
   tj=json.loads((ROOT/a.tasks).read_text())['tasks']
   for t in tj:
    ident=v3_generate.identity_of(t); glb=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
    if glb.exists(): items.append((t['id'],str(glb),ident))
  for cid,mp,ident in items:
   if ident:
    rd=od/'reg'/cid; rd.mkdir(parents=True,exist_ok=True); rec=v3_register.register(mp,str(d/'observation'),proto,rd,top_k=6); Mreg=np.asarray(rec['best']['M'],float)
    mesh=trimesh.load(mp,force='mesh',process=False).apply_transform(Mreg); Mworld=np.eye(4)
   else:
    mesh=trimesh.load(mp,force='mesh',process=False); Mworld=np.eye(4)
   ev=v3_register.evaluate_matrix(mesh,obs,Mworld); m=C.admission_metrics(mesh,Mworld,V,g,ev)
   ok=bool(adcfg['scale_ratio']['min']<=m['scale_ratio']<=adcfg['scale_ratio']['max'] and m['hidden_frac']>=adcfg['hidden_frac_min'] and m['shell_contact']>=adcfg['shell_contact_min'] and m['free_intrusion_frac']<=adcfg['free_intrusion_max'] and m['contour_iou']>=adcfg['contour_iou_min'])
   hm=R.hidden_metrics(m['P'],T,U,g)
   cands.append({'id':cid,'admitted':ok,'scale_ratio':m['scale_ratio'],'hidden_frac':m['hidden_frac'],'shell_contact':m['shell_contact'],'free_intrusion_frac':m['free_intrusion_frac'],'contour_iou':m['contour_iou'],'rear_err_m':hm['rear_err_m'],'top_err_m':hm['top_err_m'],'path_p95_mm':hm['path_p95_mm'],'hidden_iou':round(float((m['P']&U&T).sum())/max(1,int(((m['P']&U)|(T&U)).sum())),4),'P':m['P'],'mesh':mesh})
   if ok: admitted.append(cands[-1])
  (od/'candidates.json').write_text(json.dumps([{k:v for k,v in c.items() if k not in ('P','mesh')} for c in cands],ensure_ascii=False,indent=2))
  if a.channel: ref=ref0
  else:
   env0=wheelleg_env.WheelLegEnv(spec_truth,max_seconds=120); env0.reset(seed=0); env0.restore_state(snap,mode='same_scene'); ref=(np.asarray(env0.data.qpos,float).copy(),np.asarray(env0.data.qvel,float).copy())
  # truth arms
  arms={}
  for arm in ('PERFECT','OBS_CONS','OBS_OPT'):
   occ=T if arm=='PERFECT' else Vsh
   ad=od/arm; ad.mkdir(exist_ok=True); spec,env,sha=M.make_scene(M.resample_walls(occ,V['origin'],float(V['pitch'])),ad,'arm')
   if a.channel: spec['channel']={'center_y':0.0,'half_width':float(a.channel)}
   M.restore_common(env,snap,s0h,mode='project',ref=ref)
   low=float(g['xs'][(T&U).any(axis=(1,2))].max())+0.10 if (T&U).any() else 2.45
   low=2.45 if arm=='OBS_CONS' else (0.95 if arm=='OBS_OPT' else low)
   plan=plan_for(arm,low); core={'spec':spec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},'state':{'state_id':name,'state_hash':s0h}}
   rr,_=v3_core.rehearse_on_spec(core,spec,snap,proto,mode='project',options=actions,body_plan=plan,budget=120.0,record_cells=True,record_root=ad/'record')
   for r in rr: r['candidate']=arm
   dec=v3_core.aggregate(rr,[arm],{},'majority',proto,threshold_mode='majority',applic={x:(True,None) for x in actions},options=actions)
   ex=v3_core.truth_execute({'spec':spec_truth,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},'state':{'state_id':name,'state_hash':s0h}},dec['chosen'],proto,ad/'exec','run',mode='same_scene',body_plan=plan,budget=120.0)
   arms[arm]={'chosen':dec['chosen'],'outcome':ex.get('outcome'),'t_end':ex.get('t_end')}
  # FULL candidates
  if not admitted:
   full={'fallback':True,'chosen':arms['OBS_CONS']['chosen'],'outcome':arms['OBS_CONS']['outcome'],'t_end':arms['OBS_CONS']['t_end'],'reason':'zero_admitted'}
  else:
   decs={}; rows_by={}
   for c in admitted:
    occ=Vsh|(c['P']&U); cd=od/'full'/c['id']; cd.mkdir(parents=True,exist_ok=True)
    spec,env,sha=M.make_scene(M.resample_walls(occ,V['origin'],float(V['pitch'])),cd,'full'); M.restore_common(env,snap,s0h,mode='project',ref=ref)
    ax=(c['P']&U).any(axis=(1,2)); low=float(g['xs'][ax].max())+0.10 if ax.any() else 2.45
    plan=plan_for('FULL',low); core={'spec':spec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},'state':{'state_id':name,'state_hash':s0h}}
    rr,_=v3_core.rehearse_on_spec(core,spec,snap,proto,mode='project',options=actions,body_plan=plan,budget=120.0,record_cells=True,record_root=cd/'record')
    for r in rr: r['candidate']=c['id']
    decs[c['id']]=v3_core.aggregate(rr,[c['id']],{},'majority',proto,threshold_mode='majority',applic={x:(True,None) for x in actions},options=actions); rows_by[c['id']]=rr
    with (cd/'matrix_rows.jsonl').open('w') as fh:
     for r in rr: fh.write(json.dumps({k:v for k,v in r.items() if k not in ('trajectory','trajectory_arrays')},ensure_ascii=False)+'\n')
    (cd/'decision.json').write_text(json.dumps(decs[c['id']],ensure_ascii=False,indent=2))
   ids=[c['id'] for c in admitted]; allrows=[r for i in ids for r in rows_by[i]]
   maj=v3_core.aggregate(allrows,ids,{},'majority',proto,threshold_mode='majority',applic={x:(True,None) for x in actions},options=actions)
   worst=v3_core.aggregate(allrows,ids,{},'worst',proto,threshold_mode='worst',applic={x:(True,None) for x in actions},options=actions)
   ch,why=choose(maj,allrows)
   fad=od/'FULL'; fad.mkdir(exist_ok=True)
   (fad/'decision_majority.json').write_text(json.dumps(maj,ensure_ascii=False,indent=2))
   (fad/'decision_worst.json').write_text(json.dumps(worst,ensure_ascii=False,indent=2))
   (fad/'decision_chosen.json').write_text(json.dumps({'majority':maj['chosen'],'worst':worst['chosen'],'chosen':ch,'why':why},ensure_ascii=False,indent=2)); spec,env,sha=M.make_scene(M.resample_walls(Vsh|(admitted[0]['P']&U),V['origin'],float(V['pitch'])),fad,'full')
   # choose plan from majority's selected candidate? use first admitted geometry for execution body plan
   ax=(admitted[0]['P']&U).any(axis=(1,2)); low=float(g['xs'][ax].max())+0.10 if ax.any() else 2.45; plan=plan_for('FULL',low)
   ex=v3_core.truth_execute({'spec':spec_truth,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},'state':{'state_id':name,'state_hash':s0h}},ch,proto,fad/'exec','run',mode='same_scene',body_plan=plan,budget=120.0)
   full={'fallback':False,'n_admitted':len(ids),'majority':maj['chosen'],'worst':worst['chosen'],'chosen':ch,'why':why,'outcome':ex.get('outcome'),'t_end':ex.get('t_end'),'worst_different':maj['chosen']!=worst['chosen']}
   if full['worst_different']:
    ex2=v3_core.truth_execute({'spec':spec_truth,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},'state':{'state_id':name,'state_hash':s0h}},worst['chosen'],proto,fad/'exec','worst',mode='same_scene',body_plan=plan,budget=120.0)
    full['worst_exec']={'outcome':ex2.get('outcome'),'t_end':ex2.get('t_end')}
  (od/'result.json').write_text(json.dumps({'state':name,'arms':arms,'full':full,'candidates':[{k:v for k,v in c.items() if k not in ('P','mesh')} for c in cands]},ensure_ascii=False,indent=2))
  # classify
  if full.get('fallback'):
   typ=''
  else:
   p=arms['PERFECT']; o=arms['OBS_CONS']
   typ='I' if (full['outcome']=='pass' and o['outcome']!='pass') else ('II' if (full['outcome']=='pass' and o['outcome']=='pass' and (o['t_end']-full['t_end'])>=max(3.0,0.3*o['t_end'])) else '')
  table.append({'state':name,'n_candidates':len(cands),'n_admitted':len(admitted),'full_chosen':full.get('chosen'),'full_outcome':full.get('outcome'),'full_t':full.get('t_end'),'obs_chosen':arms['OBS_CONS']['chosen'],'obs_outcome':arms['OBS_CONS']['outcome'],'obs_t':arms['OBS_CONS']['t_end'],'perfect_outcome':arms['PERFECT']['outcome'],'perfect_t':arms['PERFECT']['t_end'],'type':typ,'differs':full.get('chosen')!=arms['OBS_CONS']['chosen']})
  print(json.dumps(table[-1],ensure_ascii=False),flush=True)
 with (out/'core_table.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(table[0].keys())); w.writeheader(); w.writerows(table)
if __name__=='__main__': sys.exit(main())
