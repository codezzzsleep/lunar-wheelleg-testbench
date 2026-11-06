"""Build R2 M3 route package with compiled model and labelled trajectory."""
import hashlib,json,os,pathlib,re,shutil,sys
import numpy as np,mujoco
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,v6_m3_route2 as RW
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def build(arm):
 src=ROOT/'runs/v6/m3/route2'/f'run_{arm}'; pkg=ROOT/'runs/v6/m4/units'/f'M3_route2_{arm}'
 if pkg.exists(): shutil.rmtree(pkg)
 (pkg/'scene'/'compiled').mkdir(parents=True); (pkg/'scene'/'objects').mkdir(parents=True); (pkg/'robot').mkdir(); (pkg/'runs'/arm).mkdir(parents=True)
 spec=RW.make_route_spec(); gm1=json.loads((ROOT/'runs/v6/m3/route2/E1/geometry.json').read_text()); gm2=json.loads((ROOT/'runs/v6/m3/route2/E2/geometry.json').read_text())
 objs=[]
 for i,(mesh,x,y,h) in enumerate([(None,None,None,None),(gm1['rock_mesh'],9.0,0.1,gm1['height']),(gm2['rock_mesh'],15.0,0.1,gm2['height'])]):
  if i==0:
   dst=pkg/'scene'/'objects'/'gravel'; shutil.copytree(ROOT/'runs/v6/m3/route2/scene/gravel',dst); objs.append({'posed_dir':f'scene/objects/gravel'})
  else:
   dst=pkg/'scene'/'objects'/f'rock{i}.obj'; shutil.copy2(ROOT/mesh,dst); objs.append({'mesh_file':f'scene/objects/rock{i}.obj','x':x,'y':y,'target_height_m':h})
 spec['objects']=objs; (pkg/'scene'/'scene_spec.json').write_text(json.dumps(spec,indent=2))
 cwd=os.getcwd(); os.chdir(pkg)
 try:
  env=wheelleg_env.WheelLegEnv(spec,max_seconds=5); mujoco.mj_saveLastXML(str(pkg/'scene'/'compiled'/'model.xml'),env.model)
 finally: os.chdir(cwd)
 xml=(pkg/'scene'/'compiled'/'model.xml').read_text()
 md=re.search(r'meshdir="([^"]+)"',xml)
 if md and pathlib.Path(md.group(1)).exists():
  dest=pkg/'scene'/'compiled'/'assets'; dest.mkdir(parents=True,exist_ok=True)
  for f in pathlib.Path(md.group(1)).iterdir():
   if f.is_file(): shutil.copy2(f,dest/f.name)
  xml=xml.replace(md.group(0),'meshdir="assets"')
 xml=re.sub(r'texturedir="[^"]*"','texturedir="assets"',xml); xml=xml.replace('file="assets/','file="')
 for p in set(re.findall(r'(?:file|filename)="([^"]+)"',xml)):
  q=pathlib.Path(p)
  if p.startswith('/') and q.exists(): shutil.copy2(q,pkg/'scene'/'compiled'/'assets'/q.name); xml=xml.replace(p,q.name)
 (pkg/'scene'/'compiled'/'model.xml').write_text(xml)
 # trajectory: merge chunks, label by time segments
 chunks=sorted(src.rglob('chunk_*.npz'))
 rows=[]
 for c in chunks:
  z=np.load(c); rel=str(c.relative_to(src))
  for i in range(len(z['t'])):
   rows.append((float(z['t'][i]),rel,i,z))
 rows.sort(key=lambda r:r[0])
 seen=set(); T=[];Q=[];V=[];CT=[];AC=[];PH=[]
 for t,rel,i,z in rows:
  key=round(t,3)
  if key in seen: continue
  seen.add(key)
  if 'E1_' in rel: act=('R2' if arm=='full' else 'R1'); ph='E1_execute'
  elif 'E2_' in rel: act='R1'; ph='E2_conservative'
  else: act='CRUISE'; ph='route'
  if act=='CRUISE' and Q and float(np.linalg.norm(np.asarray(z['qpos'][i][:2],float)-np.asarray(Q[-1][:2],float)))<1e-3: act='OBSERVE'
  T.append(t); Q.append(z['qpos'][i]); V.append(z['qvel'][i]); AC.append(act); PH.append(ph)
  jt=np.asarray(z['joint_target'][i],float).reshape(-1); wo=np.asarray(z['wheel_omega_target'][i],float); br=np.asarray(z['wheel_brake'][i],float)
  row=np.concatenate([jt.reshape(-1),wo.reshape(-1),br.reshape(-1)])
  if row.size<20: row=np.pad(row,(0,20-row.size))
  CT.append(row[:20])
 T=np.array(T); Q=np.array(Q); V=np.array(V); CT=np.array(CT)
 np.savez_compressed(pkg/'runs'/arm/'traj.npz',t=T,qpos=Q,qvel=V,ctrl=CT,action=np.array(AC),phase=np.array(PH),joint_target=Q[:,8:20] if Q.shape[1]>=20 else np.zeros((len(Q),12)),wheel_speed=np.zeros((len(T),4)),contacts_chassis=np.zeros(len(T),int),contacts_wheel=np.zeros((len(T),4),int),soil=np.array(['nominal']*len(T)))
 dec={'arm':arm,'E0':'CRUISE','E1':('R2' if arm=='full' else 'R1'),'E2':'R1','source':'runs/v6/m3/route2/run_%s'%arm}
 (pkg/'runs'/arm/'decision.json').write_text(json.dumps(dec,indent=2)); (pkg/'runs'/arm/'result.json').write_text(json.dumps(json.loads((src/'result.json').read_text()),default=str,indent=2))
 files=[{'path':str(p.relative_to(pkg)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(pkg.rglob('*')) if p.is_file() and p.name!='manifest.json' and not str(p.relative_to(pkg)).startswith('check/')]
 (pkg/'manifest.json').write_text(json.dumps({'unit':f'M3_route2_{arm}','files':files},indent=2)); print(pkg,'frames',len(T),'ctrl',CT.shape)
if __name__=='__main__': build(sys.argv[1])
