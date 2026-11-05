"""A-line R3: geometry-planned detour, 16 tall states x 4 channels."""
import argparse,csv,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v5_eval as E,v3_core,wheelleg_env,v3_register
from v5_c1 import plan_for
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--states',default=None); ap.add_argument('--channels',default='0.60,0.70,0.80,0.90'); ap.add_argument('--out',default='runs/v5/a_r3'); a=ap.parse_args()
 names=a.states.split(',') if a.states else [r['state'] for r in csv.DictReader(open(ROOT/'runs/v5/c1/value_table.csv')) if float(r['H_vis'])>=0.17]
 out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True); rows=[]; prot=json.loads((ROOT/'plans/v3_protocol.json').read_text()); acts0=[x for x in json.loads((ROOT/'configs/stage6_protocol.json').read_text())['actions'] if x!='CLIMB']
 for name in names:
  d=ROOT/'runs/v3/states'/name; V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0); Vsh=V['shell']
  tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
  obs=v3_register.load_observation(str(d/'observation')); sh=C.shadow_mask(V,g,obs); vis=C.visible_dims(d/'observation')
  truth_rear=float(g['xs'][T.any(axis=(1,2))].max()); shadow_rear=float(g['xs'][sh.any(axis=(1,2))].max()) if sh.any() else None
  for ch in [float(x) for x in a.channels.split(',')]:
   spec=json.loads((d/'scene_spec.json').read_text()); spec['channel']={'center_y':0.0,'half_width':ch}
   e0=wheelleg_env.WheelLegEnv(spec,max_seconds=120); e0.reset(seed=0); snap=e0.save_state(); ref=(np.asarray(e0.data.qpos,float).copy(),np.asarray(e0.data.qvel,float).copy())
   geoms={'PERFECT':T,'OBS_CONS':Vsh|sh,'OBS_OPT':Vsh}
   arms={}; plans={}
   for arm,occ in geoms.items():
    pd=E.plan_detour(occ,V,vis,ch); plans[arm]=pd
    acts=[x for x in acts0 if pd['applicable'] or x not in ('D1','D2')]
    low=2.45 if arm=='OBS_CONS' else (0.95 if arm=='OBS_OPT' else float(g['xs'][(T&U).any(axis=(1,2))].max())+0.10)
    plan=plan_for(arm,low); plan.update({'offset_m':pd['offset_m'],'leave_x':pd['leave_x']})
    arms[arm]=E.robust_arm(occ,V,snap,ref,vis,plan,acts,out/f'{name}_{ch:g}'/arm,ch,tag=arm)
   both=arms['OBS_CONS']['safe']&arms['OBS_OPT']['safe']
   def choose(res,safe):
    c=[r for r in res['combined'] if r['action'] in safe and r['success']]
    return sorted(c,key=lambda r:r['cost'])[0]['action'] if c else 'A0'
   res={}
   for arm,chc in (('PERFECT',choose(arms['PERFECT'],arms['PERFECT']['safe'])),('OBS_CONS',choose(arms['OBS_CONS'],both)),('OBS_OPT',choose(arms['OBS_OPT'],arms['OBS_OPT']['safe']))):
    ad=out/f'{name}_{ch:g}'/arm; ex=v3_core.truth_execute({'spec':spec,'snapshot':snap,'visible':vis,'state':{'state_id':name,'state_hash':snap.get('state_hash')}},chc,prot,ad/'exec','run',mode='same_scene',body_plan=arms[arm]['plan'],budget=120.0)
    cc=E.contact_of(ad/'exec'/'record'/'run'); res[arm]={'action':chc,'outcome':ex.get('outcome'),'reason':ex.get('reason'),'t_end':ex.get('t_end'),'contacts':cc}
   p,o=res['PERFECT'],res['OBS_CONS']; typ=''
   if p['outcome']=='pass' and o['outcome']!='pass': typ='I'
   elif p['outcome']=='pass' and o['outcome']=='pass' and p['t_end'] and o['t_end'] and (o['t_end']-p['t_end'])>=max(3.0,0.3*o['t_end']): typ='II'
   row={'state':name,'channel':ch,'type':typ,'perfect':p['action'],'perfect_out':p['outcome'],'perfect_t':p['t_end'],'obs':o['action'],'obs_out':o['outcome'],'obs_t':o['t_end'],'obs_opt':res['OBS_OPT']['action'],'obs_opt_out':res['OBS_OPT']['outcome'],
        'off_perfect':plans['PERFECT']['offset_m'],'leave_perfect':plans['PERFECT']['leave_x'],'off_obs':plans['OBS_CONS']['offset_m'],'leave_obs':plans['OBS_CONS']['leave_x'],'off_opt':plans['OBS_OPT']['offset_m'],
        'off_gap':round(plans['OBS_CONS']['offset_m']-plans['PERFECT']['offset_m'],4),'rear_gap':None if shadow_rear is None else round(shadow_rear-truth_rear,4),'safe_both':','.join(sorted(both))}
   rows.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
   with (out/'a_table.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
 print('done',len(rows),'I',sum(r['type']=='I' for r in rows),'II',sum(r['type']=='II' for r in rows))
if __name__=='__main__': sys.exit(main())
