"""KA8: geometry-driven detour offsets on truth_v2."""
import json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R,v5_eval as E,v3_register
T=ROOT/'runs/v3/stage008/truth_v2'; V=np.load(T/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0)
tm=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False); Pt=R.column_fill_top(tm,g)
obs=v3_register.load_observation(str(T/'observation')); vis=C.visible_dims(T/'observation'); sh=C.shadow_mask(V,g,obs)
perfect=E.plan_detour(Pt,V,vis,1.2); solid=E.plan_detour(V['shell']|sh,V,vis,1.2)
# truth half width and U_shadow rear
xs=g['xs'][Pt.any(axis=(1,2))]; ys=g['ys'][Pt.any(axis=(0,2))]
truth_half=float(max(abs(ys.min()),abs(ys.max())))
rear_shadow=float(g['xs'][sh.any(axis=(1,2))].max()) if sh.any() else None
rear_u=float(g['xs'][((V['space']==0)).any(axis=(1,2))].max())
out={'visible':vis,'perfect_offset':perfect['offset_m'],'perfect_leave':perfect['leave_x'],
     'truth_half_width':round(truth_half,4),'expected_offset':round(truth_half+0.30,4),
     'obs_cons_offset':solid['offset_m'],'obs_cons_leave':solid['leave_x'],
     'u_shadow_rear':None if rear_shadow is None else round(rear_shadow,4),'u_rear':round(rear_u,4),
     'pass_offset':abs(perfect['offset_m']-(truth_half+0.30))<=0.03,
     'pass_leave':rear_shadow is not None and abs((solid['leave_x']-0.25)-rear_shadow)<=0.03}
out['pass']=bool(out['pass_offset'] and out['pass_leave'])
d=ROOT/'runs/v5/ka8'; d.mkdir(parents=True,exist_ok=True); (d/'ka8.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)); print(json.dumps(out,ensure_ascii=False,indent=1))
