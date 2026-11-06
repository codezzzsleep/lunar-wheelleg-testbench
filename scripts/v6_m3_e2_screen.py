"""R1 E2 screening: OBS conservative geometry must allow at least one safe wheel action."""
import json,pathlib,sys
import numpy as np,trimesh,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,terrain,v7_soil,v3_core,v5_metrics_ref as R,camera_io
from PIL import Image
ACTS=['R1','R2','D1','D2','L1','L2','BODY_CLEARANCE']
def main(rock,height):
 out=ROOT/'runs/v6/m3/E2screen'/f'{rock}_{height:.3f}'; out.mkdir(parents=True,exist_ok=True)
 st={'moon_rock_01':'moon_rock_01_h1v0','moon_rock_04':'moon_rock_04_h1v0','rock_07':'rock_07_h2v1','moon_rock_06':'moon_rock_06_h1v0'}[rock]
 mp=ROOT/'runs/v3/states'/st/'truth/body_world.stl'; mesh=trimesh.load(str(mp),force='mesh',process=False)
 sc=height/(mesh.bounds[1][2]-mesh.bounds[0][2]); mesh.apply_scale(sc); mesh.apply_translation([15.0-mesh.centroid[0],0.0,-mesh.bounds[0][2]])
 spec=terrain.make_spec(kind='flat',seed=0,goal_x=21.0,span=32.0,name=f'v6_e2_{rock}_{height}'); spec['terrain']['field_x_max']=32.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=v7_soil.resolve('nominal')
 d=out/'rock'; d.mkdir(exist_ok=True); vis=d/'body_vis.obj'; mesh.export(vis)
 spec['objects']=[{'mesh_file':str(vis),'x':15.0,'y':0.0,'target_height_m':height}]; spec['front_cam']={'pos':[0.40,0,0.35],'pitch_deg':-25.0,'fovy':70.0}; spec['render']={'size':[1600,1200]}
 print('mesh bounds',mesh.bounds.tolist(),'scale',sc)
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0); print('obs xpos',env.data.xpos[mujoco.mj_name2id(env.model,mujoco.mjtObj.mjOBJ_BODY,'obstacle0')].tolist()); BASE=np.array([[0,0.85,-1.65]]*4)
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 while env.data.qpos[0]<13.5 and not getattr(env,'terminated',False) and env.t<90:
  y=float(env.data.qpos[1]); yd=float(np.clip(-1.2*y-0.8*yaw(),-0.4,0.4)); v=3.5
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd]),wheel_mode='velocity')
 for _ in range(40): env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool))
 qpos0=np.asarray(env.data.qpos,float).copy(); qvel0=np.asarray(env.data.qvel,float).copy(); snap=env.save_state(); m=env.model
 g={'origin':np.array([14.4,-0.6,-0.05]),'pitch':0.004}; dims=(220,300,100); g['dims']=np.array(dims); g['xs']=g['origin'][0]+(np.arange(dims[0])+0.5)*0.004; g['ys']=g['origin'][1]+(np.arange(dims[1])+0.5)*0.004; g['zs']=g['origin'][2]+(np.arange(dims[2])+0.5)*0.004
 import v5_metrics_ref as Rg
 occ=Rg.column_fill_top(mesh,g)  # conservative: truth solid as worst case
 print('occ sum',int(occ.sum()))
 np.savez_compressed(out/'occ.npz',occupied=occ,origin=g['origin'],pitch=np.float64(0.004),dims=g['dims'],content_sha=np.array(f'e2_{rock}_{height}'),convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
 coll=out/'coll'; v3_core.build_collision(out/'occ.npz',coll,pitch=0.004,downsample=1)
 arm_spec=json.loads(json.dumps(spec)); arm_spec['objects']=[{'posed_dir':str(coll)}]
 rows=[]
 for a in ACTS:
  try:
   arm=wheelleg_env.WheelLegEnv(arm_spec,max_seconds=90); arm.reset(seed=0)
   arm.data.qpos[:]=qpos0; arm.data.qvel[:]=qvel0
   mujoco.mj_forward(arm.model,arm.data); sa=arm.save_state()
   res=v3_core.run_action(arm,sa,a,{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},mode='same_scene',record_dir=out/a)
   rows.append({'action':a,'success':bool(res.get('success')),'contacts':res.get('contacts')})
  except Exception as e:
   import traceback; rows.append({'action':a,'success':False,'error':traceback.format_exc()[-500:]})
 safe=[x['action'] for x in rows if x['success']]
 (out/'screen.json').write_text(json.dumps({'rock':rock,'height_m':height,'actions':rows,'safe':safe},indent=2))
 print(rock,height,'safe',safe)
if __name__=='__main__': main(sys.argv[1],float(sys.argv[2]))
