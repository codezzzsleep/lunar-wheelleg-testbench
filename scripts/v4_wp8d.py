"""WP8 route v3: four boulder encounters + narrow gate, 20 m continuous."""
import json,pathlib,sys,hashlib
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import terrain,v3_core,v3_fuse,wheelleg_env,v3_record
T=ROOT/'runs/v3/stage008/truth_v2'
def main():
 out=ROOT/'runs/v4/wp8/route_v3'; out.mkdir(parents=True,exist_ok=True)
 zf=np.load(T/'fusion/V.npz'); of=np.asarray(zf['origin'],float); pf=float(zf['pitch']); df=tuple(int(x) for x in zf['dims'])
 gf={'origin':of,'pitch':pf,'dims':np.array(df)}
 gf['xs']=of[0]+(np.arange(df[0])+0.5)*pf; gf['ys']=of[1]+(np.arange(df[1])+0.5)*pf; gf['zs']=of[2]+(np.arange(df[2])+0.5)*pf
 mesh=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False); P,_=v3_fuse.voxelize_columns(mesh,gf)
 ix,iy,iz=np.nonzero(P); wx=of[0]+(ix+0.5)*pf; wy=of[1]+(iy+0.5)*pf; wz=of[2]+(iz+0.5)*pf
 ORIG=np.array([-2.0,-1.5,0.0]); PIT=0.05; DIMS=(560,60,40); Q=np.zeros(DIMS,bool)
 for x0 in (4.0,8.0,12.0,16.0):
  cx=np.floor((wx+(x0-1.0)-ORIG[0])/PIT).astype(int); cy=np.floor((wy-ORIG[1])/PIT).astype(int); cz=np.floor((wz-ORIG[2])/PIT).astype(int)
  ok=(cx>=0)&(cx<DIMS[0])&(cy>=0)&(cy<DIMS[1])&(cz>=0)&(cz<DIMS[2]); Q[cx[ok],cy[ok],cz[ok]]=True
 zc=ORIG[2]+(np.arange(DIMS[2])+0.5)*PIT; Q[:,:,zc>0.12]=False
 # narrow gate at x=18: walls with 0.7 m gap, height 0.25
 gx=(np.arange(DIMS[0])+0.5)*PIT+ORIG[0]; gy=(np.arange(DIMS[1])+0.5)*PIT+ORIG[1]
 gxm=(gx>=18.0)&(gx<=18.4); gym=(np.abs(gy)>=0.35)&(np.abs(gy)<=1.05); gzm=zc<=0.25
 Q[np.ix_(gxm,gym,gzm)]=True
 print('occ',int(Q.sum()))
 td=out/'coll'; td.mkdir(exist_ok=True)
 np.savez(out/'occ.npz',occupied=Q,origin=ORIG,pitch=PIT,dims=DIMS,
          content_sha=np.array(hashlib.sha256(np.ascontiguousarray(Q).tobytes()).hexdigest()[:32]),
          convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
 r=v3_core.build_collision(out/'occ.npz',td,pitch=PIT,downsample=1); print('coll',r.get('ok'),r.get('n_boxes'))
 spec=terrain.make_spec(kind='flat',seed=0,goal_x=20.0,objects=[{'posed_dir':str(td)}],name='wp8_route_v3',span=30.0)
 spec['terrain']['field_x_max']=30.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=__import__('v7_soil').resolve('nominal')
 (out/'scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0); rec=v3_record.Recorder(out/'record',{'scene':'wp8_route_v3'},hz=50.0)
 BASE={l:{'hip':0.0,'thigh':0.85,'calf':-1.65} for l in ('FR','FL','RR','RL')}; k=[0]
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 def step(phase,v=3.5):
  x=float(env.data.qpos[0]); y=float(env.data.qpos[1]); ye=yaw(); yt=0.0
  if 2.8<=x<=5.2: yt=0.55
  elif 6.8<=x<=9.2: yt=-0.55
  elif 10.8<=x<=13.2: yt=0.55
  elif 14.8<=x<=17.2: yt=-0.55
  elif 17.2<=x<=19.2: yt=0.0
  yd=float(np.clip(-0.9*(y-yt)-0.6*ye,-0.40,0.40))
  om=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd])
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=om,wheel_mode='velocity')
  rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k[0],env.t,extra={'phase':phase})); k[0]+=1
 for _ in range(int(130*env.control_hz)):
  if getattr(env,'terminated',False): break
  step('route')
 rec.close()
 files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp8/v3','scene':'route_v3','files':files},ensure_ascii=False,indent=2))
 print(json.dumps({'x':round(float(env.data.qpos[0]),2),'y':round(float(env.data.qpos[1]),2),'t':round(float(env.t),1),'reason':env.last_termination.get('reason'),'frames':k[0]}))
if __name__=='__main__': main()
