"""M1 per-view KA: truth mesh reprojection IoU against the rendered view."""
import csv,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v3_register
STATES={'moon_rock_01':'moon_rock_01_h1v0','moon_rock_02':'moon_rock_02_h1v0','moon_rock_03':'moon_rock_03_h1v0','moon_rock_04':'moon_rock_04_h1v0','moon_rock_05':'moon_rock_05_h1v0','moon_rock_06':'moon_rock_06_h1v0','moon_rock_07':'moon_rock_07_h0v0','rock_07':'rock_07_h2v1'}
rows=[]
for rock,st in STATES.items():
 mp=ROOT/'runs/v3/states'/st/'truth/body_world.stl'
 if rock=='moon_rock_05': mp=ROOT/'runs/v3/stage008/truth_v2/truth/body_world.stl'
 mesh=trimesh.load(str(mp),force='mesh',process=False)
 for yaw in (25,-25):
  od=ROOT/'runs/v6/m1/views'/f'{rock}_yaw{yaw:+d}'/'observation'
  if not (od/'observation.json').exists(): continue
  obs=v3_register.load_observation(str(od)); ev=v3_register.evaluate_matrix(mesh,obs,np.eye(4))
  rows.append({'rock':rock,'view':yaw,'mask_iou':round(float(ev.get('mask_iou',0)),4),'depth_p50':round(float(ev.get('depth_p50',0)),5) if ev.get('depth_p50') is not None else '', 'ka6_pass':bool(ev.get('mask_iou',0)>=0.95)})
p=ROOT/'runs/v6/m1/view_ka.csv'
with p.open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('rows',len(rows),'pass',sum(r['ka6_pass'] for r in rows),'median_iou',np.median([r['mask_iou'] for r in rows]))
