"""C3: re-evaluate WP3 GLBs with C0 metrics (yaw 0 scenes with own V/U)."""
import argparse,csv,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_register,v3_generate
STATES={'moon_rock_01':'moon_rock_01_h1v0','moon_rock_02':'moon_rock_02_h1v0','moon_rock_03':'moon_rock_03_h1v0','moon_rock_04':'moon_rock_04_h1v0','moon_rock_05':'moon_rock_05_h1v0','moon_rock_06':'moon_rock_06_h1v0','moon_rock_07':'moon_rock_07_h0v0','rock_07':'rock_07_h2v1'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--rocks',default=','.join(STATES)); ap.add_argument('--out',default='runs/v5/c3'); a=ap.parse_args()
 out=ROOT/a.out; out.mkdir(parents=True,exist_ok=True); proto=json.loads((ROOT/'plans/v3_protocol.json').read_text()); cfg=json.loads((ROOT/'configs/v5_admission.json').read_text())
 tasks=json.loads((ROOT/'runs/v4/wp3/tasks.json').read_text())['tasks']; rows=[]
 for rock,st in STATES.items():
  if rock not in a.rocks.split(','): continue
  d=ROOT/'runs/v3/states'/st; V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0)
  tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
  obsdir=str(d/'observation')
  for t in tasks:
   if t['rock']!=rock or int(t['view_yaw_deg'])!=0: continue
   ident=v3_generate.identity_of(t); cache=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
   row={'rock':rock,'view':0,'task':t['id'],'crop':t['crop'],'repeat':t['repeat_idx'],'identity':ident,'glb':cache.exists()}
   if not cache.exists(): rows.append(row); continue
   mesh=trimesh.load(str(cache),force='mesh',process=False); rd=out/'registered'/ident; rd.mkdir(parents=True,exist_ok=True)
   rec=v3_register.register(str(cache),obsdir,proto,rd,top_k=6); M=np.asarray(rec['best']['M'],float)
   ev=v3_register.evaluate_matrix(mesh,v3_register.load_observation(obsdir),M); m=C.admission_metrics(mesh,M,V,g,ev)
   ok=bool(cfg['scale_ratio']['min']<=m['scale_ratio']<=cfg['scale_ratio']['max'] and m['hidden_frac']>=cfg['hidden_frac_min'] and m['shell_contact']>=cfg['shell_contact_min'] and m['free_intrusion_frac']<=cfg['free_intrusion_max'] and m['contour_iou']>=cfg['contour_iou_min'])
   hm=R.hidden_metrics(m['P'],T,U,g)
   row.update({'admitted':ok,'rear_err_m':hm['rear_err_m'],'top_err_m':hm['top_err_m'],'path_mae_mm':hm['path_mae_mm'],'path_p95_mm':hm['path_p95_mm'],'scale_ratio':m['scale_ratio'],'hidden_frac':m['hidden_frac'],'shell_contact':m['shell_contact'],'free_intrusion_frac':m['free_intrusion_frac'],'contour_iou':m['contour_iou']})
   rows.append(row); print(json.dumps({k:row.get(k) for k in ('task','admitted','rear_err_m','top_err_m','path_p95_mm')},ensure_ascii=False),flush=True)
   (out/'checkup.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 fields=['rock','view','task','crop','repeat','identity','glb','admitted','rear_err_m','top_err_m','path_mae_mm','path_p95_mm','scale_ratio','hidden_frac','shell_contact','free_intrusion_frac','contour_iou']
 with (out/'checkup.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([{k:r.get(k) for k in fields} for r in rows])
 print('done',len(rows),'admitted',sum(bool(r.get('admitted')) for r in rows))
if __name__=='__main__': sys.exit(main())
