"""WP2: PERFECT / OBS_CONS / OBS_OPT on U-consistent scenes, unified endpoint."""
import argparse, csv, hashlib, json, pathlib, sys, time
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_core, wheelleg_env, stage8_matrix2 as M, stage6_matrix as S6M
import stage10_scenes_v2 as S10

SCENES=['ref','len_short','len_mid','len_long','rear_low','rear_high']
ARMS=['PERFECT','OBS_CONS','OBS_OPT']

def ensure_scenes():
    p=ROOT/'runs/v3/stage010/g1v2'/'occ2_ref.npz'
    if not p.exists():
        import subprocess; subprocess.check_call([sys.executable,str(ROOT/'scripts/stage10_scenes_v2.py')])

def scene_data(name):
    truth=ROOT/'runs/v3/stage008/truth_v2'
    z=np.load(ROOT/'runs/v3/stage010/g1v2'/f'occ2_{name}.npz')
    P=z['P']; o=np.asarray(z['origin'],float); pitch=float(z['pitch'])
    zv=np.load(truth/'fusion/V.npz'); V=zv['shell']; U=(zv['space']==0)
    return P,V,U,o,pitch,truth

def arm_occ(arm,P,V,U):
    if arm=='PERFECT': return V|(P&U)
    return V

def plan_for(arm,P,V,U,o,pitch):
    xs=o[0]+(np.arange(P.shape[0])+0.5)*pitch
    if arm=='PERFECT':
        added=(P&U)&~V; ax=added.any(axis=(1,2)); far=float(xs[ax].max()) if ax.any() else float(xs[P.any(axis=(1,2))].max())
        low=round(far+0.10,3)
    elif arm=='OBS_CONS': low=2.45
    else: low=0.95
    p={'raise_z':0.06,'ramp_steps':100,'speed':0.15,'lower_at_x':low,'end_x':2.6,'stop_tilt_deg':12.0,
       'far_edge_source':arm}
    p['plan_id']=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:16]
    return p

def cost_from_record(rdir):
    import numpy as np
    rdir=pathlib.Path(rdir); chunks=sorted(rdir.glob('chunk_*.npz'))
    if not chunks: return {'distance_m':None,'energy_J':None,'stops':None,'frames':0}
    q=np.concatenate([np.load(c)['qpos'] for c in chunks]); qv=np.concatenate([np.load(c)['qvel'] for c in chunks])
    t=np.concatenate([np.load(c)['t'] for c in chunks])
    dist=float(np.trapezoid(np.abs(qv[:,0]),t)) if len(t)>1 else 0.0
    e=None
    try:
        tau=np.concatenate([np.load(c)['wheel_torque'][:,-4:] for c in chunks]); tj=np.concatenate([np.load(c)['joint_torque'] for c in chunks])
        wq=np.concatenate([np.load(c)['qvel'] for c in chunks])
        pwr=np.abs(np.nansum(tau*wq[:,-4:],axis=1))+np.abs(np.nansum(tj*wq[:,:-4],axis=1))
        val=float(np.trapezoid(pwr,t)) if len(t)>1 else 0.0
        e=round(val,3) if np.isfinite(val) and val>0 else None
    except Exception: e=None
    slow=(np.abs(qv[:,0])<0.02).astype(int); events=0; run=0; dt=0.02
    for s_ in slow:
        if s_: run+=1
        else:
            if run*dt>=0.5: events+=1
            run=0
    if run*dt>=0.5: events+=1
    return {'distance_m':round(dist,4),'energy_J':e,'stops':events,'frames':len(t)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--scenes',default=','.join(SCENES)); ap.add_argument('--arms',default=','.join(ARMS))
    ap.add_argument('--out',default='runs/v4/wp2'); ap.add_argument('--only',default=None)
    a=ap.parse_args(); ensure_scenes()
    out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True)
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text())
    actions=[x for x in cfg['actions'] if x!='CLIMB']; tm=json.loads((ROOT/'runs/v3/stage008/truth_v2/truth_manifest.json').read_text())
    snap=json.loads((ROOT/'runs/v3/stage008/truth_v2/state_snapshot.json').read_text()); s0=tm['s0_state_hash']
    ts=json.loads((ROOT/'runs/v3/stage008/truth_v2/scene_spec.json').read_text())
    ref_env=wheelleg_env.WheelLegEnv(ts,max_seconds=120); ref_env.reset(seed=0); ref_env.restore_state(snap,mode='same_scene')
    s0_ref=(np.asarray(ref_env.data.qpos,float).copy(),np.asarray(ref_env.data.qvel,float).copy())
    rows=[]
    for scen in [s for s in a.scenes.split(',') if s]:
        P,V,U,o,pitch,truth=scene_data(scen)
        truth4=M.resample_walls(P,o,pitch)
        td=out/'truth'/scen; td.mkdir(parents=True,exist_ok=True)
        tspec,_e,tsha=M.make_scene(truth4,td,f'{scen}_truth')
        tcore={'spec':tspec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},
               'state':{'state_id':f'v4_wp2_{scen}_truth','state_hash':s0}}
        for arm in [x for x in a.arms.split(',') if x]:
            if a.only and arm!=a.only: continue
            occ=M.resample_walls(arm_occ(arm,P,V,U),o,pitch)
            d=out/scen/arm; d.mkdir(parents=True,exist_ok=True)
            spec,env,sha=M.make_scene(occ,d,'arm'); M.restore_common(env,snap,s0,mode='project',ref=s0_ref)
            plan=plan_for(arm,P,V,U,o,pitch)
            core={'spec':spec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},
                  'state':{'state_id':f'v4_wp2_{scen}_{arm}','state_hash':s0}}
            rr,_=v3_core.rehearse_on_spec(core,spec,snap,proto,mode='project',options=actions,body_plan=plan,
                                          budget=120.0,record_cells=True,record_root=d/'record')
            for r in rr:
                tref=r.get('trajectory_ref')
                if tref:
                    c=S6M.chassis_contacts_from_record(tref); r['chassis_contacts']=c
                    if c>0 and r.get('success'):
                        r['success']=False; r['outcome']='chassis_contact'; r['reason']='chassis_obstacle_contact'
                else:
                    r['chassis_contacts']=None; r['success']=False; r['reason']='safety_unevaluated'
                r['candidate']=arm
                if arm=='OBS_CONS' and r['action'] in ('D1','D2') and r.get('success'):
                    # conservative rule: detour band crosses U -> treat unsafe
                    if U.any(): r['success']=False; r['outcome']='unknown_detour_unsafe'; r['reason']='U_in_detour_band'
            dec=v3_core.aggregate(rr,[arm],{},'majority',proto,threshold_mode='majority',
                                  applic={x:(x!='CLIMB',None) for x in actions},options=actions)
            ch=dec['chosen']; plan_exec=dict(plan)
            ex=v3_core.truth_execute(tcore,ch,proto,out/'exec',f'{scen}_{arm}',mode='project',body_plan=plan_exec,budget=120.0)
            # costs
            recdir=out/'exec'/'record'/f'{scen}_{arm}'
            cost=cost_from_record(recdir)
            rows.append({'scene':scen,'arm':arm,'chosen':ch,'outcome':ex.get('outcome'),'reason':ex.get('reason'),
                         't_end':ex.get('t_end'),'chassis_contacts':ex.get('chassis_contacts'),
                         'safe_pass':ex.get('safe_pass'),'reached':ex.get('reached'),
                         'distance_m':cost['distance_m'],'energy_J':cost['energy_J'],'stops':cost['stops'],
                         'plan_id':plan_exec.get('plan_id'),'arm_sha':sha,'truth_sha':tsha,
                         'votes':{k:v for k,v in dec['votes'].items() if v}})
            print(json.dumps(rows[-1],ensure_ascii=False)[:400],flush=True)
            with (out/'confirm_table.json').open('w') as f: json.dump(rows,f,ensure_ascii=False,indent=2)
    # csv
    if rows:
        with (out/'confirm_table.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    (out/'run_meta.json').write_text(json.dumps({'schema':'v4-wp2/v1','at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'rows':len(rows)},ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': sys.exit(main())
