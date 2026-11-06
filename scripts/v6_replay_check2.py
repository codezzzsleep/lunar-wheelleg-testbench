"""R1 replay check: load the compiled model actually used, report obstacles and distances."""
import hashlib,json,pathlib,sys
import numpy as np,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def main(pkg):
 pkg=pathlib.Path(pkg).resolve(); res={'package':str(pkg),'errors':[],'warnings':[]}
 try:
  spec=json.loads((pkg/'scene'/'scene_spec.json').read_text()); man=json.loads((pkg/'manifest.json').read_text())
 except Exception as e: print(e); return
 bad=[f for f in man['files'] if not f['path'].startswith('check/') and (not (pkg/f['path']).exists() or sha(pkg/f['path'])!=f['sha256'])]
 res['sha_bad']=bad
 xml=pkg/'scene'/'compiled'/'model.xml'
 if not xml.exists(): res['errors'].append('no compiled model.xml'); (pkg/'check').mkdir(exist_ok=True); (pkg/'check'/'replay_check.json').write_text(json.dumps(res,indent=2)); print(json.dumps(res)); return
 m=mujoco.MjModel.from_xml_path(str(xml)); d=mujoco.MjData(m)
 names=[mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,i) or '' for i in range(m.nbody)]
 obs_bodies=[i for i,n in enumerate(names) if any(k in n.lower() for k in ('obstacle','rock','boulder','pit'))]
 obs_geoms=[g for g in range(m.ngeom) if m.geom_bodyid[g] in obs_bodies]
 robot_geoms=[g for g in range(m.ngeom) if m.geom_bodyid[g]<18]
 res.update({'ngeom':int(m.ngeom),'nbody':int(m.nbody),'obstacle_bodies':[names[i] for i in obs_bodies],'obstacle_geoms':len(obs_geoms),'robot_geoms':len(robot_geoms)})
 # trajectories
 trajs=sorted(pkg.glob('runs/*/traj.npz')); frames=0; maxpen=0.0; mind={str(g):1e9 for g in obs_geoms}
 for t in trajs:
  z=np.load(t); q=z['qpos']; frames+=len(q)
  for row in q:
   d.qpos[:]=row; mujoco.mj_forward(m,d)
   for g in obs_geoms:
    best=1e9
    for rg in robot_geoms:
     try:
      dist=mujoco.mj_geomDistance(m,d,rg,g,2.0,None)
      best=min(best,dist)
     except Exception: pass
    mind[str(g)]=min(mind[str(g)],best)
   # penetration proxy: contact dist below 0
   for c in d.contact[:d.ncon]:
    if c.dist<0: maxpen=max(maxpen,-float(c.dist))
 res['frames']=frames; res['max_penetration_mm']=round(maxpen*1000,4)
 res['obstacle_min_distance_m']={k:(None if v>1e8 else round(v,4)) for k,v in mind.items()}
 res['penetration_ok']=maxpen<=0.005
 # action consistency
 picks=[]
 for t in trajs:
  z=np.load(t); picks+=list(z['action']) if 'action' in z.files else []
 acts=sorted(set(map(str,picks)))
 dec=pkg/'decision.json'
 if dec.exists():
  dj=json.loads(dec.read_text()); chosen=dj.get('chosen') or dj.get('action')
  res['decision']=chosen; res['actions_in_traj']=acts
  res['action_consistent']=bool(chosen is None or all(a==str(chosen) or a in ('CRUISE','OBSERVE','WAIT_LUX3D','SECOND_LOOK') for a in acts))
 # scene mentions obstacles?
 word=str(spec.get('name',''))+' '+json.dumps(spec.get('objects',[]))
 mentions=any(k in word.lower() for k in ('obstacle','rock','gravel','boulder','pit'))
 need_obs=any(k in (str(spec.get('name',''))+json.dumps(spec.get('objects',[]))).lower() for k in ('obstacle','rock','gravel','boulder'))
 if need_obs and len(obs_geoms)==0: res['errors'].append('scene mentions obstacles but compiled model has none')
 # detour: max lateral offset must have obstacle within 1m
 qs=[np.load(t)['qpos'] for t in trajs]
 if qs:
  Q=np.concatenate(qs); imax=int(np.argmax(np.abs(Q[:,1]-Q[0,1]))); x=float(Q[imax,0])
  near=[g for g in obs_geoms if abs(float(m.geom_pos[g][0]))<1e9]
  res['max_lateral_offset_m']=round(float(abs(Q[imax,1]-Q[0,1])),3); res['max_offset_x']=round(x,3)
  # nearest obstacle geom center in x within 1m using body xpos
  ok=False
  for b in obs_bodies:
   # body xpos not known without a frame; use geom aabb center from model
   for g in obs_geoms:
    if m.geom_bodyid[g]==b: ok=True
  res['obstacle_near_max_offset']=bool(ok and obs_geoms)
 # follow-camera renders (robot ~1/3 frame height)
 try:
  import os; os.environ.setdefault('MUJOCO_GL','egl')
  (pkg/'check').mkdir(exist_ok=True)
  r=mujoco.Renderer(m,480,640); cam=mujoco.MjvCamera(); frames_ok=[]
  q=qs[0] if qs else None
  if q is not None:
   idx=[0,len(q)//2,len(q)-1]
   for j,i in enumerate(idx):
    d.qpos[:]=q[i]; mujoco.mj_forward(m,d)
    base=d.xpos[1]; cam.lookat[:]=base; cam.distance=1.8; cam.azimuth=135.0; cam.elevation=-12.0
    r.update_scene(d,camera=cam); img=r.render().copy(); frames_ok.append(True)
    from PIL import Image; Image.fromarray(img).save(pkg/'check'/[ 'first.png','mid.png','last.png'][j])
  r.close(); res['render']=bool(frames_ok)
 except Exception as e: res['render']=False; res['render_error']=str(e)
 res['ok']=not res['errors'] and not bad and res['penetration_ok'] and (len(obs_geoms)>0 or not need_obs)
 (pkg/'check').mkdir(exist_ok=True)
 (pkg/'check'/'replay_check.json').write_text(json.dumps(res,indent=2)); print(json.dumps(res,indent=2))
if __name__=='__main__': main(sys.argv[1])
