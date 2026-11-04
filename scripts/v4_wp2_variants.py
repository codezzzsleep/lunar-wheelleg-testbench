"""WP2 extension: 3 rocks x 3 unknown types; screen PERFECT vs OBS_CONS."""
import argparse, csv, json, pathlib, sys
import numpy as np, trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_core, v3_fuse, wheelleg_env, stage8_matrix2 as M, stage6_matrix as S6M
from v4_wp2 import cost_from_record, plan_for
STATES={'moon_rock_01':'moon_rock_01_h1v0','moon_rock_03':'moon_rock_03_h1v0','moon_rock_07':'rock_07_h2v1'}
TYPES=['low_rock','high_rock','half_occluded']

def load_state(sdir):
    z=np.load(sdir/'fusion/V.npz'); V=z['shell']; U=(z['space']==0); o=np.asarray(z['origin'],float); pitch=float(z['pitch'])
    dims=tuple(int(x) for x in z['dims'])
    grid={'origin':o,'pitch':pitch,'dims':np.array(dims)}
    grid['xs']=o[0]+(np.arange(dims[0])+0.5)*pitch; grid['ys']=o[1]+(np.arange(dims[1])+0.5)*pitch; grid['zs']=o[2]+(np.arange(dims[2])+0.5)*pitch
    mesh=trimesh.load(str(sdir/'truth/body_world.stl'),force='mesh',process=False)
    P,_=v3_fuse.voxelize_columns(mesh,grid)
    return P,V,U,o,pitch,mesh,grid

def carve(P,U,grid,typ):
    zs=grid['zs'][None,None,:]; ys=grid['ys'][None,:,None]; xs=grid['xs'][:,None,None]
    rear=(xs>1.0)&(xs<1.6)
    if typ=='low_rock': mask=rear&(zs<0.15)
    elif typ=='high_rock': mask=rear&(zs>=0.15)&(zs<=0.32)
    else: mask=rear&(ys>0.10)
    return P & ~(U & mask)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='runs/v4/wp2/ext'); ap.add_argument('--rocks',default=','.join(STATES))
    ap.add_argument('--arms',default='PERFECT,OBS_CONS'); ap.add_argument('--types',default=','.join(TYPES))
    a=ap.parse_args(); out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True)
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text())
    actions=[x for x in cfg['actions'] if x!='CLIMB']
    rows=[]
    for rock,state in STATES.items():
        if rock not in a.rocks.split(','): continue
        sdir=ROOT/'runs/v3/states'/state
        P0,V,U,o,pitch,mesh,grid=load_state(sdir)
        snap=json.loads((sdir/'state_snapshot.json').read_text()); s0=json.loads((sdir/'state.json').read_text()).get('state_hash')
        # ref pose straight from snapshot (project restore), independent of reconstructed scene
        (out/'orig'/rock).mkdir(parents=True,exist_ok=True)
        spec0,probe,sha0=M.make_scene(M.resample_walls(P0,o,pitch),out/'orig'/rock,rock)
        probe.restore_state(snap,mode='project')
        ref=(np.asarray(probe.data.qpos,float).copy(),np.asarray(probe.data.qvel,float).copy())
        for typ in [t for t in a.types.split(',') if t]:
            P=carve(P0,U,grid,typ)
            td=out/rock/typ/'truth'; td.mkdir(parents=True,exist_ok=True)
            tspec,_e,tsha=M.make_scene(M.resample_walls(P,o,pitch),td,f'{rock}_{typ}')
            tenv=wheelleg_env.WheelLegEnv(tspec,max_seconds=120); tenv.reset(seed=0); M.restore_common(tenv,snap,s0,mode='project',ref=ref)
            s0v=(np.asarray(tenv.data.qpos,float).copy(),np.asarray(tenv.data.qvel,float).copy())
            tcore={'spec':tspec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},
                   'state':{'state_id':f'wp2ext_{rock}_{typ}','state_hash':s0v[0].tobytes().hex()[:16]}}
            for arm in [x for x in a.arms.split(',') if x]:
                occ=M.resample_walls(P if arm=='PERFECT' else V,o,pitch)
                d=out/rock/typ/arm; d.mkdir(parents=True,exist_ok=True)
                spec,env,sha=M.make_scene(occ,d,'arm'); M.restore_common(env,snap,s0v[0].tobytes().hex()[:16],mode='project',ref=s0v)
                plan=plan_for(arm,P if arm=='PERFECT' else V,V,U,o,pitch)
                core={'spec':spec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},
                      'state':{'state_id':f'wp2ext_{rock}_{typ}_{arm}','state_hash':s0v[0].tobytes().hex()[:16]}}
                rr,_=v3_core.rehearse_on_spec(core,spec,snap,proto,mode='project',options=actions,body_plan=plan,budget=120.0,record_cells=True,record_root=d/'record')
                for r in rr:
                    tref=r.get('trajectory_ref')
                    if tref:
                        c=S6M.chassis_contacts_from_record(tref); r['chassis_contacts']=c
                        if c>0 and r.get('success'): r['success']=False; r['outcome']='chassis_contact'; r['reason']='chassis_obstacle_contact'
                    else: r['chassis_contacts']=None; r['success']=False; r['reason']='safety_unevaluated'
                    r['candidate']=arm
                    if arm=='OBS_CONS' and r['action'] in ('D1','D2') and r.get('success'):
                        r['success']=False; r['outcome']='unknown_detour_unsafe'; r['reason']='U_in_detour_band'
                dec=v3_core.aggregate(rr,[arm],{},'majority',proto,threshold_mode='majority',applic={x:(x!='CLIMB',None) for x in actions},options=actions)
                ex=v3_core.truth_execute(tcore,dec['chosen'],proto,out/'exec',f'{rock}_{typ}_{arm}',mode='project',body_plan=plan,budget=120.0)
                c=cost_from_record(out/'exec'/'record'/f'{rock}_{typ}_{arm}')
                try: cc=int(S6M.chassis_contacts_from_record({'trajectory_path':str(out/'exec'/'record'/f'{rock}_{typ}_{arm}'/'index.json')}))
                except Exception: cc=None
                rows.append({'rock':rock,'state':state,'unknown':typ,'arm':arm,'chosen':dec['chosen'],'outcome':ex.get('outcome'),
                             'reason':ex.get('reason'),'t_end':ex.get('t_end'),'chassis_contacts':cc,'safe_pass':bool(ex.get('outcome')=='pass' and cc==0),
                             'distance_m':c.get('distance_m'),'energy_J':c.get('energy_J'),'stops':c.get('stops'),'plan_id':plan['plan_id']})
                print(json.dumps(rows[-1],ensure_ascii=False)[:320],flush=True)
                with (out/'screen_rows.json').open('w') as f: json.dump(rows,f,ensure_ascii=False,indent=2)
    if rows:
        with (out/'screen_table.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    return 0
if __name__=='__main__': sys.exit(main())
