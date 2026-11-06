"""R2 E1: FULL fusion from admitted candidates, 3/3 rehearsal, decision (local)."""
import csv,json,pathlib,sys
import numpy as np,trimesh,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,terrain,v7_soil,v3_core,v5_core as C,v5_metrics_ref as R,camera_io
from PIL import Image
sys.path.insert(0,str(ROOT/'scripts')); import v6_m3_route2 as RW
E=ROOT/'runs/v6/m3/route2/E1'; ACTS=['R1','R2','D1','D2','L1','L2']
def main():
 gm=json.loads((E/'geometry.json').read_text()); spec=RW.make_route_spec(); spec['objects'][1]={'mesh_file':str(ROOT/gm['rock_mesh']),'x':9.0,'y':0.1,'target_height_m':gm['height']}; spec['front_cam']={'pos':gm['cam_local'],'pitch_deg':gm['pitch_deg'],'fovy':70.0}
 od=E/'observation'; ob=json.loads((od/'observation.json').read_text()); depth=np.load(od/'depth.npy'); mask=np.asarray(Image.open(od/'mask.png').convert('L'))>127
 g={'origin':np.array([8.6,-0.5,-0.05]),'pitch':0.004}; dims=(180,250,100); g['dims']=np.array(dims); g['xs']=g['origin'][0]+(np.arange(dims[0])+0.5)*0.004; g['ys']=g['origin'][1]+(np.arange(dims[1])+0.5)*0.004; g['zs']=g['origin'][2]+(np.arange(dims[2])+0.5)*0.004
 m=trimesh.load(str(ROOT/gm['rock_mesh']),force='mesh',process=False); m.apply_translation([9.0+0.00943486-m.bounds[0][0],0.1+0.00507088-m.bounds[0][1],-m.bounds[0][2]]); T=R.column_fill_top(m,g)
 pts=np.stack(np.meshgrid(g['xs'],g['ys'],g['zs'],indexing='ij'),-1).reshape(-1,3); u,v,z=camera_io.project(pts,ob['camera']); H,W=depth.shape
 ok=np.isfinite(u)&np.isfinite(v)&(z>0); ui=np.clip(np.round(u).astype(int),0,W-1); vi=np.clip(np.round(v).astype(int),0,H-1); inm=ok&(u>=0)&(u<W)&(v>=0)&(v<H); inm[inm]&=mask[vi[inm],ui[inm]]
 odp=np.zeros(len(pts)); odp[inm]=depth[vi[inm],ui[inm]]; vis=inm&(np.abs(z-odp)<=0.01)&(pts[:,2]>0.02); occ=inm&(z>odp+0.01)&(pts[:,2]>0.02)
 V=np.zeros_like(T); U=np.zeros_like(T); V[vis.reshape(T.shape)]=True; U[occ.reshape(T.shape)]=True; U|=~V
 rows=list(csv.DictReader(open(E/'admission.csv'))); adm=[r for r in rows if r['admitted']=='True']
 P=np.zeros_like(T)
 for r in adm:
  glb=ROOT/'runs/v3/generation/cache'/r['identity']/'model.glb'; M=np.asarray(json.loads((E/'reg'/r['identity']/'align.json').read_text())['best']['M'],float); mesh=trimesh.load(str(glb),force='mesh',process=False).apply_transform(M); P|=R.column_fill_top(mesh,g)
 full=V|(P&U)
 d=E/'full'; d.mkdir(exist_ok=True); np.savez_compressed(d/'occ.npz',occupied=full,origin=g['origin'],pitch=np.float64(0.004),dims=g['dims'],content_sha=np.array('r2e1full'),convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
 coll=d/'coll'; v3_core.build_collision(d/'occ.npz',coll,pitch=0.004,downsample=1)
 arm_spec=json.loads(json.dumps(spec)); arm_spec['objects']=[{'posed_dir':str(coll)}]
 st=np.load(E/'state.npz'); q0=st['qpos']; v0=st['qvel']
 rows2=[]
 for a in ACTS:
  ok3=0; contacts=[]
  for k,(dx,dyaw) in enumerate([(0,0),(0.02,0.02),(-0.02,-0.02)]):
   env=wheelleg_env.WheelLegEnv(arm_spec,max_seconds=90); env.reset(seed=0); env.data.qpos[:]=q0; env.data.qpos[0]+=dx; env.data.qvel[:]=v0; env.data.qpos[3:7]=q0[3:7]; mujoco.mj_forward(env.model,env.data); sn=env.save_state()
   r=v3_core.run_action(env,sn,a,{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},mode='same_scene',record_dir=d/f'rehearsal/{a}_{k}')
   good=bool(r.get('success')) and int(r.get('contacts') or 0)==0; ok3+=int(good); contacts.append(int(r.get('contacts') or 0))
  rows2.append({'action':a,'pass3':ok3,'contacts':contacts})
 (d/'rehearsal.json').write_text(json.dumps(rows2,indent=2)); safe=[r['action'] for r in rows2 if r['pass3']==3]
 (d/'decision.json').write_text(json.dumps({'admitted':[r['identity'] for r in adm],'rehearsal':rows2,'safe':safe,'chosen':(safe[0] if safe else 'A0')},indent=2)); print('admitted',len(adm),'safe',safe)
if __name__=='__main__': main()
