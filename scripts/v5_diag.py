"""Diagnose perturbation restores and action outcomes (review supplement 2)."""
import json,math,pathlib,sys
import numpy as np,trimesh,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_core,v3_register,wheelleg_env,stage8_matrix2 as M
name=sys.argv[1] if len(sys.argv)>1 else 'moon_rock_01_h0v0'; arm=sys.argv[2] if len(sys.argv)>2 else 'PERFECT'
d=ROOT/'runs/v3/states'/name; V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0)
tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
obs=v3_register.load_observation(str(d/'observation')); vis=C.visible_dims(d/'observation'); print('visible',vis)
sh=C.shadow_mask(V,g,obs) if arm=='OBS_CONS' else None
snap=json.loads((d/'state_snapshot.json').read_text()); spec_truth=json.loads((d/'scene_spec.json').read_text()); s0h=json.loads((d/'state.json').read_text()).get('state_hash')
env0=wheelleg_env.WheelLegEnv(spec_truth,max_seconds=120); env0.reset(seed=0); env0.restore_state(snap,mode='same_scene'); ref=(np.asarray(env0.data.qpos,float).copy(),np.asarray(env0.data.qvel,float).copy())
occ=T if arm=='PERFECT' else (V['shell']|sh if arm=='OBS_CONS' else V['shell'])
ad=ROOT/'runs/v5/diag'/name/arm; ad.mkdir(parents=True,exist_ok=True); spec,env,sha=M.make_scene(M.resample_walls(occ,V['origin'],float(V['pitch'])),ad,'arm'); M.restore_common(env,snap,s0h,mode='project',ref=ref)
def yaw():
 w,x,y,z=env.data.qpos[3:7]; return math.degrees(math.atan2(2*(w*z+x*y),1-2*(y*y+z*z)))
proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/stage6_protocol.json').read_text()); actions=[x for x in cfg['actions'] if x!='CLIMB']
plan={'raise_z':0.06,'ramp_steps':40,'speed':0.4,'lower_at_x':1.2,'end_x':2.6,'stop_tilt_deg':12.0,'plan_id':'diag'}
for pi,(dx,dy) in enumerate(((0.02,0.0),(-0.02,0.0),(0.0,2.0))):
 env.restore_state(snap,mode='project'); env.data.qpos[0]=ref[0][0]+dx; env.data.qvel[:]=ref[1]
 w1,x1,y1,z1=env.data.qpos[3:7].copy(); a=math.radians(dy)/2; w2,x2,y2,z2=math.cos(a),0,0,math.sin(a)
 env.data.qpos[3:7]=[w1*w2-x1*x2-y1*y2-z1*z2,w1*x2+x1*w2+y1*z2-z1*y2,w1*y2-x1*z2+y1*w2+z1*x2,w1*z2+x1*y2-y1*x2+z1*w2]
 mujoco.mj_forward(env.model,env.data); print(f'perturb {pi} dx={dx} dyaw={dy}: x={env.data.qpos[0]:.4f} yaw={yaw():.4f}')
 s2=env.save_state(); print('  saved x',s2.get('mjstate',[None])[0] if s2.get('mjstate') else None)
 rr,_=v3_core.rehearse_on_spec({'spec':spec,'snapshot':s2,'visible':vis,'state':{'state_id':name,'state_hash':s0h}},spec,s2,proto,mode='same_scene',options=actions,body_plan=plan,budget=120.0,record_cells=True,record_root=ad/f'p{pi}')
 for r in rr: print(' ',r['action'],r.get('success'),r.get('reason'),r.get('error_class'),r.get('outcome'),r.get('trajectory_ref',{}).get('trajectory_path') if isinstance(r.get('trajectory_ref'),dict) else None)
