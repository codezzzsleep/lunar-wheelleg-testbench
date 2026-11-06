"""R1 M3 route scene builder + phase drivers (E0 gravel, E1, slope, E2, pit, goal 21)."""
import json,os,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import terrain,wheelleg_env,v7_soil,v3_record
OUT=ROOT/'runs/v6/m3/route2'
def make_route_spec():
 OUT.mkdir(parents=True,exist_ok=True)
 # gravel boxes filtered from A2
 src=ROOT/'runs/v4/wp7_new/A2_gravel/coll'; man=json.loads((src/'manifest.json').read_text())
 boxes=man.get('boxes') or []
 # box format [i,j,k,sx,sy,sz] on grid; keep those with world x in 3..5.5
 o=np.asarray(man.get('grid_origin',[0,0,0]),float); pit=float(man.get('pitch_m',0.08))
 keep=[b for b in boxes if 3.0<=o[0]+(b[0]+b[3]/2)*pit<=5.5]
 gm=dict(man); gm['boxes']=keep
 gdir=OUT/'scene'/'gravel'; gdir.mkdir(parents=True,exist_ok=True); (gdir/'manifest.json').write_text(json.dumps(gm,indent=2))
 # rock meshes
 e1=ROOT/'assets/v3/rocks/moon_rock_02/h1/body_vis.obj'; e2=ROOT/'assets/v3/rocks/moon_rock_01/h1/body_vis.obj'
 terrain.SPAN=32.0
 spec=terrain.make_spec(kind='flat',seed=0,goal_x=21.0,span=32.0,name='v6_m3_route2'); spec['terrain']['field_x_max']=32.0
 # custom height: 8 deg ramp 10.5-12.5 and pit at (18,-1.4)
 n=terrain.N; xs=(np.arange(n)+0.5)/n*2*terrain.SPAN-terrain.SPAN; ys=xs.copy(); X,Y=np.meshgrid(xs,ys,indexing='ij'); H=np.zeros((n,n))
 for i,x in enumerate(xs):
  if 10.5<=x<=11.5: H[:,i]+=0.28*(x-10.5)
  elif 11.5<x<=12.5: H[:,i]+=0.28*(12.5-x)
 H-=0.35*np.exp(-((X-18.0)**2/0.35**2)-((Y+1.4)**2/0.35**2))
 hf=OUT/'scene'/'route2_height.npy'; OUT.joinpath('scene').mkdir(parents=True,exist_ok=True); np.save(hf,H); spec['terrain']['custom_height_file']=str(hf)
 spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=v7_soil.resolve('nominal')
 spec['objects']=[{'posed_dir':str(gdir)},{'mesh_file':str(e1),'x':8.5,'y':0.0,'target_height_m':0.172},{'mesh_file':str(e2),'x':15.0,'y':0.0,'target_height_m':0.120}]
 spec['front_cam']={'pos':[0.40,0,0.35],'pitch_deg':-20.0,'fovy':70.0}; spec['render']={'size':[1600,1200]}
 spec['_route']={'gravel':[3.0,5.5],'e1':8.5,'slope':[10.5,12.5],'e2':15.0,'pit':[17.0,19.0],'goal':21.0}
 return spec
def install_custom_terrain():
 orig=terrain.build_heightfield
 def custom(spec):
  h,meta=orig(spec); print('orig h',getattr(h,'shape',None)); n=h.shape[0]; span=float(spec.get('terrain',{}).get('span') or terrain.SPAN)
  xs=(np.arange(n)+0.5)/n*span*2-span
  # 8 deg ramp between 10.5 and 12.5 (up then down), max height ~0.28
  rise=0.28
  for i,x in enumerate(xs):
   if 10.5<=x<=11.5: h[:,i]+=rise*(x-10.5)
   elif 11.5<x<=12.5: h[:,i]+=rise*(12.5-x)
  # pit at x 18, y -1.4
  ys=(np.arange(n)+0.5)/n*span*2-span
  X,Y=np.meshgrid(xs,ys,indexing='ij')
  h-=0.35*np.exp(-((X-18.0)**2/0.35**2)-((Y+1.4)**2/0.35**2))
  meta=dict(meta); meta['route2']=True
  return h,meta
 terrain.build_heightfield=custom
def run_phase(phase):
 spec=make_route_spec(); OUT.joinpath('scene').mkdir(parents=True,exist_ok=True); (OUT/'scene'/'scene.json').write_text(json.dumps(spec,indent=2))
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=200); env.reset(seed=0); BASE=np.array([[0,0.85,-1.65]]*4)
 rec=v3_record.Recorder(OUT/'phase1_record',{'scene':'route2','phase':phase},hz=50.0); k=[0]
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 def step(phase_name):
  y=float(env.data.qpos[1]); yd=float(np.clip(-1.2*y-0.8*yaw(),-0.4,0.4)); v=3.5
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd]),wheel_mode='velocity')
  rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k[0],env.t,extra={'phase':phase_name})); k[0]+=1
 while env.data.qpos[0]<6.8 and not getattr(env,'terminated',False) and env.t<120: step('CRUISE')
 for _ in range(50):
  if getattr(env,'terminated',False): break
  env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool)); rec.add(v3_record.frame_from_env(env,None,np.zeros(3),k[0],env.t,extra={'phase':'OBSERVE'})); k[0]+=1
 rec.close(); (OUT/'phase1_state.json').write_text(json.dumps({'x':float(env.data.qpos[0]),'y':float(env.data.qpos[1]),'t':float(env.t)}))
 # render observation
 import mujoco; m=env.model; d=env.data; cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,'front_cam')
 r=mujoco.Renderer(m,1200,1600); r.update_scene(d,camera=cid); rgb=r.render().copy(); r.enable_depth_rendering(); dep=r.render().copy(); r.enable_segmentation_rendering(); seg=r.render().copy(); r.close()
 from PIL import Image
 od=OUT/'phase1_obs'; od.mkdir(parents=True,exist_ok=True); Image.fromarray(rgb).save(od/'rgb.png'); np.save(od/'depth.npy',dep.astype(np.float32)); mask=np.zeros(seg.shape[:2],np.uint8)
 for bid in range(m.nbody):
  nm=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,bid) or ''
  if nm.startswith('obstacle') and float(d.xpos[bid][0])>6.5:
   for g in range(m.ngeom):
    if m.geom_bodyid[g]==bid: mask[seg[:,:,0]==g]=255
 Image.fromarray(mask).save(od/'mask.png')
 print(json.dumps({'phase':phase,'x':float(env.data.qpos[0]),'t':float(env.t),'mask_px':int((seg[:,:,0]>0).sum()),'terrain_meta':env._terrain_meta if hasattr(env,'_terrain_meta') else None},default=str))


def phase_e1_capture():
 spec=make_route_spec(); env=wheelleg_env.WheelLegEnv(spec,max_seconds=200); env.reset(seed=0); BASE=np.array([[0,0.85,-1.65]]*4)
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 while env.data.qpos[0]<6.8 and not getattr(env,'terminated',False) and env.t<120:
  y=float(env.data.qpos[1]); yd=float(np.clip(-1.2*y-0.8*yaw(),-0.4,0.4)); v=3.5
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd]),wheel_mode='velocity')
 for _ in range(50):
  if getattr(env,'terminated',False): break
  env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool))
 import mujoco
 m=env.model; d=env.data; cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,'front_cam')
 r=mujoco.Renderer(m,1200,1600); r.update_scene(d,camera=cid); rgb=r.render().copy(); r.enable_depth_rendering(); dep=r.render().copy(); r.enable_segmentation_rendering(); seg=r.render().copy(); r.close()
 from PIL import Image
 od=OUT/'E1'/'observation'; od.mkdir(parents=True,exist_ok=True)
 Image.fromarray(rgb).save(od/'rgb.png'); np.save(od/'depth.npy',dep.astype(np.float32)); mask=np.zeros(seg.shape[:2],np.uint8)
 for bid in range(m.nbody):
  nm=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,bid) or ''
  if nm.startswith('obstacle') and float(d.xpos[bid][0])>6.5:
   for g in range(m.ngeom):
    if m.geom_bodyid[g]==bid: mask[seg[:,:,0]==g]=255
 Image.fromarray(mask).save(od/'mask.png')
 camj={'camera_schema':'camera-snapshot/v2','world_pos':np.array(d.cam_xpos[cid],float).tolist(),'R_world_from_camera':np.array(d.cam_xmat[cid],float).reshape(3,3).tolist(),'fovy_deg':70.0,'image_width':1600,'image_height':1200,'intrinsics':{'fx':0.5*1200/np.tan(np.deg2rad(70)/2),'fy':0.5*1200/np.tan(np.deg2rad(70)/2),'cx':799.5,'cy':599.5,'width':1600,'height':1200},'depth_convention':'positive_camera_minus_z'}
 (od/'camera.json').write_text(json.dumps(camj,indent=2)); (od/'observation.json').write_text(json.dumps({'schema':'observation/v1','rock':'moon_rock_02','camera':camj,'intrinsics':camj['intrinsics'],'image':'rgb.png'},indent=2))
 np.savez(OUT/'E1'/'state.npz',qpos=np.asarray(d.qpos,float),qvel=np.asarray(d.qvel,float),t=float(env.t))
 print(json.dumps({'phase':'e1_capture','x':float(d.qpos[0]),'t':float(env.t),'mask':int((mask>0).sum())}))

if __name__=='__main__':
 cmd=sys.argv[1] if len(sys.argv)>1 else 'phase1'
 if cmd=='e1_capture': phase_e1_capture()
 else: run_phase(cmd)
