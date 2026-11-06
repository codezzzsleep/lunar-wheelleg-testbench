"""M3 E0: small rubble (<0.10 m) on the route; wheels pass without imagination."""
import json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,terrain,v7_soil
def main():
 out=ROOT/'runs/v6/m3/E0'; out.mkdir(parents=True,exist_ok=True)
 d=out/'rock'; d.mkdir(exist_ok=True)
 m=trimesh.creation.box(extents=(0.30,0.22,0.08)); m.apply_translation([4.0,0.0,0.04]); m.export(d/'body_vis.obj')
 spec=terrain.make_spec(kind='flat',seed=0,goal_x=20.0,span=30.0,name='v6_m3_e0'); spec['terrain']['field_x_max']=30.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=v7_soil.resolve('nominal')
 spec['objects']=[{'mesh_file':str(d/'body_vis.obj'),'x':4.0,'y':0.0,'yaw_deg':0.0,'target_height_m':0.08}]
 spec['front_cam']={'pos':[0.40,0.0,0.35],'pitch_deg':-40.0,'fovy':70.0}; spec['render']={'size':[1600,1200]}
 (out/'scene.json').write_text(json.dumps(spec,indent=2))
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0); BASE=np.array([[0.0,0.85,-1.65]]*4)
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 while env.data.qpos[0]<20.0 and not getattr(env,'terminated',False) and env.t<90:
  y=float(env.data.qpos[1]); yd=float(np.clip(-1.2*y-0.8*yaw(),-0.4,0.4)); v=3.5
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd]),wheel_mode='velocity')
 for _ in range(5):
  if getattr(env,'terminated',False): break
  env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool))
 res={'encounter':'E0','rock_height_m':0.08,'trigger':False,'imagination_calls':0,'arms':['FULL','OBS_CONS'],'final_x':float(env.data.qpos[0]),'t_end':float(env.t),'termination':getattr(env,'last_termination',None),'success':float(env.data.qpos[0])>=19.5 and (getattr(env,'last_termination',{}) or {}).get('reason','') in ('success','')}
 (out/'result.json').write_text(json.dumps(res,indent=2,default=str)); print(json.dumps(res,default=str))
if __name__=='__main__': main()
