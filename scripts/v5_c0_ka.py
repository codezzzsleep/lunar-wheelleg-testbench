"""C0: calibrate v5 admission from known answers and run KA1-KA6 on truth_v2."""
import json,pathlib,sys,csv
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v3_register
T=ROOT/'runs/v3/stage008/truth_v2'
def main():
 z=np.load(T/'fusion/V.npz'); V=z; g=C.grid_from_V(V); obs=v3_register.load_observation(str(T/'observation'))
 mesh0=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False)
 Tp=R.column_fill_top(mesh0,g); c=mesh0.vertices.mean(0); I=np.eye(4)
 def met(mesh,M):
  ev=v3_register.evaluate_matrix(mesh,obs,M); m=C.admission_metrics(mesh,M,V,g,ev); hm=R.hidden_metrics(m['P'],Tp,(V['space']==0),g); return m,hm
 cases=[]
 for dx in (-0.02,0.0,0.02):
  for s in (0.9,1.0,1.1):
   M=np.eye(4); M[:3,:3]=s*np.eye(3); M[:3,3]=c-s*c; M[0,3]+=dx
   m,hm=met(mesh0,M); cases.append((f'good_dx{dx:+.2f}_s{s}',m,hm))
 good=[m for _,m,_ in cases]
 cfg={'schema':'v5-admission/v1','calibrated_from':'truth_v2 KA set',
  'scale_ratio':{'min':round(min(m['scale_ratio'] for m in good)-0.03,3),'max':round(max(m['scale_ratio'] for m in good)+0.03,3)},
  'hidden_frac_min':round(max(0.02,min(m['hidden_frac'] for m in good)*0.5),4),
  'shell_contact_min':round(min(m['shell_contact'] for m in good)*0.8,4),
  'free_intrusion_max':round(max(m['free_intrusion_frac'] for m in good)*1.15,4),
  'contour_iou_min':round(min(m['contour_iou'] for m in good)-0.05,4),
  'notes':'calibrated before candidates; column_fill_top; truth prior intrusion is not 2%'}
 (ROOT/'configs').mkdir(exist_ok=True); (ROOT/'configs/v5_admission.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
 def admit(m):
  return bool(cfg['scale_ratio']['min']<=m['scale_ratio']<=cfg['scale_ratio']['max'] and m['hidden_frac']>=cfg['hidden_frac_min']
              and m['shell_contact']>=cfg['shell_contact_min'] and m['free_intrusion_frac']<=cfg['free_intrusion_max']
              and m['contour_iou']>=cfg['contour_iou_min'])
 rows=[]
 def add(name,inp,mesh,M):
  m,hm=met(mesh,M); rows.append({'case':name,'input':inp,'admitted':admit(m),'rear_err_m':hm['rear_err_m'],'top_err_m':hm['top_err_m'],'path_p95_mm':hm['path_p95_mm'],'scale_ratio':m['scale_ratio'],'shell_contact':m['shell_contact'],'free_intrusion_frac':m['free_intrusion_frac'],'contour_iou':m['contour_iou'],'voxels':m['voxels']}); return m,hm
 add('KA1_truth','truth',mesh0,I)
 Mt=np.eye(4); Mt[0,3]=0.15; add('KA2_shift15cm','truth+15cm',mesh0,Mt)
 Ms=np.eye(4); Ms[:3,:3]=0.6*np.eye(3); Ms[:3,3]=c-0.6*c; add('KA3_scale06','truth*0.6',mesh0,Ms)
 keep=[f for f in mesh0.faces if mesh0.vertices[f][:,2].min()>0.005]
 m4=trimesh.Trimesh(mesh0.vertices.copy(),np.array(keep),process=False); m4=trimesh.util.concatenate([m4,m4.copy()]); m4m,h4=add('KA4_bottom_removed_dup','shell dup',m4,I)
 rows[-1]['ka4_voxel_diff_frac']=round(abs(m4m['voxels']-int(Tp.sum()))/int(Tp.sum()),5); rows[-1]['admitted']=bool(rows[-1]['ka4_voxel_diff_frac']<=0.02 and admit(m4m))
 rear=float(g['xs'][Tp.any(axis=(1,2))].max()); cut=mesh0.slice_plane([rear-0.10,0,0],[-1,0,0],cap=False)
 m5,h5=add('KA5_cut10cm','rear cut',cut,I); rows[-1]['admitted']=bool(abs((h5['rear_err_m'] or 0)+0.10)<=0.0025)
 add('KA6_projection','truth proj',mesh0,I); rows[-1]['admitted']=bool(rows[-1]['contour_iou']>=0.95)
 out=ROOT/'runs/v5/c0'; out.mkdir(parents=True,exist_ok=True)
 fields=[]
 for r in rows:
  for k in r:
   if k not in fields: fields.append(k)
 with (out/'known_answer.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
 print(json.dumps(cfg,ensure_ascii=False))
 for r in rows: print(json.dumps(r,ensure_ascii=False))
 ok={'KA1_truth':lambda r:r['admitted'],'KA2_shift15cm':lambda r:not r['admitted'],'KA3_scale06':lambda r:not r['admitted'],
     'KA4_bottom_removed_dup':lambda r:r['admitted'] and r.get('ka4_voxel_diff_frac',1)<=0.02,
     'KA5_cut10cm':lambda r:abs((r['rear_err_m'] or 0)+0.10)<=0.0025,'KA6_projection':lambda r:r['contour_iou']>=0.95}
 for r in rows: r['expected_pass']=bool(ok[r['case']](r))
 print('all_pass',all(r['expected_pass'] for r in rows))
if __name__=='__main__': main()
