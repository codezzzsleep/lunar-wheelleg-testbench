"""WP5 SOFT_ESCAPE: wheel-step cycles on soft soil."""
import copy,json,pathlib,sys,time
import numpy as np,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,v3_basic_cycle as BC,v3_record
T=ROOT/'runs/v3/stage008/truth_v2'; spec=json.loads((T/'scene_spec.json').read_text()); snap=json.loads((T/'state_snapshot.json').read_text())
soft=copy.deepcopy(spec); soft['soil']={'mode':'soil','label':'v4_soft','params':json.loads((ROOT/'configs/v4_soil_soft.json').read_text())['params']}
orig=wheelleg_env.WheelLegEnv(spec,max_seconds=5); orig.reset(seed=0); orig.restore_state(snap,mode='same_scene'); ref=(np.asarray(orig.data.qpos,float).copy(),np.asarray(orig.data.qvel,float).copy())
def make_env():
 env=wheelleg_env.WheelLegEnv(soft,max_seconds=120); env.reset(seed=0); env.restore_state(snap,mode='project'); env.data.qpos[:]=ref[0]; env.data.qvel[:]=ref[1]; mujoco.mj_forward(env.model,env.data); return env
def drive(env,seconds,w=0.12):
 n=int(seconds*env.control_hz); tg={l:dict(BC.STANCE) for l in BC.LEG}
 for _ in range(n):
  if env.terminated: break
  env.step_command(joint_targets_rad=tg,wheel_omega_rad_s=np.full(4,w),wheel_mode='velocity')
def main():
 env=make_env(); rec=v3_record.Recorder(ROOT/'runs/v4/wp5/escape/record',{'action':'SOFT_ESCAPE'},hz=50.0)
 drive(env,2.0,0.15); x0=float(env.data.qpos[0])
 for rnd in range(10):
  for leg in BC.LEG:
   if env.terminated: break
   cyc=BC.Cycle(env,swing=leg,record=rec)
   try:
    cyc.shift_support('shift_support',1.2); cyc.lift_swing('lift',1.0); cyc.hold('hold',0.4); cyc.lower_until_contact('lower',1.2)
   except Exception as e:
    print('cycle err',leg,e); break
   # drive with current targets
   for _ in range(int(1.0*env.control_hz)):
    if env.terminated: break
    env.step_command(joint_targets_rad=cyc.targets,wheel_omega_rad_s=np.full(4,0.15),wheel_mode='velocity')
  if env.terminated: break
 rec.close()
 print(json.dumps({'x0':round(x0,3),'x':round(float(env.data.qpos[0]),3),'advanced':round(float(env.data.qpos[0])-x0,3),'t':round(float(env.t),1),'terminated':env.terminated,'reason':env.last_termination.get('reason'),'tilt':round(float(env._tilt()),1)}))
if __name__=='__main__': main()
