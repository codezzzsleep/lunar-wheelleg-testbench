"""WP7 A4: same 5 m, wheel-only vs body-raised traversal; record both."""
import json,pathlib,sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import terrain,wheelleg_env,skills,runner,v3_record,stage6_body as SBdy
def run(action,out):
 spec=json.loads((out.parent.parent/'A4_scene.json').read_text())
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=60); env.reset(seed=0); snap=env.save_state(); rec=v3_record.Recorder(out/'record',{'scene':'A4_wheel_vs_body','arm':action},hz=50.0)
 if action=='R1':
  ep=runner.EpisodeRunner(env,skills.make_skill('R1'),visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=3000,seed=0,record_trajectory=True); ep.recorder=rec
  res=ep.run_from_state(snap,mode='same_scene')
 else:
  LEG=('FR','FL','RR','RL'); tg={l:dict(hip=0.0,thigh=0.85,calf=-1.65) for l in LEG}
  for _ in range(120): tg=SBdy.leg_tick_targets(env,tg,0.08/120); env.step_command(joint_targets_rad=tg,wheel_mode='coast')
  k=0
  while not getattr(env,'terminated',False) and env.data.qpos[0]<5.6 and env.t<60:
   env.step_command(joint_targets_rad=tg,wheel_omega_rad_s=np.full(4,4.65),wheel_mode='velocity')
   rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k,env.t,extra={'phase':'body_drive'})); k+=1
  for _ in range(150):
   if getattr(env,'terminated',False): break
   env.step_command(joint_targets_rad=tg,wheel_brake=np.ones(4,bool))
   rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k,env.t,extra={'phase':'settle'})); k+=1
  res={'success':env.last_termination.get('reason')=='success','reason':env.last_termination.get('reason'),'t_end':float(env.t),'final_x':float(env.data.qpos[0])}
 rec.close()
 (out/'result.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)); return res
def main():
 out=ROOT/'runs/v4/wp7/A4_wheel_vs_body'; out.mkdir(parents=True,exist_ok=True)
 spec=terrain.make_spec(kind='flat',seed=0,goal_x=5.0,name='wp7_A4',span=8.0)
 spec['terrain']['field_x_max']=7.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=__import__('v7_soil').resolve('nominal')
 (out.parent/'A4_scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
 r1=run('R1',out/'R1'); body=run('BODY',out/'BODY')
 files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp7-scene/v1','scene':'A4_wheel_vs_body','R1':r1,'BODY':body,'files':files},ensure_ascii=False,indent=2))
 print(json.dumps({'R1':{k:r1.get(k) for k in ('success','t_end','final_x')},'BODY':{k:body.get(k) for k in ('success','t_end','final_x')}}))
if __name__=='__main__': main()
