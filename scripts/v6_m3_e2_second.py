"""M3 E1: robot-mounted front_cam capture with exact cam_xpos/cam_xmat."""
import json,pathlib,sys
import numpy as np,mujoco,trimesh
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,camera_io
def main():
 st='moon_rock_01_h1v0'; spec=json.loads((ROOT/'runs/v3/states'/st/'scene_spec.json').read_text())
 for o in spec.get('objects') or []:
  if 'mesh_file' in o: o['mesh_file']=o['mesh_file'].replace('/workspace/lunar-lab','/workspace/work/lunar-lab'); o['x']=15.0
 spec['start']=[0,0]; spec['goal_x']=20; spec['terrain']['span']=30; spec['terrain']['field_x_max']=30
 spec['channel']={'center_y':0.0,'half_width':1.2}
 spec['front_cam']={'pos':[0.40,0.0,0.35],'pitch_deg':-40.0,'fovy':70.0}
 spec['render']={'size':[1600,1200]}
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0); m=env.model; d=env.data
 BASE=np.array([[0.0,0.85,-1.65]]*4)
 def yaw():
  w,x,y,z=d.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 while d.qpos[0]<12.9 and not getattr(env,'terminated',False) and env.t<60:
  y=float(d.qpos[1]); yd=float(np.clip(-1.2*y-0.8*yaw(),-0.4,0.4)); v=3.5
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd]),wheel_mode='velocity')
 for _ in range(80): env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool))
 cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,'front_cam'); print('cam id',cid,'x',float(d.qpos[0]))
 r=mujoco.Renderer(m,1200,1600); r.update_scene(d,camera=cid); rgb=r.render().copy(); r.enable_depth_rendering(); dep=r.render().copy(); r.enable_segmentation_rendering(); seg=r.render().copy(); r.close()
 bid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,'obstacle0'); gids=[g for g in range(m.ngeom) if m.geom_bodyid[g]==bid]; mask=np.zeros(seg.shape[:2],np.uint8)
 print('bid',bid,'gids',gids,'seg uniq',np.unique(seg[:,:,0])[:6])
 for g in gids: mask[seg[:,:,0]==g]=255
 pos=np.array(d.cam_xpos[cid],float); R=np.array(d.cam_xmat[cid],float).reshape(3,3)
 out=ROOT/'runs/v6/m3/E2/observation_second'; out.mkdir(parents=True,exist_ok=True)
 Image.fromarray(rgb).save(out/'rgb.png'); Image.fromarray(mask).save(out/'mask.png'); np.save(out/'depth.npy',dep.astype(np.float32))
 pts,ys,xs=camera_io.unproject_depth(dep.astype(np.float64),{'intrinsics':{'fx':0.5*1200/np.tan(np.deg2rad(70)/2),'fy':0.5*1200/np.tan(np.deg2rad(70)/2),'cx':799.5,'cy':599.5},'R_world_from_camera':R,'world_pos':pos}); np.save(out/'visible_points.npy',pts)
 camj={'camera_schema':'camera-snapshot/v2','world_pos':pos.tolist(),'R_world_from_camera':R.tolist(),'fovy_deg':70.0,'image_width':1600,'image_height':1200,'intrinsics':{'fx':0.5*1200/np.tan(np.deg2rad(70)/2),'fy':0.5*1200/np.tan(np.deg2rad(70)/2),'cx':799.5,'cy':599.5,'width':1600,'height':1200},'depth_convention':'positive_camera_minus_z'}
 (out/'camera.json').write_text(json.dumps(camj,indent=2)); (out/'observation.json').write_text(json.dumps({'schema':'observation/v1','rock':'moon_rock_01','camera':camj,'intrinsics':camj['intrinsics'],'image':'rgb.png'},indent=2))
 # KA6: project truth mesh vertices into mask
 msh=trimesh.load(str(ROOT/'assets/v3/rocks/moon_rock_01/h1/body_vis.obj'),force='mesh',process=False); msh.apply_translation([15.0,0.0,0.0])
 u,v,z=camera_io.project(msh.vertices[::3],camj); H,W=mask.shape; ok=np.isfinite(u)&np.isfinite(v)&(z>0); ui=np.round(u[ok]).astype(int); vi=np.round(v[ok]).astype(int); g=(ui>=0)&(ui<W)&(vi>=0)&(vi<H)
 inside=mask[vi[g],ui[g]]>0; print('KA6 vertex-in-mask frac',round(float(inside.mean()),3),'mask px',int((mask>0).sum()))
if __name__=='__main__': main()
