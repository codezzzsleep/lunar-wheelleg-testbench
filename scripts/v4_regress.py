"""WP1 回归测试 T1–T6（一条命令）。"""
import json, pathlib, sys, time
import numpy as np, trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_core, v3_fuse, v3_record, wheelleg_env, skills, runner, stage6_body_skill as SB
import stage8_matrix2 as M, stage6_matrix as S6M, stage10_scenes_v2 as S10
import v3_register

OUT=ROOT/'runs/v4/regress'; OUT.mkdir(parents=True,exist_ok=True)
TRUTH=ROOT/'runs/v3/stage008/truth_v2'

def load_env(spec,snap,mode='same_scene',ref=None):
    env=wheelleg_env.WheelLegEnv(spec,max_seconds=120.0); env.reset(seed=0)
    if ref is None: env.restore_state(snap,mode=mode)
    else: M.restore_common(env,snap,'',mode='project',ref=ref)
    env.data.qacc_warmstart[:]=0.0
    import mujoco; mujoco.mj_forward(env.model,env.data)
    return env

def t1():
    z=np.load(TRUTH/'fusion/V.npz'); V=z['shell']; U=(z['space']==0)
    o=np.asarray(z['origin'],float); p=float(z['pitch'])
    mesh=trimesh.load(str(TRUTH/'truth/body_world.stl'),force='mesh',process=False)
    grid={'origin':o,'pitch':p,'dims':np.array(z['dims'])}
    dims=tuple(int(x) for x in z['dims'])
    grid['xs']=o[0]+(np.arange(dims[0])+0.5)*p; grid['ys']=o[1]+(np.arange(dims[1])+0.5)*p; grid['zs']=o[2]+(np.arange(dims[2])+0.5)*p
    P,_=v3_fuse.voxelize_columns(mesh,grid)
    perfect=V|(P&U)
    diff=perfect^V
    outside=int((diff&~U).sum())
    inter=int((perfect&P&U).sum()); uni=int(((perfect|P)&U).sum())
    iou=inter/max(1,uni)
    return {'pass':bool(outside==0 and iou==1.0),'hidden_iou':round(iou,6),'diff_outside_U':outside}

def t2():
    obs=v3_register.load_observation(str(TRUTH/'observation'))
    W=trimesh.load(str(TRUTH/'truth/body_world.stl'),force='mesh',process=False)
    P=np.asarray(W.vertices,float); S=0.37; a=np.deg2rad(-11.0)
    A=S*np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1]])
    b=P.mean(0)-A@P.mean(0)
    local=(P-b)@np.linalg.inv(A).T
    tmp=OUT/'local'; tmp.mkdir(parents=True,exist_ok=True)
    lp=tmp/'candidate_local.stl'; trimesh.Trimesh(local,W.faces,process=False).export(lp)
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text())
    rec=v3_register.register(str(lp),str(TRUTH/'observation'),proto,tmp/'align',top_k=8)
    dg=rec['best']['diagnostics']
    return {'pass':bool(dg['mask_iou']>=0.90 and dg['depth_p95_mm']<=20.0),'mask_iou':dg['mask_iou'],'depth_p95_mm':dg['depth_p95_mm']}

def scene_len_short():
    base=ROOT/'runs/v3/stage010/g1v2'; z=base/'occ2_len_short.npz'
    if not z.exists():
        S10.main() if False else None
        import subprocess; subprocess.check_call([sys.executable,str(ROOT/'scripts/stage10_scenes_v2.py')])
    zz=np.load(z)
    occ=M.resample_walls(zz['P'],np.asarray(zz['origin'],float),float(zz['pitch']))
    d=OUT/'len_short'; d.mkdir(parents=True,exist_ok=True)
    spec,_e,sha=M.make_scene(occ,d,'len_short')
    return spec,sha

def run_episode(spec,snap,action,record_dir,mode='project',ref=None,body_plan=None,max_steps=None):
    env=load_env(spec,snap,mode=mode,ref=ref)
    if action=='BODY':
        plan=dict(body_plan or {}); plan.setdefault('raise_z',0.06); plan.setdefault('ramp_steps',100)
        plan.setdefault('speed',0.15); plan.setdefault('lower_at_x',1.165); plan.setdefault('end_x',2.8)
        plan.setdefault('stop_tilt_deg',12.0); plan['plan_id']='regress_body'
        rec=v3_core.run_body_clearance_cell(spec,snap,plan,json.loads((ROOT/'plans/v3_protocol.json').read_text()),
                                            mode=mode,record_dir=record_dir,budget=120.0)
        while not env.terminated and env.t<120:
            env.brake_step()
        return env,rec
    sk=skills.make_skill(action)
    ep=runner.EpisodeRunner(env,sk,visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},
                            max_steps=max_steps or 6000,seed=0,record_trajectory=True)
    import v3_record
    rec=v3_record.Recorder(record_dir,{'action':action,'method':'regress'},hz=50.0)
    ep.recorder=rec; ep.record_trajectory=True
    out=ep.run_from_state(snap,mode=mode); ref_traj=rec.close()
    return env,out,ref_traj

def last_frame_t(rec_dir):
    chunks=sorted(pathlib.Path(rec_dir).glob('chunk_*.npz'))
    if not chunks: return None
    t=np.concatenate([np.load(c)['t'] for c in chunks]); return float(t[-1])

def t3():
    spec,sha=scene_len_short(); snap=json.loads((TRUTH/'state_snapshot.json').read_text())
    d=OUT/'t3'; d.mkdir(parents=True,exist_ok=True)
    # D2
    env,out,ref=run_episode(spec,snap,'D2',d/'d2')
    t3d=last_frame_t(d/'d2'); ok_d2=bool(out['success'] and t3d is not None and abs(t3d-out['t_end'])<1e-6)
    # BODY：先按技能，再推进到共同终点
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text())
    env=load_env(spec,snap,mode='project',ref=None)
    env.restore_state(snap,mode='project')
    env.data.qacc_warmstart[:]=0.0
    plan={'raise_z':0.06,'ramp_steps':100,'speed':0.15,'lower_at_x':1.165,'end_x':2.6,'stop_tilt_deg':12.0,'plan_id':'regress_body'}
    rec=v3_record.Recorder(d/'body',{'action':'BODY','method':'regress'},hz=50.0)
    row=SB.run_body_clearance(env,plan,recorder=rec,close=False)
    targets={leg:dict(__import__('v3_basic_cycle').STANCE) for leg in __import__('v3_basic_cycle').LEG}
    kk=100000
    while (not env.terminated and env.t<120 and min(env._wheel_xs())<float(spec.get('goal_x',2.6))+0.02):
        env.step_command(joint_targets_rad=targets,wheel_omega_rad_s=np.full(4,0.15/0.086),wheel_mode='velocity')
        rec.add(v3_record.frame_from_env(env,None,[0,0,0],kk,env.t,extra={'phase':'task_drive'})); kk+=1
    while not env.terminated and env.t<120:
        env.step_command(joint_targets_rad=targets,wheel_brake=np.ones(4,bool))
        rec.add(v3_record.frame_from_env(env,None,[0,0,0],kk,env.t,extra={'phase':'task_settle'})); kk+=1
    ref_b=rec.close(); t3b=last_frame_t(d/'body')
    term=dict(getattr(env,'last_termination',{}) or {})
    ok_b=bool(term.get('reason')=='success' and t3b is not None and abs(t3b-float(env.t))<1e-6)
    return {'pass':bool(ok_d2 and ok_b),'d2':{'success':out['success'],'t_end':out['t_end'],'last_frame':t3d},
            'body':{'success':term.get('reason')=='success','t_end':float(env.t),'last_frame':t3b}}

def t4():
    spec=json.loads((TRUTH/'scene_spec.json').read_text()); snap=json.loads((TRUTH/'state_snapshot.json').read_text())
    env=load_env(spec,snap,mode='same_scene')
    sk=skills.make_skill('D2')
    ep=runner.EpisodeRunner(env,sk,visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=10,seed=0)
    out=ep.run_from_state(snap,mode='same_scene')
    truncated=bool(out['steps']>=10 and out.get('reason') is None)
    return {'pass':truncated,'steps':out['steps'],'reason':out.get('reason'),'truncated_by_cap':truncated}

def t5():
    spec=json.loads((TRUTH/'scene_spec.json').read_text()); snap=json.loads((TRUTH/'state_snapshot.json').read_text())
    d=OUT/'t5'; d.mkdir(parents=True,exist_ok=True)
    _,o1,r1=run_episode(spec,snap,'D2',d/'project',mode='project',max_steps=50)
    _,o2,r2=run_episode(spec,snap,'D2',d/'same',mode='same_scene',max_steps=50)
    import numpy as np
    def q(rd):
        c=sorted(pathlib.Path(rd).glob('chunk_*.npz')); return np.concatenate([np.load(x)['qpos'] for x in c])
    q1,q2=q(d/'project'),q(d/'same'); n=min(len(q1),len(q2))
    md=float(np.abs(q1[:n]-q2[:n]).max())
    return {'pass':bool(md<1e-6),'n_frames':int(n),'max_qpos_diff':md}

def t6():
    rec=OUT/'t5'/'project'; chunks=sorted(rec.glob('chunk_*.npz'))
    if not chunks: return {'pass':False,'error':'no frames'}
    z=np.load(chunks[0]); t=np.concatenate([np.load(c)['t'] for c in chunks])
    dt=float(np.median(np.diff(t))) if len(t)>1 else None
    keys=set(z.files)
    contacts_sidecar=any(rec.glob('contacts_*.jsonl'))
    need={'qpos','qvel','action_raw','joint_target','wheel_omega_target','t','wheel_sinkage_m','wheel_slip_ratio'}
    missing=sorted(need-keys)
    rate_ok=dt is not None and dt<=0.021
    sink=z['wheel_sinkage_m'] if 'wheel_sinkage_m' in keys else None
    slip=z['wheel_slip_ratio'] if 'wheel_slip_ratio' in keys else None
    return {'pass':bool(rate_ok and not missing and sink is not None and slip is not None and contacts_sidecar),
            'dt':dt,'missing':missing,'has_sinkage':sink is not None,'has_slip':slip is not None,'contacts_sidecar':contacts_sidecar}

def main():
    res={'schema':'v4-regress/v1','at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'tests':{}}
    for name,fn in (('T1',t1),('T2',t2),('T4',t4)):
        try: res['tests'][name]=fn()
        except Exception as e: res['tests'][name]={'pass':False,'error':f'{type(e).__name__}: {e}'}
        print(name,res['tests'][name],flush=True)
    for name,fn in (('T5',t5),('T6',t6)):
        try: res['tests'][name]=fn()
        except Exception as e: res['tests'][name]={'pass':False,'error':f'{type(e).__name__}: {e}'}
        print(name,res['tests'][name],flush=True)
    try: res['tests']['T3']=t3()
    except Exception as e: res['tests']['T3']={'pass':False,'error':f'{type(e).__name__}: {e}'}
    print('T3',res['tests']['T3'],flush=True)
    p=OUT/f"{time.strftime('%Y%m%dT%H%M%S')}.json"; p.write_text(json.dumps(res,ensure_ascii=False,indent=2))
    res['path']=str(p); print(json.dumps({'path':str(p),'all_pass':all(v.get('pass') for v in res['tests'].values())}))
    return 0
if __name__=='__main__': sys.exit(main())
