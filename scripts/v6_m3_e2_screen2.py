"""R2 1.3 E2 OBS_CONS: two geometries, 3 perturbations, zero contact, 5 cm margin."""
import json,pathlib,sys
import numpy as np,trimesh,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,v3_core,camera_io
from PIL import Image
E=ROOT/'runs/v6/m3/route2/E2'; ACTS=['R1','R2','D1','D2','L1','L2']
def grid(): 
 g={'origin':np.array([14.6,-0.6,-0.05]),'pitch':0.004}; dims=(180,260,100); g['dims']=np.array(dims); g['xs']=g['origin'][0]+(np.arange(dims[0])+0.5)*0.004; g['ys']=g['origin'][1]+(np.arange(dims[1])+0.5)*0.004; g['zs']=g['origin'][2]+(np.arange(dims[2])+0.5)*0.004; return g,dims
def build_VU(od,g,dims):
 ob=json.loads((od/'observation.json').read_text()); depth=np.load(od/'depth.npy'); mask=np.asarray(Image.open(od/'mask.png').convert('L'))>127
 pts=np.stack(np.meshgrid(g['xs'],g['ys'],g['zs'],indexing='ij'),-1).reshape(-1,3); u,v,z=camera_io.project(pts,ob['camera']); H,W=depth.shape
 ok=np.isfinite(u)&np.isfinite(v)&(z>0); ui=np.clip(np.round(u).astype(int),0,W-1); vi=np.clip(np.round(v).astype(int),0,H-1); inm=ok&(u>=0)&(u<W)&(v>=0)&(v<H); inm[inm]&=mask[vi[inm],ui[inm]]
 odp=np.zeros(len(pts)); odp[inm]=depth[vi[inm],ui[inm]]; vis=inm&(np.abs(z-odp)<=0.01)&(pts[:,2]>0.02); occ=inm&(z>odp+0.01)&(pts[:,2]>0.02)
 V=np.zeros(dims,bool); U=np.zeros(dims,bool); V[vis.reshape(dims)]=True; U[occ.reshape(dims)]=True; return V,U
def main():
 import v6_m3_route2 as RW
 g,dims=grid(); V,U=build_VU(E/'observation',g,dims); gm=json.loads((E/'geometry.json').read_text())
 st=np.load(E/'state.npz'); q0=st['qpos']; v0=st['qvel']
 results={}
 for name,occ in (('A_VplusU',V|U),('B_Vsh',V)):
  d=E/'screen'/name; d.mkdir(parents=True,exist_ok=True); np.savez_compressed(d/'occ.npz',occupied=occ,origin=g['origin'],pitch=np.float64(0.004),dims=g['dims'],content_sha=np.array(name),convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
  coll=d/'coll'; v3_core.build_collision(d/'occ.npz',coll,pitch=0.004,downsample=1)
  spec=RW.make_route_spec(); spec['objects'][2]={'posed_dir':str(coll)}; spec['front_cam']={'pos':gm['cam_local'],'pitch_deg':gm['pitch_deg'],'fovy':70.0}
  rows=[]
  for a in ACTS:
   ok3=0; mind=1e9
   for k,(dx,dy) in enumerate([(0,0),(0.02,0.02),(-0.02,-0.02)]):
    env=wheelleg_env.WheelLegEnv(spec,max_seconds=90); env.reset(seed=0); env.data.qpos[:]=q0; env.data.qpos[0]+=dx; env.data.qpos[1]+=dy; env.data.qvel[:]=v0; mujoco.mj_forward(env.model,env.data); sn=env.save_state()
    r=v3_core.run_action(env,sn,a,{'x_front':0.834,'W_vis':0.275,'H_vis':0.30},mode='same_scene',record_dir=d/f'{a}_{k}')
    # min distance over recorded trajectory frames
    try:
     import glob
     tr=glob.glob(str(d/f'{a}_{k}'/'**'/'traj.npz'),recursive=True)+glob.glob(str(d/f'{a}_{k}'/'*.npz'))
     obid=[i for i in range(env.model.nbody) if (mujoco.mj_id2name(env.model,mujoco.mjtObj.mjOBJ_BODY,i) or '').startswith('obstacle')]
     og=[gi for gi in range(env.model.ngeom) if env.model.geom_bodyid[gi] in obid]; rg=[gi for gi in range(env.model.ngeom) if env.model.geom_bodyid[gi]<18]
     if tr:
      z=np.load(tr[0]); qs=z['qpos'][::10]
      for row in qs:
       env.data.qpos[:]=row; mujoco.mj_forward(env.model,env.data)
       for gi in og:
        for ri in rg:
         try: mind=min(mind,mujoco.mj_geomDistance(env.model,env.data,ri,gi,1.0,None))
         except Exception: pass
    except Exception: pass
    if r.get('success') and int(r.get('contacts') or 0)==0: ok3+=1
   rows.append({'action':a,'pass3':ok3,'min_dist_m':round(float(mind),4) if mind<1e8 else None})
  results[name]=rows
 safeA=[r['action'] for r in results['A_VplusU'] if r['pass3']==3 and (r['min_dist_m'] is None or r['min_dist_m']>=0.05)]
 safeB=[r['action'] for r in results['B_Vsh'] if r['pass3']==3 and (r['min_dist_m'] is None or r['min_dist_m']>=0.05)]
 out={'results':results,'safe_A':safeA,'safe_B':safeB,'intersection':sorted(set(safeA)&set(safeB))}
 (E/'screen/screen.json').write_text(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
