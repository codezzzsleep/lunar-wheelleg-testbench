"""Common evaluation: channel-aware 3/3 robust rehearsal, contacts, dual-geometry safety."""
import json,math,pathlib
import numpy as np,mujoco
import v3_core,wheelleg_env,stage8_matrix2 as M,stage6_matrix as S6M
ROOT=pathlib.Path(__file__).resolve().parent.parent
def scene_channel(spec): return float((spec.get('channel') or {}).get('half_width',0.45))

def plan_detour(occ, V, vis, channel, side=None, z_min=0.02):
    """按某臂自己的几何算绕行 offset_m 与 leave_x（R3 §3.1）。"""
    g_zs=np.asarray(V['origin'],float)[2]+(np.arange(int(V['dims'][2]))+0.5)*float(V['pitch'])
    above=g_zs[None,None,:]>z_min
    O=occ&above
    xf=float(vis['x_front'])
    gx=np.asarray(V['origin'],float)[0]+(np.arange(int(V['dims'][0]))+0.5)*float(V['pitch'])
    gy=np.asarray(V['origin'],float)[1]+(np.arange(int(V['dims'][1]))+0.5)*float(V['pitch'])
    if O.any():
        xs=gx[O.any(axis=(1,2))]; leave=float(xs.max())+0.25
    else:
        leave=xf+0.25
    band=(gx>=xf)&(gx<=leave)
    sub=O[band]
    if sub.any():
        yy=gy[sub.any(axis=(0,2))]
        if side is None or side>0: off=abs(float(yy.max()))+0.30
        else: off=abs(float(yy.min()))+0.30
    else:
        off=float(vis['W_vis'])/2.0+0.30
    return {'offset_m':round(off,4),'leave_x':round(leave,4),'side':side,
            'applicable':bool(off+0.20+0.05<=float(channel))}
def contact_of(path):
 p=pathlib.Path(path)
 if not p.is_absolute(): p=ROOT/p
 if p.name!='index.json': p=p/'index.json'
 try: return int(S6M.chassis_contacts_from_record({'trajectory_path':str(p)}))
 except Exception: return None
def perturb_snaps(env,snap,ref):
 out=[]
 for dx,dyaw in ((0.02,0.0),(-0.02,0.0),(0.0,2.0)):
  env.restore_state(snap,mode='project'); env.data.qpos[0]=ref[0][0]+dx; env.data.qvel[:]=ref[1]
  q=env.data.qpos[3:7].copy(); a=math.radians(dyaw)/2; dq=np.array([math.cos(a),0,0,math.sin(a)])
  w1,x1,y1,z1=q; w2,x2,y2,z2=dq
  env.data.qpos[3:7]=[w1*w2-x1*x2-y1*y2-z1*z2,w1*x2+x1*w2+y1*z2-z1*y2,w1*y2-x1*z2+y1*w2+z1*x2,w1*z2+x1*y2-y1*x2+z1*w2]
  mujoco.mj_forward(env.model,env.data); out.append(env.save_state())
 return out
def robust_arm(occ,V,snap,ref,visible,plan,actions,out,channel,tag='arm'):
 out=pathlib.Path(out); out.mkdir(parents=True,exist_ok=True)
 spec,env,sha=M.make_scene(M.resample_walls(occ,V['origin'],float(V['pitch'])),out,tag,channel_half=channel)
 s0h=snap.get('state_hash'); M.restore_common(env,snap,s0h,mode='project',ref=ref)
 snaps=perturb_snaps(env,snap,ref); runs=[]
 for si,s2 in enumerate(snaps):
  core={'spec':spec,'snapshot':s2,'visible':visible,'state':{'state_id':'r2','state_hash':s0h}}
  rr,_=v3_core.rehearse_on_spec(core,spec,s2,json.loads((ROOT/'plans/v3_protocol.json').read_text()),mode='same_scene',options=actions,body_plan=plan,budget=120.0,record_cells=True,record_root=out/f'p{si}')
  runs.append(rr)
 detail=[]; combined=[]; lat_max=0.0
 for act in actions:
  perms=[]; ok=True; costs=[]; ts=[]
  for si,rr in enumerate(runs):
   r=next((x for x in rr if x['action']==act),None)
   ent={'action':act,'perturb':si,'success':bool(r and r.get('success')),'reason':None if not r else r.get('reason'),'contacts':None,'cost':None if not r else r.get('cost'),'t_end':None if not r else r.get('t_end')}
   if r and r.get('trajectory_ref'):
    tp=r['trajectory_ref'].get('trajectory_path'); ent['contacts']=contact_of(tp); ent['record_path']=str(tp)
    try:
     import numpy as _np
     td=pathlib.Path(tp).parent if not str(tp).endswith('index.json') else pathlib.Path(tp).parent
     if not td.is_absolute(): td=ROOT/td
     ys=[]
     for ch in sorted(td.glob('chunk_*.npz')):
      z=_np.load(ch); ys.append(z['qpos'][:,1])
     if ys:
      ent['lat_max']=float(_np.abs(_np.concatenate(ys)).max()); lat_max=max(lat_max,ent['lat_max'])
    except Exception: pass
   if not ent['success'] or ent['contacts'] is None or (ent['contacts'] or 0)>0: ok=False
   if ent['cost'] is not None and ent['success'] and (ent['contacts'] or 0)==0: costs.append(ent['cost'])
   if ent['t_end'] is not None: ts.append(float(ent['t_end']))
   perms.append(ent)
  detail+=perms
  if any(e.get('lat_max',0.0)>float(channel)-0.05 for e in perms): ok=False
  combined.append({'action':act,'success':bool(ok),'cost':float(np.mean(costs)) if costs else 60.0,'candidate':tag,'reason':'3of3' if ok else 'failed','t_end':float(np.mean(ts)) if ts else 60.0,'final_x':None})
 safe={c['action'] for c in combined if c['success']}
 (out/'rehearsal_3of3.json').write_text(json.dumps({'arm':tag,'channel':channel,'entries':detail,'safe_actions':sorted(safe)},ensure_ascii=False,indent=2))
 return {'safe':safe,'combined':combined,'detail':detail,'plan':plan,'spec':spec,'snap':snap,'ref':ref,'lat_max':lat_max}
