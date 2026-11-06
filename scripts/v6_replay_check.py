"""V6 §4 replay check: manifest sha, rebuild model, replay qpos with mj_forward, render 3 frames."""
import hashlib,json,pathlib,sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def main(pkg):
 import mujoco, wheelleg_env, terrain
 pkg=pathlib.Path(pkg).resolve(); (pkg/'check').mkdir(parents=True,exist_ok=True); res={'package':str(pkg),'ok':False,'errors':[]}
 man=json.loads((pkg/'manifest.json').read_text())
 bad=[e['path'] for e in man['files'] if not (pkg/e['path']).exists() or sha(pkg/e['path'])!=e['sha256']]
 res['sha_bad']=bad
 import os
 spec=json.loads((pkg/'scene'/'scene_spec.json').read_text())
 cwd=os.getcwd(); os.chdir(pkg)
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0)
 trajs=sorted((pkg/'runs').glob('*/traj.npz'))
 if not trajs: res['errors'].append('no traj.npz'); (pkg/'check'/'replay_check.json').write_text(json.dumps(res,indent=2)); print(json.dumps(res)); return
 z=np.load(trajs[0]); qpos=np.asarray(z['qpos']); m=env.model; d=env.data
 pen=0.0
 for q in qpos:
  d.qpos[:]=q; mujoco.mj_forward(m,d)
  for c in d.contact[:d.ncon]:
   dist=float(c.dist)
   if dist<0: pen=max(pen,-dist)
 res['frames']=int(len(qpos)); res['max_penetration_mm']=round(pen*1000,3)
 res['penetration_ok']=bool(pen<=0.005)
 res['end_qpos_match']=bool(np.allclose(qpos[-1],z['qpos'][-1]))
 # render 3 frames
 import os; os.environ.setdefault('MUJOCO_GL','egl')
 from PIL import Image
 try:
  r=mujoco.Renderer(m,480,640); ck=pkg/'check'; ck.mkdir(exist_ok=True)
  for tag,idx in (('first',0),('mid',len(qpos)//2),('last',len(qpos)-1)):
   d.qpos[:]=qpos[idx]; mujoco.mj_forward(m,d); r.update_scene(d); Image.fromarray(r.render()).save(ck/f'{tag}.png')
  r.close(); res['render']=True
 except Exception as e: res['render']=False; res['render_error']=str(e)[:200]
 res['ok']=bool(not bad and res.get('penetration_ok') and res.get('render'))
 os.chdir(cwd)
 (pkg/'check'/'replay_check.json').write_text(json.dumps(res,indent=2)); print(json.dumps(res,indent=2))
if __name__=='__main__': main(sys.argv[1])
