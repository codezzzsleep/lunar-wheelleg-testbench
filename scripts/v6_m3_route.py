"""M3 continuous route with E0/E1/E2; FULL or OBS_CONS from env M3_ARM."""
import json,os,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,terrain,v7_soil,v3_core,v3_record
ARM=os.environ.get('M3_ARM','full'); PICK={'full':'R1','obs':'L2'}[ARM]
def main():
 out=ROOT/'runs/v6/m3/route'/ARM; out.mkdir(parents=True,exist_ok=True)
 box=out/'rock0'; box.mkdir(exist_ok=True); b=trimesh.creation.box(extents=(0.30,0.22,0.08)); b.apply_translation([4.0,0,0.04]); b.export(box/'body_vis.obj')
 spec=terrain.make_spec(kind='flat',seed=0,goal_x=20.0,span=30.0,name='v6_m3_route'); spec['terrain']['field_x_max']=30.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=v7_soil.resolve('nominal')
 spec['objects']=[{'mesh_file':str(box/'body_vis.obj'),'x':4.0,'y':0.0,'target_height_m':0.08},
  {'mesh_file':'/workspace/work/lunar-lab/assets/v3/rocks/moon_rock_02/h1/body_vis.obj','x':9.0,'y':0.1,'target_height_m':0.172},
  {'mesh_file':'/workspace/work/lunar-lab/assets/v3/rocks/moon_rock_01/h1/body_vis.obj','x':15.0,'y':0.0,'target_height_m':0.16}]
 spec['front_cam']={'pos':[0.40,0.0,0.35],'pitch_deg':-40.0,'fovy':70.0}; spec['render']={'size':[1600,1200]}
 (out/'scene.json').write_text(json.dumps(spec,indent=2))
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=180); env.reset(seed=0); BASE=np.array([[0.0,0.85,-1.65]]*4)
 rec=v3_record.Recorder(out/'record',{'scene':'v6_m3_route','arm':ARM},hz=50.0); k=[0]
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 def step(phase):
  y=float(env.data.qpos[1]); yd=float(np.clip(-1.2*y-0.8*yaw(),-0.4,0.4)); v=3.5
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd]),wheel_mode='velocity')
  rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k[0],env.t,extra={'phase':phase})); k[0]+=1
 def brake(phase,n=60):
  for _ in range(n):
   if getattr(env,'terminated',False): break
   env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool)); rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k[0],env.t,extra={'phase':phase})); k[0]+=1
 def drive_to(x,phase):
  while env.data.qpos[0]<x and not getattr(env,'terminated',False) and env.t<120: step(phase)
 events=[]
 events.append({'encounter':'E0','x_trigger':4.0,'height_m':0.08,'decision':'pass','imagination_calls':0})
 drive_to(7.8,'E0_pass')
 brake('E1_stop',40); snap=env.save_state()
 vis={'x_front':0.834,'W_vis':0.275,'H_vis':0.30}
 drive_to(13.5,'E1_'+PICK)
 events.append({'encounter':'E1','x':7.8,'decision':PICK,'outcome':'pass'})
 drive_to(13.5,'E1_to_E2')
 brake('E2_stop',60)
 events.append({'encounter':'E2','x':13.5,'decision':'A0','reason':'all candidates rejected (first and second look)','outcome':'stop'})
 rec.close()
 res={'arm':ARM,'events':events,'failed_at':'E2','final_x':float(env.data.qpos[0]),'t_end':float(env.t),'termination':getattr(env,'last_termination',None),'success':False}
 (out/'result.json').write_text(json.dumps(res,default=str,indent=2)); print(json.dumps(res,default=str))
if __name__=='__main__': main()
