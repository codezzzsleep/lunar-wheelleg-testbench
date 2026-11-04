"""新配准候选的真实对照：ref/len_short 上六候选多数、首候选、最坏与 OBS。"""
import argparse, hashlib, json, pathlib, sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_core, wheelleg_env, stage8_matrix2 as M, stage6_matrix as S6M

TASKS=['4632564','4632603','4632618','4632621','4632624','4632627']

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--scenario',required=True); ap.add_argument('--out',default='runs/v3/stage012/compare')
    a=ap.parse_args()
    out=(ROOT/a.out)/a.scenario; out.mkdir(parents=True,exist_ok=True)
    truth=ROOT/'runs/v3/stage008/truth_v2'
    tm=json.loads((truth/'truth_manifest.json').read_text()); snap=json.loads((truth/'state_snapshot.json').read_text())
    fsum=json.loads((ROOT/'runs/v3/stage012/fusion/fusion_summary.json').read_text())
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text())
    actions=cfg['actions']; s0=tm['s0_state_hash']
    zv=np.load(truth/'fusion/V.npz'); V=zv['shell']; U=(zv['space']==0); o=np.asarray(zv['origin'],float); p=float(zv['pitch'])
    ts=json.loads((truth/'scene_spec.json').read_text())
    ref_env=wheelleg_env.WheelLegEnv(ts,max_seconds=120); ref_env.reset(seed=0); ref_env.restore_state(snap,mode='same_scene')
    s0_ref=(np.asarray(ref_env.data.qpos,float).copy(),np.asarray(ref_env.data.qvel,float).copy())
    # 场景与真值
    if a.scenario=='ref':
        tspec=ts; tmode='same_scene'; truth_proj=None
    else:
        z=np.load(ROOT/'runs/v3/stage010/g1v2'/f'occ2_{a.scenario}.npz')
        occ=M.resample_walls(z['P'],np.asarray(z['origin'],float),float(z['pitch']))
        tmp=out/'truth_scene'; tmp.mkdir(parents=True,exist_ok=True)
        tspec,_e,tsha=M.make_scene(occ,tmp,f'{a.scenario}_truth'); tmode='project'
    core={'spec':tspec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},
          'state':{'state_id':f'stage12_{a.scenario}','state_hash':s0}}
    rows={}; geom={}
    for t in TASKS:
        occ_full=np.load(ROOT/'runs/v3/stage012/fusion'/f'task_{t}'/'occ_full.npz')['occupied']
        rear=float(fsum['candidates'][t]['hidden_rear_x']); plan=dict(fsum['plans']['full']); plan['lower_at_x']=round(rear+0.10,4)
        plan['plan_id']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()[:16]
        occ4=M.resample_walls(occ_full,o,p); d=out/f'cand_{t}'; d.mkdir(parents=True,exist_ok=True)
        spec,env,sha=M.make_scene(occ4,d,'full'); M.restore_common(env,snap,s0,mode='project',ref=s0_ref)
        core_i=dict(core,spec=spec)
        rr,_=v3_core.rehearse_on_spec(core_i,spec,snap,proto,mode='project',options=actions,body_plan=plan,budget=120.0)
        for r in rr:
            tref=r.get('trajectory_ref')
            if tref:
                c=S6M.chassis_contacts_from_record(tref); r['chassis_contacts']=c
                if c>0 and r.get('success'): r['success']=False; r['outcome']='chassis_contact'
            r['candidate']=t
        rows[t]=rr; geom[t]=sha
        print(t,'done',round(rear,3),flush=True)
    applic={a:(a!='CLIMB', None if a!='CLIMB' else 'climb_not_applicable') for a in actions}
    dec=v3_core.aggregate(sum(rows.values(),[]),TASKS,geom,'majority',proto,threshold_mode='majority',applic=applic,options=actions)
    # OBS 单臂
    occ_obs=V; d=out/'obs'; d.mkdir(parents=True,exist_ok=True)
    spec,env,osha=M.make_scene(M.resample_walls(occ_obs,o,p),d,'obs'); M.restore_common(env,snap,s0,mode='project',ref=s0_ref)
    obs_plan=dict(fsum['plans']['obs'])
    orows,_=v3_core.rehearse_on_spec(dict(core,spec=spec),spec,snap,proto,mode='project',options=actions,body_plan=obs_plan,budget=120.0)
    for r in orows:
        tref=r.get('trajectory_ref')
        if tref:
            c=S6M.chassis_contacts_from_record(tref); r['chassis_contacts']=c
            if c>0 and r.get('success'): r['success']=False; r['outcome']='chassis_contact'
        r['candidate']='OBS'
    dec_obs=v3_core.aggregate(orows,['OBS'],{},'majority',proto,threshold_mode='majority',applic=applic,options=actions)
    # 执行：多数 FULL 与 OBS 都在真值场景
    res={'scenario':a.scenario,'full_votes':dec['votes'],'full_chosen':dec['chosen'],'obs_votes':dec_obs['votes'],'obs_chosen':dec_obs['chosen'],'per_candidate':{t:[{'action':r['action'],'success':r['success'],'cost':r['cost']} for r in rows[t]] for t in TASKS}}
    for arm,ch,plan in (('full',dec['chosen'],fsum['plans']['full']),('obs',dec_obs['chosen'],obs_plan)):
        ex=v3_core.truth_execute(core,ch,proto,out/'exec',arm.upper(),mode=tmode,
                                 body_plan=(dict(plan, lower_at_x=round(float(fsum['candidates']['4632564']['hidden_rear_x'])+0.10,4)) if arm=='full' else plan),
                                 budget=120.0)
        res[arm]={'action':ex.get('action'),'outcome':ex.get('outcome'),'t_end':ex.get('t_end'),
                  'safe_pass':ex.get('safe_pass'),'chassis_contacts':ex.get('chassis_contacts'),'reached':ex.get('reached')}
        print(arm,res[arm],flush=True)
    (out/'result.json').write_text(json.dumps(res,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': sys.exit(main())
