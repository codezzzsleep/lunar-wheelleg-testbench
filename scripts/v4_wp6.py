"""WP6: BODY speed-up test (same plan for all arms)."""
import argparse,json,pathlib,sys,time
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_core,wheelleg_env,stage8_matrix2 as M
import numpy as np
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--scene',default='ref'); ap.add_argument('--speed',type=float,default=0.40)
    ap.add_argument('--ramp',type=int,default=40); ap.add_argument('--lower',type=float,default=1.165); ap.add_argument('--out',default='runs/v4/wp6')
    a=ap.parse_args(); T=ROOT/'runs/v3/stage008/truth_v2'; out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True)
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); snap=json.loads((T/'state_snapshot.json').read_text())
    spec=json.loads((T/'scene_spec.json').read_text()); env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0); env.restore_state(snap,mode='same_scene')
    core={'spec':spec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},
          'state':{'state_id':f'wp6_{a.scene}','state_hash':json.loads((T/'truth_manifest.json').read_text())['s0_state_hash']}}
    plan={'raise_z':0.06,'ramp_steps':a.ramp,'speed':a.speed,'lower_at_x':a.lower,'end_x':2.6,'stop_tilt_deg':12.0,'far_edge_source':'wp6'}
    plan['plan_id']=__import__('hashlib').sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()[:16]
    res=v3_core.truth_execute(core,'BODY_CLEARANCE',proto,out/'exec',f'{a.scene}_s{a.speed}',mode='same_scene',body_plan=plan,budget=120.0)
    print(json.dumps({'scene':a.scene,'speed':a.speed,'ramp':a.ramp,'lower':a.lower,'result':{k:res.get(k) for k in ('outcome','reason','t_end','chassis_contacts','safe_pass','reached')}},ensure_ascii=False))
    (out/f'{a.scene}_s{a.speed}.json').write_text(json.dumps(res,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
