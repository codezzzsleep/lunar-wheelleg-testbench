"""R1: recoded confusion semantics (positive=bad, predicted positive=rejected)."""
import csv,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
rows=list(csv.DictReader(open(ROOT/'runs/v6/m1/checkup_all.csv')))
def metrics(rs):
 out={}
 for r in rs:
  if r['rear_err_m'] in ('','None') or not r['path_p95_mm']: continue
  rear=float(r['rear_err_m']); p95=float(r['path_p95_mm']); bad=abs(rear)>0.05 or p95>80; adm=r['admitted'] in ('True','true','1')
  out.setdefault('n',0); out['n']+=1
  key=('pass' if adm else 'reject')+('_bad' if bad else '_good'); out[key]=out.get(key,0)+1
 n=out['n']; bad=out.get('pass_bad',0)+out.get('reject_bad',0); good=n-bad
 return {'n':n,'pass_bad':out.get('pass_bad',0),'pass_good':out.get('pass_good',0),'reject_bad':out.get('reject_bad',0),'reject_good':out.get('reject_good',0),'bad_rejected':round(out.get('reject_bad',0)/bad,3) if bad else None,'good_kept':round(out.get('pass_good',0)/good,3) if good else None,'pass_bad_ratio':round(out.get('pass_bad',0)/max(1,out.get('pass_bad',0)+out.get('pass_good',0)),3),'reject_bad_ratio':round(out.get('reject_bad',0)/max(1,out.get('reject_bad',0)+out.get('reject_good',0)),3)}
val=[r for r in rows if r['source'] in ('v3','WP3yaw0')]
allr=rows
res={'validated_122':metrics(val),'all_206':metrics(allr),'reference_pm25':metrics([r for r in rows if r['source']=='WP3pm25'])}
(ROOT/'runs/v6/m1/semantics.json').write_text(json.dumps(res,indent=2)); print(json.dumps(res,indent=2))
