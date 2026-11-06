"""M1 per-view KA1 (truth prior) and KA5 (10 cm rear cut)."""
import csv,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_register,camera_io
from PIL import Image
STATES={'moon_rock_01':'moon_rock_01_h1v0','moon_rock_02':'moon_rock_02_h1v0','moon_rock_03':'moon_rock_03_h1v0','moon_rock_04':'moon_rock_04_h1v0','moon_rock_06':'moon_rock_06_h1v0','moon_rock_07':'moon_rock_07_h0v0','rock_07':'rock_07_h2v1'}
rows=[]
for rock,st in STATES.items():
 T=np.load(ROOT/'runs/v3/states'/st/'fusion/V.npz'); g=C.grid_from_V(T); U=(T['space']==0)
 mp=ROOT/'runs/v3/states'/st/'truth/body_world.stl'
 if rock=='moon_rock_05': mp=ROOT/'runs/v3/stage008/truth_v2/truth/body_world.stl'
 mesh0=trimesh.load(str(mp),force='mesh',process=False)
 for yaw in (25,-25):
  od=ROOT/'runs/v6/m1/views'/f'{rock}_yaw{yaw:+d}'/'observation'
  if not (od/'observation.json').exists(): continue
  ob=json.loads((od/'observation.json').read_text()); depth=np.load(od/'depth.npy'); mask=np.asarray(Image.open(od/'mask.png').convert('L'))>127
  pts=np.stack(np.meshgrid(g['xs'],g['ys'],g['zs'],indexing='ij'),-1).reshape(-1,3); u,v,z=camera_io.project(pts,ob['camera']); H,W=depth.shape
  ok=np.isfinite(u)&np.isfinite(v)&(z>0); ui=np.clip(np.round(u).astype(int),0,W-1); vi=np.clip(np.round(v).astype(int),0,H-1); inm=ok&(u>=0)&(u<W)&(v>=0)&(v<H); inm[inm]&=mask[vi[inm],ui[inm]]
  odp=np.zeros(len(pts)); odp[inm]=depth[vi[inm],ui[inm]]; vis=inm&(np.abs(z-odp)<=0.01)&(pts[:,2]>0.02); occ=inm&(z>odp+0.01)&(pts[:,2]>0.02)
  V=np.zeros_like(U); V[vis.reshape(U.shape)]=True; Uu=np.zeros_like(U); Uu[occ.reshape(U.shape)]=True; Uu|=~V
  Vz={'shell':V,'space':np.where(V,1,np.where(Uu,0,2)),'origin':g['origin'],'pitch':0.004,'dims':g['dims']}
  def met(mesh,M=np.eye(4)):
   ev=v3_register.evaluate_matrix(mesh,v3_register.load_observation(str(od)),M); m=C.admission_metrics(mesh,M,Vz,g,ev); hm=R.hidden_metrics(m['P'],R.column_fill_top(mesh,g),Uu,g); return m,hm
  cfg=json.loads((ROOT/'configs/v5_admission.json').read_text())
  def admit(m): return bool(cfg['scale_ratio']['min']<=m['scale_ratio']<=cfg['scale_ratio']['max'] and m['hidden_frac']>=cfg['hidden_frac_min'] and m['shell_contact']>=cfg['shell_contact_min'] and m['free_intrusion_frac']<=cfg['free_intrusion_max'] and m['contour_iou']>=cfg['contour_iou_min'])
  m1,h1=met(mesh0); ka1=admit(m1)
  tt=R.column_fill_top(mesh0,g); rear=float(g['xs'][tt.any(axis=(1,2))].max()) if tt.any() else float(mesh0.bounds[1][0])
  cut=mesh0.slice_plane([rear-0.10,0,0],[-1,0,0],cap=False); m5,h5=met(cut); ka5=bool(abs((h5['rear_err_m'] or 0)+0.10)<=0.0025)
  rows.append({'rock':rock,'view':yaw,'KA1':ka1,'KA5':ka5,'KA1_scale':round(m1['scale_ratio'],3),'KA1_contour':round(m1['contour_iou'],3),'KA5_rear':round(h5['rear_err_m'],4) if h5['rear_err_m'] is not None else ''})
p=ROOT/'runs/v6/m1/view_ka15.csv'
with p.open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('rows',len(rows),'KA1',sum(r['KA1'] for r in rows),'KA5',sum(r['KA5'] for r in rows))
