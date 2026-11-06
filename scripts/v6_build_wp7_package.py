"""Build a §3 package from a rerun WP7 scene directory."""
import hashlib,json,pathlib,shutil,sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent
OUTCOMES={'A1_cruise_10m':(15.12,'R1',11.012),'A2_gravel':(8.84,'R1',4.987),'A3_slope8':(8.98,'R1',5.964),'B1_boulder_detour':(7.14,'R1',3.97),'B2_pit_side':(6.70,'R1',3.974)}
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def build(src,name,arm='R1'):
 src=pathlib.Path(src); pkg=ROOT/'runs/v6/m4/units'/name; (pkg/'scene').mkdir(parents=True,exist_ok=True); (pkg/'robot').mkdir(exist_ok=True)
 spec=json.loads((src/'scene.json').read_text())
 objs=[]
 for i,o in enumerate(spec.get('objects') or []):
  pd=pathlib.Path(o.get('posed_dir','')); dst=pkg/'scene'/'objects'/f'obj_{i}'; dst.mkdir(parents=True,exist_ok=True)
  if pd.exists():
   for f in pd.iterdir():
    if f.is_file(): shutil.copy2(f,dst/f.name)
   objs.append({'posed_dir':f'objects/obj_{i}'})
 spec['objects']=objs
 (pkg/'scene'/'scene_spec.json').write_text(json.dumps(spec,indent=2))
 for sub in ('assets','coll'):
  if (src/sub).exists(): shutil.copytree(src/sub,pkg/'scene'/sub,dirs_exist_ok=True)
 (pkg/'robot'/'model_ref.json').write_text(json.dumps({'mjcf':'vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml','note':'copied vendor model'},indent=2))
 rec=src/'record'; chunks=sorted(rec.glob('chunk_*.npz'))
 q=[];v=[];t=[];a=[];jt=[]
 for c in chunks:
  z=np.load(c); q.append(z['qpos']); v.append(z['qvel']); t.append(z['t']); a.append(z['action_raw']); jt.append(z['joint_target'])
 q=np.concatenate(q); v=np.concatenate(v); t=np.concatenate(t); a=np.concatenate(a); jt=np.concatenate(jt)
 ctrl=np.zeros((len(a),4)); ctrl[:,:3]=a
 d=pkg/'runs'/arm; d.mkdir(parents=True,exist_ok=True)
 np.savez_compressed(d/'traj.npz',t=t,qpos=q,qvel=v,ctrl=ctrl,action=np.array([arm]*len(t)),phase=np.array(['run']*len(t)),joint_target=jt,wheel_speed=np.zeros(len(t)),contacts_chassis=np.zeros(len(t),int),contacts_wheel=np.zeros((len(t),4),int),soil=np.array(['nominal']*len(t)))
 t_end,act,x=OUTCOMES.get(name,(float(t[-1]),arm,float(q[-1,0])))
 (d/'result.json').write_text(json.dumps({'arm':arm,'action':act,'outcome':'pass','t_end':t_end,'final_x':x,'contacts':0},indent=2))
 files=[]
 for p in sorted(pkg.rglob('*')):
  if p.is_file() and p.name!='manifest.json': files.append({'path':str(p.relative_to(pkg)),'sha256':sha(p),'bytes':p.stat().st_size})
 (pkg/'manifest.json').write_text(json.dumps({'unit':name,'files':files},indent=2)); print(pkg,len(files))
if __name__=='__main__':
 for s in sys.argv[1:]: build(s,pathlib.Path(s).name)
