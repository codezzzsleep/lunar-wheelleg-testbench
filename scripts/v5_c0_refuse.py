"""C0: recompute v3 FULL P∩U with column_fill_top vs old parity fill."""
import csv,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import v5_core as C,v5_metrics_ref as R
def main():
 rows=[]
 for d in sorted((ROOT/'runs/v3/states').iterdir()):
  dec=d/'decision'/'execution_FULL.json'
  if not dec.exists(): continue
  V=np.load(d/'fusion/V.npz'); g=C.grid_from_V(V); U=(V['space']==0); Vsh=V['shell']
  for cand in sorted((d/'candidates').glob('*')):
   mesh_p=cand/'parent_world'/'body.stl'; full_p=cand/'fused'/'occ_full.npz'
   if not mesh_p.exists() or not full_p.exists(): continue
   old=np.load(full_p)['occupied']
   old_PU=int((old&U&~Vsh).sum())
   mesh=trimesh.load(str(mesh_p),force='mesh',process=False)
   newP=R.column_fill_top(mesh,g); new_PU=int((newP&U).sum())
   T=np.load(d/'fusion'/'V.npz') if False else None
   tm=trimesh.load(str(d/'truth'/'body_world.stl'),force='mesh',process=False); Tp=R.column_fill_top(tm,g)
   Ht=Tp&U; Ho=(old&U); Hn=(newP&U)
   iou_old=float((Ho&Ht).sum())/max(1,int((Ho|Ht).sum())); iou_new=float((Hn&Ht).sum())/max(1,int((Hn|Ht).sum()))
   rows.append({'state':d.name,'candidate':cand.name,'old_PU':old_PU,'new_PU':new_PU,'ratio':round(new_PU/max(old_PU,1),3),
                'hidden_iou_old':round(iou_old,4),'hidden_iou_new':round(iou_new,4)})
   print(json.dumps(rows[-1]),flush=True)
 out=ROOT/'runs/v5/c0'; out.mkdir(parents=True,exist_ok=True)
 with (out/'v3_refuse.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
 print('states',len({r['state'] for r in rows}),'rows',len(rows))
if __name__=='__main__': main()
