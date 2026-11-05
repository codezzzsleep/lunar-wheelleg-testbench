"""C2 R2: FULL with the shared channel-aware robust evaluation."""
import argparse,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v5_eval as E,v3_core,v3_register,v3_generate,wheelleg_env
from v5_c1 import plan_for
WHEEL={'R1','R2','D1','D2','L1','L2'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--state',required=True); ap.add_argument('--channel',type=float,required=True); ap.add_argument('--tasks',required=True); ap.add_argument('--out',required=True); a=ap.parse_args()
 d=ROOT/'runs/v3/states'/a.state; out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True)
 V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0); Vsh=V['shell']
 tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
 obs=v3_register.load_observation(str(d/'observation')); sh=C.shadow_mask(V,g,obs); vis=C.visible_dims(d/'observation')
 spec_truth=json.loads((d/'scene_spec.json').read_text()); spec_truth['channel']={'center_y':0.0,'half_width':a.channel}
 e0=wheelleg_env.WheelLegEnv(spec_truth,max_seconds=120); e0.reset(seed=0); snap=e0.save_state(); ref=(np.asarray(e0.data.qpos,float).copy(),np.asarray(e0.data.qvel,float).copy())
 proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); actions=[x for x in json.loads((ROOT/'configs/stage6_protocol.json').read_text())['actions'] if x!='CLIMB']; adcfg=json.loads((ROOT/'configs/v5_admission.json').read_text())
 cands=[]
 items=[]
 if a.tasks and a.tasks!='none':
  for t in json.loads((ROOT/a.tasks).read_text())['tasks']:
   ident=v3_generate.identity_of(t); glb=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
   if glb.exists(): items.append((t['id'],str(glb),True))
 else:
  for cd in sorted((d/'candidates').glob('*')):
   mp=cd/'parent_world'/'body.stl'
   if mp.exists(): items.append((cd.name,str(mp),False))
 for cid,glb,need_reg in items:
  if need_reg:
   rd=out/'reg'/cid; rd.mkdir(parents=True,exist_ok=True); rec=v3_register.register(glb,str(d/'observation'),proto,rd,top_k=6); Mreg=np.asarray(rec['best']['M'],float)
   mesh=trimesh.load(glb,force='mesh',process=False).apply_transform(Mreg)
  else:
   mesh=trimesh.load(glb,force='mesh',process=False)
  ev=v3_register.evaluate_matrix(mesh,obs,np.eye(4)); m=C.admission_metrics(mesh,np.eye(4),V,g,ev); hm=R.hidden_metrics(m['P'],T,U,g)
  ok=bool(adcfg['scale_ratio']['min']<=m['scale_ratio']<=adcfg['scale_ratio']['max'] and m['hidden_frac']>=adcfg['hidden_frac_min'] and m['shell_contact']>=adcfg['shell_contact_min'] and m['free_intrusion_frac']<=adcfg['free_intrusion_max'] and m['contour_iou']>=adcfg['contour_iou_min'])
  cands.append({'id':cid,'admitted':ok,'P':m['P'],'rear_err_m':hm['rear_err_m'],'top_err_m':hm['top_err_m'],'path_p95_mm':hm['path_p95_mm'],'hidden_iou':round(float((m['P']&U&T).sum())/max(1,int(((m['P']&U)|(T&U)).sum())),4),'scale_ratio':m['scale_ratio'],'contour_iou':m['contour_iou']})
 (out/'candidates.json').write_text(json.dumps([{k:v for k,v in c.items() if k!='P'} for c in cands],ensure_ascii=False,indent=2))
 admitted=[c for c in cands if c['admitted']]
 arms={}
 for arm,occ,low in (('PERFECT',T,None),('OBS_CONS',Vsh|sh,2.45),('OBS_OPT',Vsh,0.95)):
  if low is None: low=float(g['xs'][(T&U).any(axis=(1,2))].max())+0.10 if (T&U).any() else 2.45
  arms[arm]=E.robust_arm(occ,V,snap,ref,vis,plan_for(arm,low),actions,out/arm,a.channel,tag=arm)
 both=arms['OBS_CONS']['safe']&arms['OBS_OPT']['safe']
 def choose(res,safe):
  c=[r for r in res['combined'] if r['action'] in safe and r['success']]
  return sorted(c,key=lambda r:r['cost'])[0]['action'] if c else 'A0'
 fullrows={}; fullplans={}
 for c in admitted:
  low=float(g['xs'][(c['P']&U).any(axis=(1,2))].max())+0.10 if (c['P']&U).any() else 2.45
  plan=plan_for('FULL',low); fullplans[c['id']]=plan
  fullrows[c['id']]=E.robust_arm(Vsh|(c['P']&U),V,snap,ref,vis,plan,actions,out/'full'/c['id'],a.channel,tag=c['id'])
 if fullrows:
  def agg(mode):
   need=len(fullrows)//2+1 if mode=='majority' else len(fullrows)
   votes={}; costs={}
   for act in actions:
    votes[act]=sum(1 for cid in fullrows if any(r['action']==act and r['success'] for r in fullrows[cid]['combined']))
    costs[act]=[next((r['cost'] for r in fullrows[cid]['combined'] if r['action']==act),60.0) for cid in fullrows]
   passing=[act for act in actions if act!='A0' and votes[act]>=need]
   return (sorted(passing,key=lambda act:sum(costs[act])/len(costs[act]))[0] if passing else 'A0'),votes,costs,need
  maj,mv,mc,need=agg('majority'); worst,wv,wc,_=agg('worst')
  ch=maj
  if ch!='A0':
   ch_cost=sum(mc[ch])/len(mc[ch])
   wheels={act:sum(mc[act])/len(mc[act]) for act in WHEEL if mv[act]>=need}
   if wheels:
    best=min(wheels,key=wheels.get)
    if wheels[best]<=0.95*ch_cost: ch=best
 else:
  maj=worst=ch='A0'
 (out/'FULL').mkdir(exist_ok=True)
 (out/'FULL'/'decision_majority.json').write_text(json.dumps({'chosen':maj,'votes':{k:v for k,v in (mv.items() if fullrows else [])}},ensure_ascii=False,indent=2))
 (out/'FULL'/'decision_worst.json').write_text(json.dumps({'chosen':worst},ensure_ascii=False,indent=2))
 (out/'FULL'/'decision_chosen.json').write_text(json.dumps({'majority':maj,'worst':worst,'chosen':ch},ensure_ascii=False,indent=2))
 res={}
 for arm,choice in (('PERFECT',choose(arms['PERFECT'],arms['PERFECT']['safe'])),('OBS_CONS',choose(arms['OBS_CONS'],both)),('OBS_OPT',choose(arms['OBS_OPT'],arms['OBS_OPT']['safe'])),('FULL',ch)):
  ad=out/arm
  plan=arms.get(arm,{}).get('plan') or (fullplans[admitted[0]['id']] if admitted else plan_for('FULL',2.45))
  ex=v3_core.truth_execute({'spec':spec_truth,'snapshot':snap,'visible':vis,'state':{'state_id':a.state,'state_hash':snap.get('state_hash')}},choice,proto,ad/'exec','run',mode='same_scene',body_plan=plan,budget=120.0)
  cc=E.contact_of(ad/'exec'/'record'/'run'); res[arm]={'action':choice,'outcome':ex.get('outcome'),'reason':ex.get('reason'),'t_end':ex.get('t_end'),'contacts':cc}
 p,o,f=res['PERFECT'],res['OBS_CONS'],res['FULL']; typ=''
 if f['outcome']=='pass' and o['outcome']!='pass': typ='I'
 elif f['outcome']=='pass' and o['outcome']=='pass' and f['t_end'] and o['t_end'] and (o['t_end']-f['t_end'])>=max(3.0,0.3*o['t_end']): typ='II'
 row={'state':a.state,'channel':a.channel,'n_cand':len(cands),'n_adm':len(admitted),'type':typ,'perfect':p['action'],'perfect_out':p['outcome'],'obs':o['action'],'obs_out':o['outcome'],'full':f['action'],'full_out':f['outcome'],'full_t':f['t_end'],'obs_t':o['t_end'],'differs':f['action']!=o['action'],'contacts':f['contacts']}
 (out/'result.json').write_text(json.dumps({'row':row,'arms':res,'full':{'majority':maj,'worst':worst,'chosen':ch},'candidates':[{k:v for k,v in c.items() if k!='P'} for c in cands]},ensure_ascii=False,indent=2)); print(json.dumps(row,ensure_ascii=False))
if __name__=='__main__': sys.exit(main())
