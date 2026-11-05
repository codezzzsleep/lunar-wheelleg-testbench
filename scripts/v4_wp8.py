"""WP8 route skeleton v0: 20 m, three rock encounters, continuous execution."""
import json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import stage8_matrix2 as M,v3_fuse,wheelleg_env,skills,v3_record,stage6_body_skill as SB
import stage6_body as SBdy
T=ROOT/'runs/v3/stage008/truth_v2'
def main():
 out=ROOT/'runs/v4/wp8/route_v0'; out.mkdir(parents=True,exist_ok=True)
 z=np.load(T/'fusion/V.npz'); o=np.asarray(z['origin'],float); pitch=float(z['pitch']); dims=tuple(int(x) for x in z['dims'])
 g={'origin':o,'pitch':pitch,'dims':np.array(dims)}
 g['xs']=o[0]+(np.arange(dims[0])+0.5)*pitch; g['ys']=o[1]+(np.arange(dims[1])+0.5)*pitch; g['zs']=o[2]+(np.arange(dims[2])+0.5)*pitch
 mesh=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False); P,_=v3_fuse.voxelize_columns(mesh,g)
 Q=np.zeros_like(P)
 for x in (5.0,10.0,15.0):
  sx=int(round((x-1.0)/pitch)); C=np.zeros_like(P0) if False else np.zeros_like(P)
  if sx>=0: C[sx:sx+P.shape[0]]=P[:P.shape[0]-sx]
  Q|=C
 td=out/'coll'; td.mkdir(exist_ok=True)
 spec,env,sha=M.make_scene(M.resample_walls(Q,o,pitch),td,'wp8_route')
 spec['terrain']['field_x_max']=30.0; spec['goal_x']=20.0; spec['channel']={'center_y':0.0,'half_width':1.2}
 spec['soil']=__import__('v7_soil').resolve('nominal')
 (out/'scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
 snap=env.save_state(); rec=v3_record.Recorder(out/'record',{'scene':'wp8_route_v0'},hz=50.0)
 LEG=('FR','FL','RR','RL'); BASE={l:{'hip':0.0,'thigh':0.85,'calf':-1.65} for l in LEG}
 k=0
 def step(targets,w=0.0,phase=''):
  nonlocal k
  env.step_command(joint_targets_rad=targets,wheel_omega_rad_s=np.full(4,w),wheel_mode='velocity')
  rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k,env.t,extra={'phase':phase})); k+=1
 def drive(seconds,w=0.15,phase='R1'):
  n=int(seconds*env.control_hz)
  for _ in range(n):
   if getattr(env,"terminated",False): break
   step(BASE,w,phase)
 # segments: R1 -> D2 around 5 m -> R1 -> D1 around 10 m -> R1 -> BODY over 15 m -> R1 to 20 m
 drive(22.0,0.15,'R1_to_4m')
 # D2: lateral target +0.45
 tg={l:dict(BASE[l]) for l in LEG}
 env.nav_target_y=0.45
 for _ in range(int(12.0*env.control_hz)):
  if getattr(env,"terminated",False): break
  step(tg,0.15,'D2')
 env.nav_target_y=0.0; drive(20.0,0.15,'R1_to_9m')
 env.nav_target_y=-0.45
 for _ in range(int(12.0*env.control_hz)):
  if getattr(env,"terminated",False): break
  step(tg,0.15,'D1')
 env.nav_target_y=0.0
 # BODY raise + drive over 15 m
 for _ in range(150):
  tg=SBdy.leg_tick_targets(env,tg,0.08/150); step(tg,0.0,'body_raise')
 drive(25.0,0.15,'BODY_drive')
 rec.close()
 files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp8/v0','scene':'route_v0','encounters':[5.0,10.0,15.0],'files':files},ensure_ascii=False,indent=2))
 print(json.dumps({'x':round(float(env.data.qpos[0]),2),'t':round(float(env.t),1),'term':env.last_termination.get('reason'),'frames':k}))
if __name__=='__main__': main()
