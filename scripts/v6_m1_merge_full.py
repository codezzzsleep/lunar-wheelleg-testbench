"""Merge v3 75 + WP3 yaw0 47 + WP3 ±25 96 into the full M1 checkup."""
import csv,glob,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
rows=[]
for r in csv.DictReader(open(ROOT/'runs/v6/m1/checkup_all.csv')):
 if r['source']=='v3': rows.append(r)
for r in csv.DictReader(open(ROOT/'runs/v5/c3/checkup.csv')):
 if not r.get('rear_err_m'): continue
 rows.append({'source':'WP3yaw0','state':r['rock'],'candidate':r['task'],'admitted':r['admitted']=='True','rear_err_m':r['rear_err_m'],'top_err_m':r['top_err_m'],'path_p95_mm':r['path_p95_mm'],'hidden_iou':'','scale_ratio':r['scale_ratio'],'hidden_frac':r['hidden_frac'],'shell_contact':r['shell_contact'],'free_intrusion_frac':r['free_intrusion_frac'],'contour_iou':r['contour_iou']})
for p in glob.glob(str(ROOT/'runs/v6/m1/views/*/checkup.csv')):
 for r in csv.DictReader(open(p)):
  rows.append({'source':'WP3pm25','state':r['rock'],'candidate':r['task'],'admitted':r['admitted']=='True','rear_err_m':r['rear_err_m'],'top_err_m':r['top_err_m'],'path_p95_mm':r['path_p95_mm'],'hidden_iou':r['hidden_iou'],'scale_ratio':r['scale_ratio'],'hidden_frac':r['hidden_frac'],'shell_contact':r['shell_contact'],'free_intrusion_frac':r['free_intrusion_frac'],'contour_iou':r['contour_iou']})
fields=list(rows[0].keys())
with (ROOT/'runs/v6/m1/checkup_all.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
print('total',len(rows),'v3',sum(r['source']=='v3' for r in rows),'yaw0',sum(r['source']=='WP3yaw0' for r in rows),'pm25',sum(r['source']=='WP3pm25' for r in rows))
