import json,pathlib,sys,copy,numpy as np,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,v3_basic_cycle as BC,stage6_body as SB
T=ROOT/'runs/v3/stage008/truth_v2'; spec=json.loads((T/'scene_spec.json').read_text()); snap=json.loads((T/'state_snapshot.json').read_text())
soft=copy.deepcopy(spec); soft['soil']={'mode':'soil','label':'soft','params':json.loads((ROOT/'configs/v4_soil_soft.json').read_text())['params']}
orig=wheelleg_env.WheelLegEnv(spec,max_seconds=5); orig.reset(seed=0); orig.restore_state(snap,mode='same_scene'); ref=(np.asarray(orig.data.qpos,float).copy(),np.asarray(orig.data.qvel,float).copy())
def env0():
 e=wheelleg_env.WheelLegEnv(soft,max_seconds=120); e.reset(seed=0); e.restore_state(snap,mode='project'); e.data.qpos[:]=ref[0]; e.data.qvel[:]=ref[1]; mujoco.mj_forward(e.model,e.data); return e
def run(e,targets,sec,w):
 for _ in range(int(sec*e.control_hz)):
  if e.terminated: break
  e.step_command(joint_targets_rad=targets,wheel_omega_rad_s=np.full(4,w),wheel_mode='velocity')
for name,dz,rev in (('raise_slow',0.10,0),('reverse_first',0.0,-1),('raise_reverse',0.10,-1)):
 e=env0(); tg={l:dict(BC.STANCE) for l in BC.LEG}
 if dz:
  for _ in range(150): tg=SB.leg_tick_targets(e,tg,dz/150); e.step_command(joint_targets_rad=tg,wheel_mode='coast')
 x0=float(e.data.qpos[0])
 if rev:
  run(e,tg,8.0,-0.12)
  run(e,tg,30.0,0.03)
 else:
  run(e,tg,30.0,0.03)
 print(name,'x0',round(x0,3),'x',round(float(e.data.qpos[0]),3),'dx',round(float(e.data.qpos[0])-x0,3),'t',round(float(e.t),1),'term',e.terminated,e.last_termination.get('reason'),'z',round(float(e.data.qpos[2]),3),flush=True)
