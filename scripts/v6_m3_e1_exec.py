"""M3 E1: FULL fusion from the admitted candidate, 3/3 rehearsal, decision and route execution."""
import json,pathlib,sys,math
import numpy as np,trimesh,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import os
import wheelleg_env,terrain,v3_core,stage6_matrix as S6M,v5_core as C,v5_metrics_ref as R,v5_eval as E,v7_soil
from PIL import Image
ident='907ec204fdc9a1442d05b5c26c8c1d6fc22f4f25af9838031d65ba638c5e2398'
ARM=os.environ.get('M3_ARM','full')
def route_spec(rock=True,coll=None):
 spec=json.loads((ROOT/'runs/v3/states/moon_rock_02_h1v0/scene_spec.json').read_text())
 if coll: spec['objects']=[{'posed_dir':str(coll)}]
 else:
  for o in spec.get('objects') or []:
   o['mesh_file']=o['mesh_file'].replace('/workspace/lunar-lab','/workspace/work/lunar-lab'); o['x']=9.0
 spec['start']=[0,0]; spec['goal_x']=20; spec['terrain']['span']=30; spec['terrain']['field_x_max']=30
 spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=v7_soil.resolve('nominal'); spec['front_cam']={'pos':[0.40,0.0,0.35],'pitch_deg':-40.0,'fovy':70.0}; spec['render']={'size':[1600,1200]}
 return spec
def drive(env,limit,BASE):
 def yaw():
  w,x,y,z=env.data.qpos[3:7]; return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
 while env.data.qpos[0]<limit and not getattr(env,'terminated',False) and env.t<60:
  y=float(env.data.qpos[1]); yd=float(np.clip(-1.2*y-0.8*yaw(),-0.4,0.4)); v=3.5
  env.step_command(joint_targets_rad=BASE,wheel_omega_rad_s=np.array([v+1.2*yd,v-1.2*yd,v+1.2*yd,v-1.2*yd]),wheel_mode='velocity')
 for _ in range(5):
  if getattr(env,'terminated',False): break
  env.step_command(joint_targets_rad=BASE,wheel_brake=np.ones(4,bool))
def main():
 truth=route_spec(); env=wheelleg_env.WheelLegEnv(truth,max_seconds=120); env.reset(seed=0); BASE=np.array([[0.0,0.85,-1.65]]*4); drive(env,7.8,BASE)
 snap=env.save_state(); ref=(np.asarray(env.data.qpos,float).copy(),np.asarray(env.data.qvel,float).copy()); print('start x',float(env.data.qpos[0]))
 g={'origin':np.array([8.6,-0.5,-0.05]),'pitch':0.004}; dims=(180,250,100); g['dims']=np.array(dims); g['xs']=g['origin'][0]+(np.arange(dims[0])+0.5)*0.004; g['ys']=g['origin'][1]+(np.arange(dims[1])+0.5)*0.004; g['zs']=g['origin'][2]+(np.arange(dims[2])+0.5)*0.004
 m=trimesh.load(str(ROOT/'assets/v3/rocks/moon_rock_02/h1/body_vis.obj'),force='mesh',process=False); m.apply_translation([9.00943486,0.10507088,0.0713347]); T=R.column_fill_top(m,g)
 import camera_io,json as _json
 from PIL import Image
 od=ROOT/'runs/v6/m3/E1/observation2'; ob=_json.loads((od/'observation.json').read_text()); depth=np.load(od/'depth.npy'); mask=np.asarray(Image.open(od/'mask.png').convert('L'))>127
 pts=np.stack(np.meshgrid(g['xs'],g['ys'],g['zs'],indexing='ij'),-1).reshape(-1,3); u,v,z=camera_io.project(pts,ob['camera']); H,W=depth.shape
 ok=np.isfinite(u)&np.isfinite(v)&(z>0); ui=np.clip(np.round(u).astype(int),0,W-1); vi=np.clip(np.round(v).astype(int),0,H-1); inm=ok&(u>=0)&(u<W)&(v>=0)&(v<H); inm[inm]&=mask[vi[inm],ui[inm]]
 odp=np.zeros(len(pts)); odp[inm]=depth[vi[inm],ui[inm]]; vis=inm&(np.abs(z-odp)<=0.01)&(pts[:,2]>0.02); occm=inm&(z>odp+0.01)&(pts[:,2]>0.02)
 Vv=np.zeros_like(T); Vv[vis.reshape(T.shape)]=True; Uu=np.zeros_like(T); Uu[occm.reshape(T.shape)]=True
 if ARM=='obs':
  occ=Vv|Uu
 else:
  glb=ROOT/'assets/v6/m3/E1'/ident/'model.glb'; Mreg=np.asarray(_json.loads((ROOT/'runs/v6/m3/E1/reg_local'/ident/'align.json').read_text())['best']['M'],float)
  mesh=trimesh.load(str(glb),force='mesh',process=False).apply_transform(Mreg); P=R.column_fill_top(mesh,g); occ=Vv|(P&Uu)
 # build collision for FULL
 d=ROOT/'runs/v6/m3/E1'/ARM; d.mkdir(parents=True,exist_ok=True); grid=d/'occ.npz'; np.savez_compressed(grid,occupied=occ,origin=g['origin'],pitch=np.float64(0.004),dims=g['dims'],content_sha=np.array('m3e1full'),convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
 coll=d/'coll'; r=v3_core.build_collision(grid,coll,pitch=0.004,downsample=1); print('coll',r.get('ok'))
 spec=route_spec(coll=coll); arm=wheelleg_env.WheelLegEnv(spec,max_seconds=120); arm.reset(seed=0); ck=C.grid_from_V({'origin':g['origin'],'pitch':0.004,'dims':g['dims']})
 core={'spec':spec,'snapshot':snap,'visible':C.visible_dims(ROOT/'runs/v6/m3/E1/observation2'),'state':{'state_id':'m3e1','state_hash':'m3e1'}}
 acts=['R1','R2','D1','D2','L1','L2','BODY_CLEARANCE']
 rr,_=v3_core.rehearse_on_spec(core,spec,snap,json.loads((ROOT/'plans/v3_protocol.json').read_text()),mode='project',options=acts,body_plan={'raise_z':0.06,'ramp_steps':40,'speed':0.4,'lower_at_x':9.6,'end_x':20.0,'stop_tilt_deg':12.0,'plan_id':'m3e1'},budget=120.0,record_cells=True,record_root=d/'rehearsal')
 rows=[]
 for row in rr:
  if row['action']=='A0': continue
  tref=row.get('trajectory_ref'); c=E.contact_of(tref['trajectory_path']) if tref else None
  rows.append({'action':row['action'],'success':bool(row['success'] and (c or 0)==0),'cost':row.get('cost',60),'contacts':c,'t_end':row.get('t_end')})
 safe=[x for x in rows if x['success']]
 pick=sorted(safe,key=lambda x:x['cost'])[0]['action'] if safe else 'A0'; print('rehearsal',[(x['action'],x['success'],x['cost']) for x in rows],'pick',pick)
 out=d/'execution'; ex=v3_core.run_action(env,snap,pick,core['visible'],mode='same_scene',record_dir=out); print('exec',ex.get('outcome'),ex.get('reason'),ex.get('t_end'))
 if ex.get('success'):
  drive(env,20.0,BASE); print('route end x',float(env.data.qpos[0]),'t',float(env.t),'term',getattr(env,'last_termination',None))
 (d/'result.json').write_text(json.dumps({'start_x':float(snap.get('mjstate',[0])[0]) if False else None,'pick':pick,'exec':{k:ex.get(k) for k in ('outcome','reason','t_end','final_x')},'route_x':float(env.data.qpos[0]),'route_t':float(env.t),'termination':getattr(env,'last_termination',None)},default=str,indent=2))
if __name__=='__main__': main()
