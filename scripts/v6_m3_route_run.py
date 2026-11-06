"""R2 M3 route execution (headless): E0 pass, E1 decision, E2 conservative, goal 21."""
import json,os,pathlib,sys
import numpy as np,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v6_m3_route2 as RW,wheelleg_env,v3_core,v3_record
ARM=os.environ.get('M3_ARM','full'); DEC={'full':{'E1':'R2','E2':'R1'},'obs':{'E1':'R1','E2':'R1'}}[ARM]
def main():
 out=ROOT/'runs/v6/m3/route2'/f'run_{ARM}'; out.mkdir(parents=True,exist_ok=True)
 spec=RW.make_route_spec(); gm1=json.loads((ROOT/'runs/v6/m3/route2/E1/geometry.json').read_text()); gm2=json.loads((ROOT/'runs/v6/m3/route2/E2/geometry.json').read_text())
 spec['objects'][1]={'mesh_file':str(ROOT/gm1['rock_mesh']),'x':9.0,'y':0.1,'target_height_m':gm1['height']}
 spec['objects'][2]={'mesh_file':str(ROOT/gm2['rock_mesh']),'x':15.0,'y':0.1,'target_height_m':gm2['height']}
 spec['front_cam']={'pos':gm1['cam_local'],'pitch_deg':gm1['pitch_deg'],'fovy':70.0}
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=200); env.reset(seed=0); BASE=np.array([[0,0.85,-1.65]]*4)
 rec=v3_record.Recorder(out/'record',{'scene':'route2','arm':ARM},hz=50.0); k=[0]
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 def add(act,phase):
  rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k[0],env.t,extra={'action':act,'phase':phase,'ctrl':np.asarray(env.data.ctrl,float).tolist()})); k[0]+=1
 def drive_to(x,act,phase,limit_t=160):
  while env.data.qpos[0]<x and not getattr(env,'terminated',False) and env.t<limit_t:
   y=float(env.data.qpos[1]); yd=float(np.clip(-1.2*y-0.8*yaw(),-0.4,0.4)); v=3.5
   env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd]),wheel_mode='velocity'); add(act,phase)
 def stop(phase,n=40):
  for _ in range(n):
   if getattr(env,'terminated',False): break
   env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool)); add('OBSERVE',phase)
 events=[]
 drive_to(7.653,'CRUISE','E0_gravel'); stop('E1_observe'); snap=env.save_state(); events.append({'encounter':'E0','action':'CRUISE','x':float(env.data.qpos[0])})
 act=DEC['E1']; r=v3_core.run_action(env,snap,act,{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},mode='same_scene',record_dir=out/f'E1_{act}'); events.append({'encounter':'E1','action':act,'outcome':r.get('outcome'),'t':r.get('t_end')})
 drive_to(13.654,'CRUISE','E1_to_E2'); stop('E2_observe'); snap2=env.save_state()
 act2=DEC['E2']; r2=v3_core.run_action(env,snap2,act2,{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},mode='same_scene',record_dir=out/f'E2_{act2}'); events.append({'encounter':'E2','action':act2,'outcome':r2.get('outcome'),'t':r2.get('t_end')})
 drive_to(21.0,'CRUISE','E2_to_goal',limit_t=200); stop('goal',20)
 rec.close(); res={'arm':ARM,'events':events,'final_x':float(env.data.qpos[0]),'t_end':float(env.t),'term':getattr(env,'last_termination',None)}; (out/'result.json').write_text(json.dumps(res,default=str,indent=2)); print(json.dumps(res,default=str))
if __name__=='__main__': main()
