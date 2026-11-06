import concurrent.futures as cf,csv,hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v3_generate,v3_register
def sha(p):
 try: return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
 except Exception: return None
cfg=json.loads((ROOT/'configs/v5_admission.json').read_text()); proto=json.loads((ROOT/'plans/v3_protocol.json').read_text())
tasks={t['id']:t for t in json.loads((ROOT/'runs/v4/wp3/tasks.json').read_text())['tasks']}
rows=[r for r in csv.DictReader(open(ROOT/'runs/v6/m1/checkup_all.csv')) if r['source']=='WP3yaw0']
def work(r):
 t=tasks.get(r['candidate']);
 if not t: return None
 ident=v3_generate.identity_of(t); glb=ROOT/'runs/v3/generation/cache'/ident/'model.glb'; obs=ROOT/'runs/v6/m1/views'/f"{r['state']}_yaw+0"/'observation'
 if not glb.exists() or not (obs/'observation.json').exists(): return None
 rd=ROOT/'runs/v6/gallery/yaw0_reg'/ident; rd.mkdir(parents=True,exist_ok=True)
 if not (rd/'align.json').exists():
  try: rec=v3_register.register(str(glb),str(obs),proto,rd,top_k=6)
  except Exception: return None
 else: rec=json.loads((rd/'align.json').read_text())
 M=rec['best']['M']; img=ROOT/t['image']
 out=ROOT/'runs/v6/gallery/WP3yaw0'/r['state']/f'{ident[:16]}.json'; out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text(json.dumps({'source':'WP3yaw0','rock':r['state'],'view':'0','candidate':ident,'validated':True,
  'glb':{'path':str(glb.relative_to(ROOT)),'sha256':sha(glb)},
  'input_image':{'path':str(img.relative_to(ROOT)),'sha256':sha(img)},
  'observation':{'rgb':str((obs/'rgb.png').relative_to(ROOT)),'depth':str((obs/'depth.npy').relative_to(ROOT)),'mask':str((obs/'mask.png').relative_to(ROOT)),'camera':str((obs/'observation.json').relative_to(ROOT))},
  'M_world':M,'admission':{'scale_ratio':float(r['scale_ratio']),'contour_iou':float(r['contour_iou']),'shell_contact':float(r['shell_contact']),'hidden_frac':float(r['hidden_frac']),'free_intrusion_frac':float(r['free_intrusion_frac']),'thresholds':cfg,'admitted':r['admitted']=='True'},
  'hidden_metrics':{'rear_err_m':float(r['rear_err_m']) if r['rear_err_m'] else None,'top_err_m':float(r['top_err_m']) if r['top_err_m'] else None,'path_p95_mm':float(r['path_p95_mm']) if r['path_p95_mm'] else None},
  'truth':{'asset':f'assets/v3/rocks/{r["state"]}/h1/body_vis.obj','pose':None,'scale':None,'texture':'none'}},indent=2)); return str(out)
with cf.ProcessPoolExecutor(max_workers=4) as ex:
 res=[x for x in ex.map(work,rows) if x]
print('yaw0 entries',len(res))
