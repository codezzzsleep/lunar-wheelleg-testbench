"""正式候选对照：门控、逐格记录、固定计划、决策先落盘。"""
import argparse, hashlib, json, pathlib, sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_core, wheelleg_env, stage8_matrix2 as M, stage6_matrix as S6M

TASKS=['4632564','4632603','4632618','4632621','4632624','4632627']
GATE={'mask_iou_min':0.90,'depth_p95_max_mm':20.0}

def qualify_candidates(registration, generated_ids=TASKS):
    """Only generated Lux3D ids enter the denominator; diagnostic controls stay separate."""
    out={}
    for t in generated_ids:
        c=registration.get(t)
        dg=(c or {}).get('diagnostics') or (c or {}).get('diag') or {}
        iou=dg.get('mask_iou'); p95=dg.get('depth_p95_mm')
        good=(iou is not None and p95 is not None
              and float(iou)>=GATE['mask_iou_min']
              and float(p95)<=GATE['depth_p95_max_mm'])
        reasons=[]
        if iou is None: reasons.append('missing_mask_iou')
        elif float(iou)<GATE['mask_iou_min']: reasons.append('mask_iou_below_gate')
        if p95 is None: reasons.append('missing_depth_p95')
        elif float(p95)>GATE['depth_p95_max_mm']: reasons.append('depth_p95_above_gate')
        if c is None: reasons.append('registration_missing')
        out[t]={'mask_iou':iou,'depth_p95_mm':p95,'qualified':bool(good),
                'rejection_reasons':reasons}
    return out

def load_registration(path=None):
    p=pathlib.Path(path) if path else ROOT/'runs/v3/stage012/registered/registration.json'
    d=json.loads(p.read_text())
    return d,qualify_candidates(d.get('candidates',{}))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--scenario',default='ref')
    ap.add_argument('--tasks',default=','.join(TASKS)); ap.add_argument('--out',default='runs/v3/stage012/compare')
    ap.add_argument('--registered',default='runs/v3/stage012/registered')
    ap.add_argument('--fusion',default='runs/v3/stage012/fusion')
    ap.add_argument('--explore',action='store_true',help='对不合格候选也跑矩阵，仅探索诊断，不进入正式投票')
    a=ap.parse_args(); tasks=[t for t in a.tasks.split(',') if t]
    out=(ROOT/a.out)/a.scenario; out.mkdir(parents=True,exist_ok=True)
    truth=ROOT/'runs/v3/stage008/truth_v2'
    registered=(ROOT/a.registered).resolve(); fusion=(ROOT/a.fusion).resolve()
    tm=json.loads((truth/'truth_manifest.json').read_text()); snap=json.loads((truth/'state_snapshot.json').read_text())
    fsum=json.loads((fusion/'fusion_summary.json').read_text())
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text())
    actions=cfg['actions']; s0=tm['s0_state_hash']; reg_record,reg_all=load_registration(registered/'registration.json')
    reg={t:reg_all[t] for t in tasks if t in reg_all}
    qualified=[t for t in tasks if reg.get(t,{}).get('qualified')]
    ts=json.loads((truth/'scene_spec.json').read_text())
    ref_env=wheelleg_env.WheelLegEnv(ts,max_seconds=120); ref_env.reset(seed=0); ref_env.restore_state(snap,mode='same_scene')
    s0_ref=(np.asarray(ref_env.data.qpos,float).copy(),np.asarray(ref_env.data.qvel,float).copy())
    if a.scenario=='ref':
        tspec=ts; tmode='same_scene'; truth_sha=tm['truth_occ_sha256']
    else:
        z=np.load(ROOT/'runs/v3/stage010/g1v2'/f'occ2_{a.scenario}.npz')
        occ=M.resample_walls(z['P'],np.asarray(z['origin'],float),float(z['pitch']))
        tmp=out/'truth_scene'; tmp.mkdir(parents=True,exist_ok=True)
        tspec,_e,truth_sha=M.make_scene(occ,tmp,f'{a.scenario}_truth'); tmode='project'
    core={'spec':tspec,'snapshot':snap,'visible':{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},
          'state':{'state_id':f'stage12_{a.scenario}','state_hash':s0}}
    plan_full=dict(fsum['plans']['full'])          # 固定一份计划，所有候选共用
    rows_all=[]; geom={}; per={}
    run_tasks = tasks if a.explore else qualified
    for t in run_tasks:
        occ_full=np.load(fusion/f'task_{t}'/'occ_full.npz')['occupied']
        d=out/f'cand_{t}'; d.mkdir(parents=True,exist_ok=True)
        occ4=M.resample_walls(occ_full,np.asarray(np.load(fusion/f'task_{t}'/'occ_full.npz')['origin'],float),float(np.load(fusion/f'task_{t}'/'occ_full.npz')['pitch']))
        spec,env,sha=M.make_scene(occ4,d,'full'); M.restore_common(env,snap,s0,mode='project',ref=s0_ref)
        rr,_=v3_core.rehearse_on_spec(dict(core,spec=spec),spec,snap,proto,mode='project',options=actions,
                                      body_plan=plan_full,budget=120.0,record_cells=True,
                                      record_root=d/'record')
        for r in rr:
            tref=r.get('trajectory_ref')
            if tref:
                c=S6M.chassis_contacts_from_record(tref); r['chassis_contacts']=c
                if c>0 and r.get('success'):
                    r['success']=False; r['outcome']='chassis_contact'; r['reason']='chassis_obstacle_contact'
            else:
                r['chassis_contacts']=None; r['outcome']='safety_unevaluated'
                r['reason']='safety_unevaluated'; r['success']=False
            r['candidate']=t
        rows_all+=rr; geom[t]=sha; per[t]=rr
        print(t,'done',flush=True)
    # OBS 单臂（同一 S0、同一计划集）
    zv=np.load(truth/'fusion/V.npz'); V=zv['shell']; o=np.asarray(zv['origin'],float); p=float(zv['pitch'])
    d=out/'obs'; d.mkdir(parents=True,exist_ok=True)
    spec,env,osha=M.make_scene(M.resample_walls(V,o,p),d,'obs'); M.restore_common(env,snap,s0,mode='project',ref=s0_ref)
    obs_plan=dict(fsum['plans']['obs'])
    orows,_=v3_core.rehearse_on_spec(dict(core,spec=spec),spec,snap,proto,mode='project',options=actions,
                                     body_plan=obs_plan,budget=120.0,record_cells=True,record_root=d/'record')
    for r in orows:
        tref=r.get('trajectory_ref')
        if tref:
            c=S6M.chassis_contacts_from_record(tref); r['chassis_contacts']=c
            if c>0 and r.get('success'):
                r['success']=False; r['outcome']='chassis_contact'; r['reason']='chassis_obstacle_contact'
        else:
            r['chassis_contacts']=None; r['outcome']='safety_unevaluated'; r['reason']='safety_unevaluated'; r['success']=False
        r['candidate']='OBS'
    applic={a:(a!='CLIMB', None if a!='CLIMB' else 'climb_not_applicable') for a in actions}
    dec_obs=v3_core.aggregate(orows,['OBS'],{},'majority',proto,threshold_mode='majority',applic=applic,options=actions)
    res={'schema':'stage12-compare/v2','scenario':a.scenario,'gate':GATE,
         'registration_run_id':reg_record.get('run_id'),
         'registration_manifest_sha256':reg_record.get('manifest_sha256'),
         'registration':reg,'qualified':qualified,
         'generated_denominator':len(TASKS),
         'registration_evaluated_denominator':len(reg_record.get('candidates',{})),
         'matrix_run_denominator':len(run_tasks),
         'matrix_run_ids':run_tasks,
         'diagnostic_assets_excluded_from_denominator':reg_record.get('diagnostic_assets',[]),
         'rejections':{t:(reg.get(t,{}).get('rejection_reasons') or ['qualified']) for t in tasks},
         'obs':{'votes':dec_obs['votes'],'chosen':dec_obs['chosen']},
         'exploratory_only':bool(a.explore),
         'ran_candidates':run_tasks}
    if qualified and not a.explore:
        dec=v3_core.aggregate(rows_all,qualified,geom,'majority',proto,threshold_mode='majority',
                              applic=applic,options=actions)
        res['full']={'votes':dec['votes'],'chosen':dec['chosen'],'n_valid':dec['n_valid']}
        # 决策先落盘，再执行；执行不再改计划参数
        drec_f=v3_core.write_decision(out,core, 'FULL', rows_all, dec, {'plan':plan_full,'truth_sha':truth_sha,'s0_state_hash':s0,'matrix_candidate_ids':qualified})
        drec_o=v3_core.write_decision(out,core, 'OBS', orows, dec_obs, {'plan':obs_plan,'truth_sha':truth_sha,'s0_state_hash':s0})
        for arm,ch,plan,drec in (('full',dec['chosen'],plan_full,drec_f),('obs',dec_obs['chosen'],obs_plan,drec_o)):
            ex=v3_core.truth_execute(core,ch,proto,out/'exec',arm.upper(),mode=tmode,body_plan=plan,budget=120.0)
            res[arm]={'action':ex.get('action'),'outcome':ex.get('outcome'),'reason':ex.get('reason'),
                      't_end':ex.get('t_end'),'safe_pass':ex.get('safe_pass'),
                      'chassis_contacts':ex.get('chassis_contacts'),'reached':ex.get('reached'),
                      'decision_sha':drec['decision_sha'],'plan_id':plan.get('plan_id')}
    elif not a.explore:
        # Zero-qualified formal result: FULL inherits the exact OBS action and plan.
        effective=dec_obs['chosen']; effective_plan=obs_plan
        full_dec={'rule':'zero-qualified/fallback-to-OBS/v1','n_tasks':len(TASKS),
                  'n_registered':len(reg),'n_qualified':0,'votes':{},
                  'chosen':effective,'effective_chosen':effective,
                  'fallback_reason':'zero_qualified_candidates','fallback_arm':'OBS',
                  'plan_id':effective_plan.get('plan_id')}
        drec_o=v3_core.write_decision(out,core,'OBS',orows,dec_obs,
                         {'plan':effective_plan,'truth_sha':truth_sha,'s0_state_hash':s0})
        drec_f=v3_core.write_decision(out,core,'FULL',[],full_dec,
                         {'plan':effective_plan,'truth_sha':truth_sha,'s0_state_hash':s0,
                          'fallback_reason':'zero_qualified_candidates',
                          'effective_chosen':effective,
                          'fallback_from_decision_sha':drec_o['decision_sha']})
        ex=v3_core.truth_execute(core,effective,proto,out/'exec','OBS_FALLBACK_SHARED',
                                 mode=tmode,body_plan=effective_plan,budget=120.0)
        shared={'action':effective,'outcome':ex.get('outcome'),'reason':ex.get('reason'),
                't_end':ex.get('t_end'),'cost':ex.get('cost'),
                'safe_pass':ex.get('safe_pass'),'chassis_contacts':ex.get('chassis_contacts'),
                'reached':ex.get('reached'),'plan_id':effective_plan.get('plan_id'),
                'trajectory_ref':ex.get('trajectory_ref'),'execution_id':ex.get('run_id'),
                'independent_sample':False}
        res['full']={'chosen':effective,'effective_chosen':effective,
                     'fallback_reason':'zero_qualified_candidates',
                     'plan_id':effective_plan.get('plan_id'),
                     'decision_sha':drec_f['decision_sha'],'execution_ref':'shared_obs_fallback'}
        res['obs'].update({'effective_chosen':effective,'plan_id':effective_plan.get('plan_id'),
                           'decision_sha':drec_o['decision_sha'],'execution_ref':'shared_obs_fallback'})
        res['shared_fallback_execution']=shared
    (out/'result.json').write_text(json.dumps(res,ensure_ascii=False,indent=2))
    print(json.dumps({k:res.get(k) for k in ('qualified','full','obs')},ensure_ascii=False)[:800])
    return 0
if __name__=='__main__': sys.exit(main())
