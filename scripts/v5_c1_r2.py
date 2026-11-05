"""R2 four-width value screening with the common evaluation module."""
import argparse,csv,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v5_eval as E,v3_core,wheelleg_env,stage8_matrix2 as M,v3_register
from v5_c1 import plan_for
def pick(arm,name,low):
 return plan_for(name,low)
def run_state(name,channel,outroot,actions,repeat=False):
 d=ROOT/'runs/v3/states'/name; V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0); Vsh=V['shell']
 tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
 obs=v3_register.load_observation(str(d/'observation')); sh=C.shadow_mask(V,g,obs); vis=C.visible_dims(d/'observation')
 spec_truth=json.loads((d/'scene_spec.json').read_text()); spec_truth['channel']={'center_y':0.0,'half_width':float(channel)}
 e0=wheelleg_env.WheelLegEnv(spec_truth,max_seconds=120); e0.reset(seed=0); snap=e0.save_state(); ref=(np.asarray(e0.data.qpos,float).copy(),np.asarray(e0.data.qvel,float).copy())
 out=outroot/f'{name}_{channel:g}'; arms={}
 for arm,occ,low in (('PERFECT',T,None),('OBS_CONS',Vsh|sh,2.45),('OBS_OPT',Vsh,0.95)):
  if low is None: low=float(g['xs'][(T&U).any(axis=(1,2))].max())+0.10 if (T&U).any() else 2.45
  arms[arm]=E.robust_arm(occ,V,snap,ref,vis,pick(arm,name,low),actions,out/arm,channel,tag=arm)
 both=arms['OBS_CONS']['safe']&arms['OBS_OPT']['safe']
 def choose(res):
  c=[r for r in res['combined'] if r['action'] in res['safe'] and r['success']]
  return sorted(c,key=lambda r:r['cost'])[0]['action'] if c else 'A0'
 choices={'PERFECT':choose(arms['PERFECT']),'OBS_CONS':choose({'combined':arms['OBS_CONS']['combined'],'safe':both}),'OBS_OPT':choose(arms['OBS_OPT'])}
 res={}
 for arm in ('PERFECT','OBS_CONS','OBS_OPT'):
  ad=out/arm; ex=v3_core.truth_execute({'spec':spec_truth,'snapshot':snap,'visible':vis,'state':{'state_id':name,'state_hash':snap.get('state_hash')}},choices[arm],json.loads((ROOT/'plans/v3_protocol.json').read_text()),ad/'exec','run',mode='same_scene',body_plan=arms[arm]['plan'],budget=120.0)
  cc=E.contact_of(ad/'exec'/'record'/'run'); res[arm]={'action':choices[arm],'outcome':ex.get('outcome'),'t_end':ex.get('t_end'),'contacts':cc}
 typ=''
 p,o=res['PERFECT'],res['OBS_CONS']
 if p['outcome']=='pass' and o['outcome']!='pass': typ='I'
 elif p['outcome']=='pass' and o['outcome']=='pass' and p['t_end'] and o['t_end'] and (o['t_end']-p['t_end'])>=max(3.0,0.3*o['t_end']): typ='II'
 row={'state':name,'channel':channel,'type':typ,'perfect':p['action'],'perfect_out':p['outcome'],'perfect_t':p['t_end'],'obs':o['action'],'obs_out':o['outcome'],'obs_t':o['t_end'],'obs_opt':res['OBS_OPT']['action'],'obs_opt_out':res['OBS_OPT']['outcome'],'safe_solid':','.join(sorted(arms['OBS_CONS']['safe'])),'safe_empty':','.join(sorted(arms['OBS_OPT']['safe'])),'safe_both':','.join(sorted(both)),'contacts':o['contacts']}
 return row,arms
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--states',default='rock_07_h0v0,moon_rock_05_h2v1,moon_rock_06_h1v1,moon_rock_02_h0v1'); ap.add_argument('--channels',default='0.60,0.70,0.80,0.90'); ap.add_argument('--out',default='runs/v5/c1_r2'); a=ap.parse_args()
 out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True); actions=json.loads((ROOT/'configs/stage6_protocol.json').read_text())['actions']; actions=[x for x in actions if x!='CLIMB']
 rows=[]
 for name in a.states.split(','):
  for ch in [float(x) for x in a.channels.split(',')]:
   row,_=run_state(name,ch,out,actions); rows.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
   with (out/'width_table.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
 print('I',sum(r['type']=='I' for r in rows),'II',sum(r['type']=='II' for r in rows))
if __name__=='__main__': sys.exit(main())
