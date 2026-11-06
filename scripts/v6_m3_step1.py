"""M3 E1 step 1: drive to observation point in the route scene and capture RGB-D+mask."""
import json,pathlib,sys
import numpy as np,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,terrain,v3_record
from PIL import Image
def look_camera(pos,target):
 d=np.asarray(target,float)-np.asarray(pos,float); d/=np.linalg.norm(d)
 z=-d; x=np.cross([0,0,1],z); x/=np.linalg.norm(x); y=np.cross(z,x); return np.stack([x,y,z],1)
def main():
 st='moon_rock_02_h1v0'; spec=json.loads((ROOT/'runs/v3/states'/st/'scene_spec.json').read_text())
 for o in spec.get('objects') or []:
  if 'mesh_file' in o: o['mesh_file']=o['mesh_file'].replace('/workspace/lunar-lab','/workspace/work/lunar-lab')
 spec['start']=[0.0,0.0]; spec['goal_x']=20.0; spec['channel']={'center_y':0.0,'half_width':1.2}
 spec.setdefault('terrain',{})['span']=30.0; spec['terrain']['field_x_max']=30.0
 for o in spec.get('objects') or []:
  if 'x' in o: o['x']=9.0
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0)
 target=8.2; BASE=np.array([[0.0,0.85,-1.65]]*4)
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 while env.data.qpos[0]<target and not getattr(env,'terminated',False) and env.t<60:
  y=float(env.data.qpos[1]); yaw_e=yaw(); yd=float(np.clip(-1.2*y-0.8*yaw_e,-0.4,0.4)); v=3.5
  om=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd])
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=om,wheel_mode='velocity')
 for _ in range(80): env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool))
 print('stopped x',float(env.data.qpos[0]),'y',float(env.data.qpos[1]),'t',float(env.t))
 out=ROOT/'runs/v6/m3/E1/observation'; out.mkdir(parents=True,exist_ok=True)
 m=env.model; d=env.data
 m.vis.global_.offwidth=1600; m.vis.global_.offheight=1200
 target_p=np.array([9.0,0.10,0.15]); dist=0.95; az=np.deg2rad(180.0); el=np.deg2rad(15.0)
 pos=target_p+dist*np.array([np.cos(el)*np.cos(az),np.cos(el)*np.sin(az),np.sin(el)])
 R=look_camera(pos,target_p); quat=np.zeros(4); from scipy.spatial.transform import Rotation; q=Rotation.from_matrix(R).as_quat(); quat=[q[3],q[0],q[1],q[2]]
 cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,'obs') if mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,'obs')>=0 else -1
 if cid<0:
  cam=mujoco.MjvCamera(); cam.lookat[:]=target_p; cam.distance=dist; cam.azimuth=180; cam.elevation=15
  scn=mujoco.MjvScene(m,maxgeom=2000); opt=mujoco.MjvOption(); pert=mujoco.MjvPerturb()
  mujoco.mjv_updateScene(m,d,opt,pert,cam,mujoco.mjtCatBit.mjCAT_ALL,scn); mujoco.mjv_updateCamera(m,d,cam,scn)
  gl=scn.camera[0]; pos=np.array(gl.pos,float); fwd=np.array(gl.forward,float); up=np.array(gl.up,float); right=np.cross(up,fwd); right=right/np.linalg.norm(right)
  R=np.stack([right,up,-fwd],axis=1)
  r=mujoco.Renderer(m,1200,1600); r.update_scene(d,camera=cam)
  rgb=r.render().copy(); r.enable_depth_rendering(); dep=r.render().copy(); r.enable_segmentation_rendering(); seg=r.render().copy(); r.close()
  mask=np.zeros((1200,1600),np.uint8)
  for bid in range(m.nbody):
   nm=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,bid) or ''
   if ('rock' in nm.lower()) or ('obstacle' in nm.lower()): mask[(seg[:,:,0]==bid)]=255
 else:
  m.cam_pos[cid]=pos; m.cam_quat[cid]=quat; mujoco.mj_forward(m,d)
  r=mujoco.Renderer(m,1200,1600); r.update_scene(d,camera=cid); rgb=r.render().copy(); r.enable_depth_rendering(); dep=r.render().copy(); r.enable_segmentation_rendering(); seg=r.render().copy(); r.close()
  mask=np.zeros((1200,1600),np.uint8)
  for bid in range(m.nbody):
   nm=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,bid) or ''
   if ('rock' in nm.lower()) or ('obstacle' in nm.lower()): mask[(seg[:,:,0]==bid)]=255
  if mask.sum()==0:
   gid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,'rockg'); mask[seg[:,:,0]==gid]=255
 Image.fromarray(rgb).save(out/'rgb.png'); Image.fromarray(mask).save(out/'mask.png'); np.save(out/'depth.npy',dep.astype(np.float32))
 camj={'camera_schema':'camera-snapshot/v2','world_pos':pos.tolist(),'R_world_from_camera':R.tolist(),'fovy_deg':45.0,'image_width':1600,'image_height':1200,'intrinsics':{'fx':0.5*1200/np.tan(np.deg2rad(45)/2),'fy':0.5*1200/np.tan(np.deg2rad(45)/2),'cx':799.5,'cy':599.5,'width':1600,'height':1200},'depth_convention':'positive_camera_minus_z'}
 (out/'camera.json').write_text(json.dumps(camj,indent=2)); print('mask px',int((mask>0).sum()))
if __name__=='__main__': main()
