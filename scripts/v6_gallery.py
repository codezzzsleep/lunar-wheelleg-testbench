"""R2 1.5: export M1 gallery JSON for all candidates."""
import csv,glob,hashlib,json,pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent/'scripts'))
import v3_generate
ROOT=pathlib.Path(__file__).resolve().parent.parent
def sha(p):
 try: return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
 except Exception: return None
cfg=json.loads((ROOT/'configs/v5_admission.json').read_text())
entries=[]
# +/-25 from view checkups + reg align
for f in glob.glob(str(ROOT/'runs/v6/m1/views/*/checkup.csv')):
 view=pathlib.Path(f).parent.name; rock=view.rsplit('_yaw',1)[0]
 for r in csv.DictReader(open(f)):
  task=[t for t in json.loads((ROOT/'runs/v4/wp3/tasks.json').read_text())['tasks'] if t['id']==r['task']]
  if not task: continue
  ident=v3_generate.identity_of(task[0]); regd=pathlib.Path(f).parent/'reg'/ident/'align.json'
  if not regd.exists(): continue
  M=json.loads(regd.read_text())['best']['M']; obs=pathlib.Path(f).parent/'observation'
  img=ROOT/task[0]['image']
  rec={'source':'WP3pm25','rock':rock,'view':view.rsplit('_yaw',1)[1],'candidate':ident,'validated':False,
   'glb':{'path':str((ROOT/'runs/v3/generation/cache'/ident/'model.glb').relative_to(ROOT)),'sha256':sha(ROOT/'runs/v3/generation/cache'/ident/'model.glb')},
   'input_image':{'path':str(img.relative_to(ROOT)) if img else None,'sha256':sha(img) if img else None},
   'observation':{'rgb':str((obs/'rgb.png').relative_to(ROOT)),'depth':str((obs/'depth.npy').relative_to(ROOT)),'mask':str((obs/'mask.png').relative_to(ROOT)),'camera':str((obs/'camera.json').relative_to(ROOT))},
   'M_world':M,'admission':{'scale_ratio':float(r['scale_ratio']),'contour_iou':float(r['contour_iou']),'shell_contact':float(r['shell_contact']),'hidden_frac':float(r['hidden_frac']),'free_intrusion_frac':float(r['free_intrusion_frac']),'thresholds':cfg,'admitted':r['admitted']=='True'},
   'hidden_metrics':{'rear_err_m':float(r['rear_err_m']) if r['rear_err_m'] else None,'top_err_m':float(r['top_err_m']) if r['top_err_m'] else None,'path_p95_mm':float(r['path_p95_mm']) if r['path_p95_mm'] else None,'hidden_iou':float(r['hidden_iou']) if r.get('hidden_iou') else None},
   'truth':{'asset':f'assets/v3/rocks/{rock}/h1/body_vis.obj','pose':None,'scale':None,'texture':'none'}}
  out=ROOT/'runs/v6/gallery'/'WP3pm25'/view/f'{ident[:16]}.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(rec,indent=2)); entries.append(str(out.relative_to(ROOT)))
(ROOT/'runs/v6/gallery').mkdir(parents=True,exist_ok=True)
(ROOT/'runs/v6/gallery/index.json').write_text(json.dumps({'schema':'v6-gallery-index/v1','count':len(entries),'entries':entries},indent=2))
print('entries',len(entries))
