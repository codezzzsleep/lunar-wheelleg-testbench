"""M1: evaluate one WP3 view with its own V/U/truth built from the rendered camera."""
import argparse,csv,json,pathlib,sys
import numpy as np,trimesh
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_register,v3_generate,camera_io
STATES={'moon_rock_01':'moon_rock_01_h1v0','moon_rock_02':'moon_rock_02_h1v0','moon_rock_03':'moon_rock_03_h1v0','moon_rock_04':'moon_rock_04_h1v0','moon_rock_05':'moon_rock_05_h1v0','moon_rock_06':'moon_rock_06_h1v0','moon_rock_07':'moon_rock_07_h0v0','rock_07':'rock_07_h2v1'}
def build_obs(view,out):
 out.mkdir(parents=True,exist_ok=True)
 cam=json.loads((view/'camera.json').read_text()); depth=np.load(view/'depth.npy').astype(np.float64)
 mask=np.asarray(Image.open(view/'mask.png').convert('L'))>127
 pts,ys,xs=camera_io.unproject_depth(depth,cam); ok=mask[ys,xs]; pts=pts[ok]
 ob={'schema':'observation/v1','rock':view.parent.name,'camera':cam,'intrinsics':cam['intrinsics'],'image':'rgb.png','camera_schema':'camera-snapshot/v2'}
 (out/'observation.json').write_text(json.dumps(ob,indent=2)); np.save(out/'visible_points.npy',pts)
 np.save(out/'depth.npy',depth); Image.fromarray((mask*255).astype(np.uint8)).save(out/'mask.png')
 ob['depth']=depth; ob['mask']=mask
 return ob
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--rock',required=True); ap.add_argument('--view',type=int,required=True); ap.add_argument('--out',default='runs/v6/m1/views'); a=ap.parse_args()
 st=STATES[a.rock]; d=ROOT/'runs/v3/states'/st; V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0)
 mesh_path=d/'truth/body_world.stl'
 if a.rock=='moon_rock_05': mesh_path=ROOT/'runs/v3/stage008/truth_v2/truth/body_world.stl'
 tm=trimesh.load(str(mesh_path),force='mesh',process=False); T=R.column_fill_top(tm,g)
 view=ROOT/'runs/v4/wp3/views'/a.rock/f'yaw{a.view:+d}'; od=ROOT/a.out/f'{a.rock}_yaw{a.view:+d}'/'observation'; ob=build_obs(view,od)
 # per-view V/U from rendered depth
 cam=ob['camera']; H,W=ob['depth'].shape
 ix,iy,iz=np.nonzero(T|U)
 pts=np.stack([g['xs'][ix],g['ys'][iy],g['zs'][iz]],1); u,v,z=camera_io.project(pts,cam)
 good=np.isfinite(u)&np.isfinite(v)&(z>0); ui=np.clip(np.round(u).astype(int),0,W-1); vi=np.clip(np.round(v).astype(int),0,H-1)
 inmask=good&(u>=0)&(u<W)&(v>=0)&(v<H); inmask[inmask]&=ob['mask'][vi[inmask],ui[inmask]]
 obs_d=np.zeros(len(pts)); obs_d[inmask]=ob['depth'][vi[inmask],ui[inmask]]
 Vv=np.zeros_like(T); Uu=np.zeros_like(T)
 vis=inmask&(np.abs(z-obs_d)<=0.01)&(pts[:,2]>0.02)
 occ=inmask&(z>obs_d+0.01)&(pts[:,2]>0.02)
 Vv[ix[vis],iy[vis],iz[vis]]=True; Uu[ix[occ],iy[occ],iz[occ]]=True
 Uu|= (U & ~Vv) if False else False
 obs=v3_register.load_observation(str(od)); proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); adcfg=json.loads((ROOT/'configs/v5_admission.json').read_text())
 tasks=[t for t in json.loads((ROOT/'runs/v4/wp3/tasks.json').read_text())['tasks'] if t['rock']==a.rock and int(t['view_yaw_deg'])==a.view]
 rows=[]
 for t in tasks:
  ident=v3_generate.identity_of(t); glb=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
  if not glb.exists(): continue
  rd=ROOT/a.out/f'{a.rock}_yaw{a.view:+d}'/'reg'/ident; rd.mkdir(parents=True,exist_ok=True)
  rec=v3_register.register(str(glb),str(od),proto,rd,top_k=6); Mreg=np.asarray(rec['best']['M'],float)
  mesh=trimesh.load(str(glb),force='mesh',process=False).apply_transform(Mreg)
  ev=v3_register.evaluate_matrix(mesh,obs,np.eye(4)); m=C.admission_metrics(mesh,np.eye(4),V,g,ev); hm=R.hidden_metrics(m['P'],T,U,g)
  ok=bool(adcfg['scale_ratio']['min']<=m['scale_ratio']<=adcfg['scale_ratio']['max'] and m['hidden_frac']>=adcfg['hidden_frac_min'] and m['shell_contact']>=adcfg['shell_contact_min'] and m['free_intrusion_frac']<=adcfg['free_intrusion_max'] and m['contour_iou']>=adcfg['contour_iou_min'])
  rows.append({'source':'WP3','rock':a.rock,'view':a.view,'task':t['id'],'candidate':t['crop'],'repeat':t['repeat_idx'],'admitted':ok,'rear_err_m':hm['rear_err_m'],'top_err_m':hm['top_err_m'],'path_p95_mm':hm['path_p95_mm'],'hidden_iou':round(float((m['P']&U&T).sum())/max(1,int(((m['P']&U)|(T&U)).sum())),4),'scale_ratio':m['scale_ratio'],'hidden_frac':m['hidden_frac'],'shell_contact':m['shell_contact'],'free_intrusion_frac':m['free_intrusion_frac'],'contour_iou':m['contour_iou']})
 p=ROOT/a.out/f'{a.rock}_yaw{a.view:+d}'/'checkup.csv'
 with p.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
 print(a.rock,a.view,'rows',len(rows),'admitted',sum(r['admitted'] for r in rows))
if __name__=='__main__': main()
