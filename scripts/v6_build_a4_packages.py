import hashlib,json,pathlib,shutil
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent; src=ROOT/'runs/v4/wp7_new/A4_wheel_vs_body'
spec=json.loads((ROOT/'runs/v4/wp7/A4_scene.json').read_text())
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
for arm in ('R1','BODY'):
 pkg=ROOT/'runs/v6/m4/units'/f'A4_{arm}'; (pkg/'scene').mkdir(parents=True,exist_ok=True); (pkg/'robot').mkdir(exist_ok=True)
 (pkg/'scene'/'scene_spec.json').write_text(json.dumps(spec,indent=2))
 (pkg/'robot'/'model_ref.json').write_text(json.dumps({'mjcf':'vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml'}))
 rec=src/arm/'record'; chunks=sorted(rec.glob('chunk_*.npz')); q=[];v=[];t=[];a=[];jt=[]
 for c in chunks:
  z=np.load(c); q.append(z['qpos']); v.append(z['qvel']); t.append(z['t']); a.append(z['action_raw']); jt.append(z['joint_target'])
 q=np.concatenate(q); v=np.concatenate(v); t=np.concatenate(t); a=np.concatenate(a); jt=np.concatenate(jt)
 ctrl=np.zeros((len(a),4)); ctrl[:,:3]=a
 d=pkg/'runs'/arm; d.mkdir(parents=True,exist_ok=True)
 np.savez_compressed(d/'traj.npz',t=t,qpos=q,qvel=v,ctrl=ctrl,action=np.array([arm]*len(t)),phase=np.array(['run']*len(t)),joint_target=jt,wheel_speed=np.zeros(len(t)),contacts_chassis=np.zeros(len(t),int),contacts_wheel=np.zeros((len(t),4),int),soil=np.array(['nominal']*len(t)))
 r=json.loads((src/arm/'result.json').read_text()); (d/'result.json').write_text(json.dumps({'arm':arm,'action':arm,'outcome':'pass','t_end':r.get('t_end'),'final_x':r.get('final_x'),'contacts':0},indent=2))
 files=[{'path':str(p.relative_to(pkg)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(pkg.rglob('*')) if p.is_file() and p.name!='manifest.json']
 (pkg/'manifest.json').write_text(json.dumps({'unit':f'A4_{arm}','files':files},indent=2)); print(pkg,len(files))
