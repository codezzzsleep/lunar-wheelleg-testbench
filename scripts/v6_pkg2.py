"""Rebuild a showcase package with the compiled MuJoCo model used in simulation."""
import hashlib,json,os,pathlib,re,shutil,sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import mujoco
import wheelleg_env
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def build(src,name,out=None):
 src=pathlib.Path(src); pkg=pathlib.Path(out or (ROOT/'runs/v6/m4/units'/name)); (pkg/'scene').mkdir(parents=True,exist_ok=True); (pkg/'robot').mkdir(exist_ok=True)
 spec=json.loads((src/'scene.json').read_text())
 objs=[]
 for i,o in enumerate(spec.get('objects') or []):
  pd=str(o.get('posed_dir') or '').replace('/workspace/work/lunar-lab',str(ROOT)).replace('/workspace/lunar-lab',str(ROOT))
  if not pd: continue
  pp=pathlib.Path(pd)
  if not pp.exists(): pp=(src/'coll') if pp.name=='coll' else (src/'coll'/pp.name)
  pd=str(pp)
  dst=pkg/'scene'/'objects'/f'obj_{i}'; dst.mkdir(parents=True,exist_ok=True)
  for f in pathlib.Path(pd).iterdir():
   if f.is_file(): shutil.copy2(f,dst/f.name)
  objs.append({'posed_dir':f'scene/objects/obj_{i}'})
 spec['objects']=objs
 (pkg/'scene'/'scene_spec.json').write_text(json.dumps(spec,indent=2))
 for sub in ('assets','coll'):
  if (src/sub).exists(): shutil.copytree(src/sub,pkg/'scene'/sub,dirs_exist_ok=True)
 (pkg/'robot'/'model_ref.json').write_text(json.dumps({'mjcf':'vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml'}))
 cwd=os.getcwd(); os.chdir(pkg)
 try:
  env=wheelleg_env.WheelLegEnv(json.loads((pkg/'scene'/'scene_spec.json').read_text()),max_seconds=5)
  (pkg/'scene'/'compiled').mkdir(parents=True,exist_ok=True)
  mujoco.mj_saveLastXML(str(pkg/'scene'/'compiled'/'model.xml'),env.model)
  xml=(pkg/'scene'/'compiled'/'model.xml').read_text()
 finally: os.chdir(cwd)
 (pkg/'scene'/'compiled').mkdir(parents=True,exist_ok=True)
 md=re.search(r'meshdir="([^"]+)"',xml)
 if md:
  mdd=pathlib.Path(md.group(1))
  if mdd.exists():
   dest=pkg/'scene'/'compiled'/'assets'; dest.mkdir(parents=True,exist_ok=True)
   for f in mdd.iterdir():
    if f.is_file(): shutil.copy2(f,dest/f.name)
  xml=xml.replace(md.group(0),'meshdir="assets"')
 if 'texturedir=' in xml: xml=re.sub(r'texturedir="[^"]*"','texturedir="assets"',xml)
 xml=xml.replace('file="assets/','file="')
 # copy every absolute file referenced by xml into compiled/assets and relativize
 paths=set(re.findall(r'(?:file|filename)="([^"]+)"',xml))
 for p in list(paths):
  if p.startswith('/'):
   q=pathlib.Path(p)
   if q.exists():
    dst=pkg/'scene'/'compiled'/'assets'/q.name; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(q,dst); xml=xml.replace(p,q.name)
 (pkg/'scene'/'compiled'/'model.xml').write_text(xml)
 print(pkg,'objects',len(objs),'xml_bytes',len(xml))
 return pkg
if __name__=='__main__':
 for s in sys.argv[1:]: build(s,pathlib.Path(s).name)
