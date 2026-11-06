"""Local E1 registration/admission (no sandbox)."""
import json,pathlib,sys,csv
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_register
from PIL import Image
E=ROOT/'runs/v6/m3/E2'; od=E/'observation_second'
ob=json.loads((od/'observation.json').read_text()); depth=np.load(od/'depth.npy'); mask=np.asarray(Image.open(od/'mask.png').convert('L'))>127
g={'origin':np.array([14.6,-0.5,-0.05]),'pitch':0.004}; dims=(180,250,100); g['dims']=np.array(dims)
g['xs']=g['origin'][0]+(np.arange(dims[0])+0.5)*0.004; g['ys']=g['origin'][1]+(np.arange(dims[1])+0.5)*0.004; g['zs']=g['origin'][2]+(np.arange(dims[2])+0.5)*0.004
m=trimesh.load(str(ROOT/'assets/v3/rocks/moon_rock_01/h1/body_vis.obj'),force='mesh',process=False); m.apply_translation([15.0,0.0,0.0])
T=R.column_fill_top(m,g); V=np.zeros_like(T); U=np.zeros_like(T)
import camera_io
pts=np.stack(np.meshgrid(g['xs'],g['ys'],g['zs'],indexing='ij'),-1).reshape(-1,3); u,v,z=camera_io.project(pts,ob['camera']); H,W=depth.shape
ok=np.isfinite(u)&np.isfinite(v)&(z>0); ui=np.clip(np.round(u).astype(int),0,W-1); vi=np.clip(np.round(v).astype(int),0,H-1); inm=ok&(u>=0)&(u<W)&(v>=0)&(v<H); inm[inm]&=mask[vi[inm],ui[inm]]
odp=np.zeros(len(pts)); odp[inm]=depth[vi[inm],ui[inm]]; vis=inm&(np.abs(z-odp)<=0.01)&(pts[:,2]>0.02); occ=inm&(z>odp+0.01)&(pts[:,2]>0.02)
V[vis.reshape(T.shape)]=True; U[occ.reshape(T.shape)]=True; U|=~V
Vz={'shell':V,'space':np.where(V,1,np.where(U,0,2)),'origin':g['origin'],'pitch':0.004,'dims':g['dims']}
adcfg=json.loads((ROOT/'configs/v5_admission.json').read_text()); proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); obs=v3_register.load_observation(str(od)); rows=[]
for d in sorted((ROOT/'assets/v6/m3/E2imgs').iterdir()):
 glb=d/'model.glb'
 if not glb.exists(): continue
 rd=E/'reg_second'/d.name; rd.mkdir(parents=True,exist_ok=True); rec=v3_register.register(str(glb),str(od),proto,rd,top_k=6); Mreg=np.asarray(rec['best']['M'],float)
 mesh=trimesh.load(str(glb),force='mesh',process=False).apply_transform(Mreg); ev=v3_register.evaluate_matrix(mesh,obs,np.eye(4)); met=C.admission_metrics(mesh,np.eye(4),Vz,g,ev); hm=R.hidden_metrics(met['P'],T,U,g)
 ok2=bool(adcfg['scale_ratio']['min']<=met['scale_ratio']<=adcfg['scale_ratio']['max'] and met['hidden_frac']>=adcfg['hidden_frac_min'] and met['shell_contact']>=adcfg['shell_contact_min'] and met['free_intrusion_frac']<=adcfg['free_intrusion_max'] and met['contour_iou']>=adcfg['contour_iou_min'])
 rows.append({'identity':d.name,'admitted':ok2,'rear_err_m':hm['rear_err_m'],'path_p95_mm':hm['path_p95_mm'],'scale_ratio':met['scale_ratio'],'contour_iou':met['contour_iou'],'shell_contact':met['shell_contact'],'free_intrusion_frac':met['free_intrusion_frac']})
with (E/'admission_second.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('rows',len(rows),'admitted',sum(r['admitted'] for r in rows))
