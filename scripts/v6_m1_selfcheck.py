"""M1 self-check statistics on the merged checkup (v3 75 + WP3 yaw0 47)."""
import csv,json,pathlib,statistics
from scipy.stats import spearmanr
ROOT=pathlib.Path(__file__).resolve().parent.parent
rows=[r for r in csv.DictReader(open(ROOT/'runs/v6/m1/checkup_all.csv')) if r['rear_err_m'] and r['path_p95_mm']]
for r in rows:
 r['rear']=float(r['rear_err_m']); r['p95']=float(r['path_p95_mm']); r['adm']=r['admitted']=='True'
 r['bad']=abs(r['rear'])>0.05 or r['p95']>80
def med(xs): return round(statistics.median(xs),3) if xs else None
def q(xs):
 import numpy as np
 return {k:round(float(np.percentile(xs,k)),3) for k in (10,25,75,90)} if xs else {}
out={'n':len(rows),'n_admitted':sum(r['adm'] for r in rows),'n_bad':sum(r['bad'] for r in rows)}
out['pass_group']={'n':sum(r['adm'] for r in rows),'rear_median':med([r['rear'] for r in rows if r['adm']]),'p95_median':med([r['p95'] for r in rows if r['adm']]),'rear_q':q([r['rear'] for r in rows if r['adm']]),'p95_q':q([r['p95'] for r in rows if r['adm']])}
out['reject_group']={'n':sum(not r['adm'] for r in rows),'rear_median':med([r['rear'] for r in rows if not r['adm']]),'p95_median':med([r['p95'] for r in rows if not r['adm']]),'rear_q':q([r['rear'] for r in rows if not r['adm']]),'p95_q':q([r['p95'] for r in rows if not r['adm']])}
tp=sum(r['adm'] and r['bad'] for r in rows); fp=sum(r['adm'] and not r['bad'] for r in rows)
fn=sum((not r['adm']) and r['bad'] for r in rows); tn=sum((not r['adm']) and not r['bad'] for r in rows)
out['confusion']={'tp':tp,'fp':fp,'fn':fn,'tn':tn,'sensitivity':round(tp/max(1,tp+fn),3),'specificity':round(tn/max(1,tn+fp),3),'precision':round(tp/max(1,tp+fp),3)}
metrics=['scale_ratio','hidden_frac','shell_contact','free_intrusion_frac','contour_iou']
corr={}
for m in metrics:
 xs=[float(r[m]) for r in rows if r[m]]; ys=[abs(r['rear']) for r in rows if r[m]]
 if len(xs)>5: corr[m]=round(float(spearmanr(xs,ys).statistic),3)
out['spearman_abs_rear']=corr
by={}
for r in rows:
 rock=r['state'].split('_yaw')[0]
 if rock.startswith('v4_'): rock=rock[3:].rsplit('_yaw',1)[0]
 by.setdefault(rock,[]).append(r)
out['by_rock']={k:{'n':len(v),'adm':sum(x['adm'] for x in v),'bad':sum(x['bad'] for x in v),'rear_median':med([x['rear'] for x in v])} for k,v in sorted(by.items())}
p=ROOT/'runs/v6/m1/selfcheck.json'; p.write_text(json.dumps(out,ensure_ascii=False,indent=2)); print(json.dumps(out,ensure_ascii=False,indent=1))
