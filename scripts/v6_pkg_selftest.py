"""Build a tiny synthetic package to exercise v6_replay_check (no showcase claim)."""
import json,pathlib,sys,hashlib
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,terrain
spec=json.loads((ROOT/'runs/v4/wp7/A1_cruise_10m/scene.json').read_text())
out=ROOT/'runs/v6/m4/selftest'; (out/'scene').mkdir(parents=True,exist_ok=True)
(out/'scene'/'scene_spec.json').write_text(json.dumps(spec,indent=2))
env=wheelleg_env.WheelLegEnv(spec,max_seconds=120); env.reset(seed=0)
qs=[]
for i in range(120):
 env.step(np.zeros(3)); qs.append(np.asarray(env.data.qpos,float).copy())
(out/'runs'/'selftest').mkdir(parents=True,exist_ok=True)
np.savez(out/'runs'/'selftest'/'traj.npz',t=np.arange(len(qs))*0.02,qpos=np.array(qs),qvel=np.zeros((len(qs),env.model.nv)))
(out/'robot').mkdir(exist_ok=True); (out/'robot'/'model_ref.json').write_text(json.dumps({'mjcf':'vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml'}))
files=[]
for p in sorted(out.rglob('*')):
 if p.is_file() and p.name!='manifest.json':
  h=hashlib.sha256(p.read_bytes()).hexdigest(); files.append({'path':str(p.relative_to(out)),'sha256':h,'bytes':p.stat().st_size})
(out/'manifest.json').write_text(json.dumps({'files':files},indent=2)); print(out)
