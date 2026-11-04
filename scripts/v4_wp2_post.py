"""Recompute WP2 cost fields from execution records (energy, contacts)."""
import json,pathlib,sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import stage6_matrix as S6M
def metrics(rdir):
    rdir=pathlib.Path(rdir); chunks=sorted(rdir.glob('chunk_*.npz'))
    if not chunks: return {}
    t=np.concatenate([np.load(c)['t'] for c in chunks]); q=np.concatenate([np.load(c)['qpos'] for c in chunks])
    qv=np.concatenate([np.load(c)['qvel'] for c in chunks])
    dist=float(np.trapezoid(np.abs(qv[:,0]),t)) if len(t)>1 else 0.0
    e=None
    try:
        tl=np.concatenate([np.load(c)['joint_torque'] for c in chunks]); tw=np.concatenate([np.load(c)['wheel_torque'][:,-4:] for c in chunks])
        pwr=np.abs(np.nansum(tl*qv[:,6:18],axis=1))+np.abs(np.nansum(tw*qv[:,18:22],axis=1))
        v=float(np.trapezoid(pwr,t)); e=round(v,3) if np.isfinite(v) and v>0 else None
    except Exception: e=None
    slow=(np.abs(qv[:,0])<0.02).astype(int); ev=0; run=0
    for x in slow:
        if x: run+=1
        else:
            if run*0.02>=0.5: ev+=1
            run=0
    if run*0.02>=0.5: ev+=1
    return {'distance_m':round(dist,4),'energy_J':e,'stops':ev}
def contacts(rdir):
    try:
        tref={'trajectory_path':str(pathlib.Path(rdir)/'index.json')}
        return int(S6M.chassis_contacts_from_record(tref))
    except Exception: return None
def main():
    out=ROOT/'runs/v4/wp2'; p=out/'confirm_table.json'; rows=json.loads(p.read_text())
    for r in rows:
        rd=out/'exec'/'record'/f"{r['scene']}_{r['arm']}"
        r.update({k:v for k,v in metrics(rd).items() if v is not None})
        c=contacts(rd); r['chassis_contacts']=c
        r['safe_pass']=bool(r.get('outcome')=='pass' and c==0)
        r['reached']=bool(r.get('outcome')=='pass')
    p.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    import csv
    with (out/'confirm_table.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(json.dumps({'rows':len(rows),'pass':sum(r['outcome']=='pass' for r in rows),'contacts0':sum(r['chassis_contacts']==0 for r in rows)},ensure_ascii=False))
if __name__=='__main__': main()
