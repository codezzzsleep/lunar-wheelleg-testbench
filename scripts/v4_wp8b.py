"""WP8 route v1: custom 30 m occupancy, three boulders, continuous drive."""
import json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import terrain,v3_core,wheelleg_env,v3_record,stage6_body as SBdy
T=ROOT/'runs/v3/stage008/truth_v2'
def main():
 out=ROOT/'runs/v4/wp8/route_v1'; out.mkdir(parents=True,exist_ok=True)
 origin=np.array([-2.0,-1.5,0.0]); pitch=0.05; dims=(560,60,40)
 xs=origin[0]+(np.arange(dims[0])+0.5)*pitch; ys=origin[1]+(np.arange(dims[1])+0.5)*pitch; zs=origin[2]+(np.arange(dims[2])+0.5)*pitch
 mesh=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False)
 Q=np.zeros(dims,bool)
 for x in (5.0,10.0,15.0):
  m=mesh.copy(); m.apply_translation([x-1.0,0,0])
  # simple column fill via ray casting on the coarse grid
  import trimesh.ray.ray_triangle as RT
  inter=RT.RayMeshIntersector(m)
  X,Y=np.meshgrid(xs,ys,indexing='ij'); pts=np.stack([X.ravel(),Y.ravel(),np.full(X.size,-0.05)],1); d=np.tile([0,0,1.0],(len(pts),1))
  loc,ridx,_=inter.intersects_location(pts,d,multiple_hits=True)
  order=np.argsort(ridx); loc,ridx=loc[order],ridx[order]
  uniq=np.unique(ridx); bounds=np.searchsorted(ridx,np.arange(len(pts)+1)); breaks=np.searchsorted(ridx,uniq)
  for k,r in enumerate(uniq):
   s=breaks[k]; e=breaks[k+1] if k+1<len(breaks) else len(ridx); zz=np.sort(loc[s:e,2])
   col=r; iy=col%len(ys); ix=col//len(ys)
   if len(zz)>=2:
    for a,b in zip(zz[0::2],zz[1::2]):
     Q[ix,iy,(zs>=a)&(zs<=b)]=True
 td=out/'coll'; td.mkdir(exist_ok=True)
 import hashlib
 np.savez(out/'occ.npz',occupied=Q,origin=origin,pitch=pitch,dims=dims,
          content_sha=np.array(hashlib.sha256(np.ascontiguousarray(Q).tobytes()).hexdigest()[:32]),
          convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
 r=v3_core.build_collision(out/'occ.npz',td,pitch=pitch,downsample=1)
 print('coll',r.get('ok'))
 spec=terrain.make_spec(kind='flat',seed=0,goal_x=20.0,objects=[{'posed_dir':str(td)}],name='wp8_route_v1',span=30.0)
 spec['terrain']['field_x_max']=30.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=__import__('v7_soil').resolve('nominal')
 (out/'scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0); rec=v3_record.Recorder(out/'record',{'scene':'wp8_route_v1'},hz=50.0)
 LEG=('FR','FL','RR','RL'); BASE={l:{'hip':0.0,'thigh':0.85,'calf':-1.65} for l in LEG}; k=[0]
 def step(tg,w,phase):
  env.step_command(joint_targets_rad=tg,wheel_omega_rad_s=np.full(4,w),wheel_mode='velocity')
  rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k[0],env.t,extra={'phase':phase})); k[0]+=1
 def drive(sec,tg,w,phase):
  for _ in range(int(sec*env.control_hz)):
   if getattr(env,'terminated',False): break
   step(tg,w,phase)
 TG={l:dict(BASE[l]) for l in LEG}
 env.nav_target_y=0.0; drive(12.0,TG,2.0,'R1_0_4m')
 env.nav_target_y=0.45; drive(8.0,TG,2.0,'D2_rock5')
 env.nav_target_y=0.0; drive(12.0,TG,2.0,'R1_6_9m')
 env.nav_target_y=-0.45; drive(8.0,TG,2.0,'D1_rock10')
 env.nav_target_y=0.0; drive(10.0,TG,2.0,'R1_12_14m')
 for _ in range(120): TG=SBdy.leg_tick_targets(env,TG,0.08/120); step(TG,0.0,'body_raise')
 drive(15.0,TG,2.0,'BODY_rock15')
 drive(15.0,TG,2.0,'R1_goal')
 rec.close()
 files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp8/v1','scene':'route_v1','files':files},ensure_ascii=False,indent=2))
 print(json.dumps({'x':round(float(env.data.qpos[0]),2),'t':round(float(env.t),1),'reason':env.last_termination.get('reason'),'frames':k[0]}))
if __name__=='__main__': main()
