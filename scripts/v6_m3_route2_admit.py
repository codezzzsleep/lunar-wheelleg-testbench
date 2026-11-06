"""Local registration/admission for route2 E1 candidates (CLI: enc, rock, x)."""
import csv,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_register,camera_io,v3_generate
from PIL import Image
enc=sys.argv[1]; rock=sys.argv[2]; x0=float(sys.argv[3]); E=ROOT/'runs/v6/m3'/enc; od=E/'observation'
ob=json.loads((od/'observation.json').read_text()); depth=np.load(od/'depth.npy'); mask=np.asarray(Image.open(od/'mask.png').convert('L'))>127
g={'origin':np.array([x0-0.35,-0.5,-0.05]),'pitch':0.004}; dims=(160,250,100); g['dims']=np.array(dims); g['xs']=g['origin'][0]+(np.arange(dims[0])+0.5)*0.004; g['ys']=g['origin'][1]+(np.arange(dims[1])+0.5)*0.004; g['zs']=g['origin'][2]+(np.arange(dims[2])+0.5)*0.004
m=trimesh.load(str(ROOT/'assets/v3/rocks'/rock/'h1/body_vis.obj'),force='mesh',process=False); m.apply_translation([x0+0.00943486-m.bounds[0][0],0.10507088-m.bounds[0][1],-m.bounds[0][2]])
T=R.column_fill_top(m,g)
pts=np.stack(np.meshgrid(g['xs'],g['ys'],g['zs'],indexing='ij'),-1).reshape(-1,3); u,v,z=camera_io.project(pts,ob['camera']); H,W=depth.shape
ok=np.isfinite(u)&np.isfinite(v)&(z>0); ui=np.clip(np.round(u).astype(int),0,W-1); vi=np.clip(np.round(v).astype(int),0,H-1); inm=ok&(u>=0)&(u<W)&(v>=0)&(v<H); inm[inm]&=mask[vi[inm],ui[inm]]
odp=np.zeros(len(pts)); odp[inm]=depth[vi[inm],ui[inm]]; vis=inm&(np.abs(z-odp)<=0.01)&(pts[:,2]>0.02); occ=inm&(z>odp+0.01)&(pts[:,2]>0.02)
V=np.zeros_like(T); U=np.zeros_like(T); V[vis.reshape(T.shape)]=True; U[occ.reshape(T.shape)]=True; U|=~V
Vz={'shell':V,'space':np.where(V,1,np.where(U,0,2)),'origin':g['origin'],'pitch':0.004,'dims':g['dims']}
cfg=json.loads((ROOT/'configs/v5_admission.json').read_text()); proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); vp=od/'visible_points.npy'
if not vp.exists():
 pts_all,ys,xs=camera_io.unproject_depth(depth.astype(np.float64),ob['camera']); keep=mask[ys,xs]; np.save(vp,pts_all[keep])
obs=v3_register.load_observation(str(od))
rows=[]; E.joinpath('reg').mkdir(exist_ok=True)
for t in json.loads((E/'tasks.json').read_text())['tasks']:
 ident=v3_generate.identity_of(t); glb=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
 if not glb.exists(): continue
 rd=E/'reg'/ident; rd.mkdir(parents=True,exist_ok=True)
 ys,xs=np.nonzero(mask); dc=float(np.median(depth[ys,xs]))
 K=ob['camera']['intrinsics']; Rm=np.asarray(ob['camera']['R_world_from_camera'],float); tw=np.asarray(ob['camera']['world_pos'],float)
 wpts,wy,wx=camera_io.unproject_depth(depth.astype(np.float64),ob['camera']); pms=wpts[mask[wy,wx]]; ctr=np.median(pms,axis=0)
 hpx=float(ys.max()-ys.min()+1); size=hpx*dc/K['fy']; mh=float(m.bounds[1][2]-m.bounds[0][2]); sc=max(0.2,min(2.0,size/mh))
 Mc=np.eye(4); Mc[:3,:3]*=sc; Mc[:3,3]=ctr-sc*np.asarray(m.centroid,float); Mc[2,3]=max(Mc[2,3],-float(m.bounds[0][2])*sc)
 rec={'best':{'M':Mc}}
 M=np.asarray(rec['best']['M'],float)
 cand=trimesh.load(str(glb),force='mesh',process=False)
 mh=float(cand.bounds[1][2]-cand.bounds[0][2]); sc2=max(0.2,min(2.0,(ys.max()-ys.min()+1)*dc/K['fy']/mh)); Mc[:3,:3]=np.eye(3)*sc2; Mc[:3,3]=ctr-sc2*np.asarray(cand.centroid,float); Mc[2,3]=max(Mc[2,3],-float(cand.bounds[0][2])*sc2); M=Mc
 mesh=cand.apply_transform(M); ev=v3_register.evaluate_matrix(mesh,obs,np.eye(4)); met=C.admission_metrics(mesh,np.eye(4),Vz,g,ev); hm=R.hidden_metrics(met['P'],T,U,g)
 ok2=bool(cfg['scale_ratio']['min']<=met['scale_ratio']<=cfg['scale_ratio']['max'] and met['hidden_frac']>=cfg['hidden_frac_min'] and met['shell_contact']>=cfg['shell_contact_min'] and met['free_intrusion_frac']<=cfg['free_intrusion_max'] and met['contour_iou']>=cfg['contour_iou_min'])
 rows.append({'id':t['id'],'identity':ident,'admitted':ok2,'rear':hm['rear_err_m'],'p95':hm['path_p95_mm'],'scale':met['scale_ratio'],'contour':met['contour_iou'],'shell':met['shell_contact'],'intrusion':met['free_intrusion_frac']})
with (E/'admission.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('rows',len(rows),'admitted',sum(r['admitted'] for r in rows))
