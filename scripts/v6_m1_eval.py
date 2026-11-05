"""M1 partial: evaluate v3 candidates with C0 metrics; merge C3 yaw0 checkup."""
import csv,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_register
adcfg=json.loads((ROOT/'configs/v5_admission.json').read_text())
rows=[]
for d in sorted((ROOT/'runs/v3/states').iterdir()):
 if not (d/'fusion/V.npz').exists(): continue
 V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0)
 tm=trimesh.load(str(d/'truth/body_world.stl'),force='mesh',process=False); T=R.column_fill_top(tm,g)
 obs=v3_register.load_observation(str(d/'observation'))
 for cd in sorted((d/'candidates').glob('*')):
  mp=cd/'parent_world'/'body.stl'
  if not mp.exists(): continue
  mesh=trimesh.load(str(mp),force='mesh',process=False); ev=v3_register.evaluate_matrix(mesh,obs,np.eye(4)); m=C.admission_metrics(mesh,np.eye(4),V,g,ev); hm=R.hidden_metrics(m['P'],T,U,g)
  ok=bool(adcfg['scale_ratio']['min']<=m['scale_ratio']<=adcfg['scale_ratio']['max'] and m['hidden_frac']>=adcfg['hidden_frac_min'] and m['shell_contact']>=adcfg['shell_contact_min'] and m['free_intrusion_frac']<=adcfg['free_intrusion_max'] and m['contour_iou']>=adcfg['contour_iou_min'])
  rows.append({'source':'v3','state':d.name,'candidate':cd.name,'admitted':ok,'rear_err_m':hm['rear_err_m'],'top_err_m':hm['top_err_m'],'path_p95_mm':hm['path_p95_mm'],'hidden_iou':round(float((m['P']&U&T).sum())/max(1,int(((m['P']&U)|(T&U)).sum())),4),'scale_ratio':m['scale_ratio'],'hidden_frac':m['hidden_frac'],'shell_contact':m['shell_contact'],'free_intrusion_frac':m['free_intrusion_frac'],'contour_iou':m['contour_iou']})
  print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
# merge C3 yaw0
for r in csv.DictReader(open(ROOT/'runs/v5/c3/checkup.csv')):
 if r.get('admitted') not in ('True','False'): continue
 rows.append({'source':'WP3yaw0','state':r['task'],'candidate':'', 'admitted':r['admitted']=='True','rear_err_m':float(r['rear_err_m']) if r['rear_err_m'] else None,'top_err_m':float(r['top_err_m']) if r['top_err_m'] else None,'path_p95_mm':float(r['path_p95_mm']) if r['path_p95_mm'] else None,'hidden_iou':None,'scale_ratio':float(r['scale_ratio']) if r['scale_ratio'] else None,'hidden_frac':float(r['hidden_frac']) if r['hidden_frac'] else None,'shell_contact':float(r['shell_contact']) if r['shell_contact'] else None,'free_intrusion_frac':float(r['free_intrusion_frac']) if r['free_intrusion_frac'] else None,'contour_iou':float(r['contour_iou']) if r['contour_iou'] else None})
out=ROOT/'runs/v6/m1'; out.mkdir(parents=True,exist_ok=True)
fields=['source','state','candidate','admitted','rear_err_m','top_err_m','path_p95_mm','hidden_iou','scale_ratio','hidden_frac','shell_contact','free_intrusion_frac','contour_iou']
with (out/'checkup_all.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
print('total',len(rows),'v3',sum(r['source']=='v3' for r in rows),'wp3',sum(r['source']=='WP3yaw0' for r in rows))
