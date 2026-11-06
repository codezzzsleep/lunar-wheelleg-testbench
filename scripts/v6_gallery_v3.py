import csv,hashlib,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
def sha(p):
 try: return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
 except Exception: return None
cfg=json.loads((ROOT/'configs/v5_admission.json').read_text()); n=0
for r in csv.DictReader(open(ROOT/'runs/v6/m1/checkup_all.csv')):
 if r['source']!='v3': continue
 st=r['state']; cand=r['candidate']; cd=ROOT/'runs/v3/states'/st/'candidates'/cand
 if not (cd/'align.json').exists(): continue
 cj=json.loads((cd/'candidate.json').read_text()); aj=json.loads((cd/'align.json').read_text()); M=aj.get('M') or aj['best']['M']; ident=cj['identity']
 meta=ROOT/'runs/v3/generation/cache'/ident/'meta.json'; img=None; ish=cj.get('input_shas',[None])[0]
 if meta.exists():
  mi=json.loads(meta.read_text()).get('image')
  if mi: img=pathlib.Path(str(mi).replace('/workspace/lunar-lab',str(ROOT)))
 spec=json.loads((ROOT/'runs/v3/states'/st/'scene_spec.json').read_text()); obj=(spec.get('objects') or [{}])[0]
 rock=st.rsplit('_h',1)[0]
 rec={'source':'v3','rock':rock,'state':st,'candidate':cand,'validated':True,
  'glb':{'path':str((ROOT/'runs/v3/generation/cache'/ident/'model.glb').relative_to(ROOT)),'sha256':sha(ROOT/'runs/v3/generation/cache'/ident/'model.glb')},
  'input_image':{'path':str(img.relative_to(ROOT)) if img and img.exists() else None,'sha256':sha(img) if img and img.exists() else ish},
  'observation':{'rgb':str((ROOT/'runs/v3/states'/st/'observation'/'rgb.png').relative_to(ROOT)),'depth':str((ROOT/'runs/v3/states'/st/'observation'/'depth.npy').relative_to(ROOT)),'mask':str((ROOT/'runs/v3/states'/st/'observation'/'mask.png').relative_to(ROOT)),'camera':str((ROOT/'runs/v3/states'/st/'observation'/'observation.json').relative_to(ROOT))},
  'M_world':M,'admission':{'scale_ratio':float(r['scale_ratio']),'contour_iou':float(r['contour_iou']),'shell_contact':float(r['shell_contact']),'hidden_frac':float(r['hidden_frac']),'free_intrusion_frac':float(r['free_intrusion_frac']),'thresholds':cfg,'admitted':r['admitted']=='True'},
  'hidden_metrics':{'rear_err_m':float(r['rear_err_m']) if r['rear_err_m'] else None,'top_err_m':float(r['top_err_m']) if r['top_err_m'] else None,'path_p95_mm':float(r['path_p95_mm']) if r['path_p95_mm'] else None,'hidden_iou':float(r['hidden_iou']) if r.get('hidden_iou') else None},
  'truth':{'asset':str(obj.get('mesh_file','')).replace('/workspace/lunar-lab',''),'pose':{'x':obj.get('x'),'y':obj.get('y'),'yaw_deg':obj.get('yaw_deg')},'scale':obj.get('target_height_m'),'texture':'none'}}
 out=ROOT/'runs/v6/gallery/v3'/st/f'{cand}.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(rec,indent=2)); n+=1
print('v3 entries',n)
