"""Stage013 input-improvement batch: register + fuse the new GLBs (one case)."""
import hashlib, json, pathlib, sys, time
import numpy as np, trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_register, v3_fuse

def sha(p):
    h=hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()

def asset_mesh(glb):
    sc=trimesh.load(str(glb),force='scene'); parts=[]
    for name,g in sc.geometry.items():
        if not len(g.faces): continue
        T,_=sc.graph.get(name); gg=g.copy(); gg.apply_transform(T); parts.append(gg)
    return trimesh.util.concatenate(parts) if len(parts)>1 else parts[0].copy()

def main():
    out=ROOT/'runs/v3/stage013/input_batch'; reg=out/'registered'; fus=out/'fusion'
    reg.mkdir(parents=True,exist_ok=True); fus.mkdir(parents=True,exist_ok=True)
    truth=ROOT/'runs/v3/stage008/truth_v2'
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text())
    rows=[json.loads(l) for l in (ROOT/'runs/v3/generation/ledger.jsonl').read_text().splitlines() if l.strip()]
    tasks={r['id']:r for r in rows if str(r.get('id','')).startswith('stage013_') and r.get('event')=='downloaded'}
    rejected=[r for r in rows if str(r.get('id','')).startswith('stage013_') and r.get('event')=='rejected']
    rec={'schema':'stage013-batch/v1','run_id':'stage013-input-r1','generated_denominator':6,
         'submitted':6,'downloaded':len(tasks),'rejected':[{'id':r.get('id'),'reason':r.get('note') or r.get('reason')} for r in rejected],
         'diagnostic_assets':[],'candidates':{}}
    art=v3_fuse.write_v_artifact(truth,proto)
    fsum={'schema':'stage013-fusion/v1','truth':'runs/v3/stage008/truth_v2','v_sha':art['v_sha'],'v_stats':art['stats'],'candidates':{}}
    rears={}
    for tid,r in sorted(tasks.items()):
        glb=ROOT/'runs/v3/generation/cache'/r['identity']/'model.glb'
        d=reg/f'task_{tid}'; d.mkdir(parents=True,exist_ok=True)
        asset=asset_mesh(glb); asset.export(d/'asset.stl')
        a=v3_register.register(str(d/'asset.stl'),str(truth/'observation'),proto,d)
        M=np.asarray(a['M'],float); w=asset.copy(); w.apply_transform(M); w.export(d/'world.stl')
        dg=a['best']['diagnostics']
        rec['candidates'][tid]={'source_glb_sha256':sha(glb),'asset_sha256':sha(d/'asset.stl'),
                                'world_sha256':sha(d/'world.stl'),'diagnostics':dg,
                                'M':M.tolist(),'task_id':r.get('task_id')}
        man,stats=v3_fuse.fuse_parent(art,w,fus/f'task_{tid}',{'id':f'stage013_{tid}','mesh_sha256':sha(d/'world.stl')},proto)
        z=np.load(fus/f'task_{tid}'/'occ_full.npz'); full=z['occupied']; o=np.asarray(z['origin'],float); p=float(z['pitch'])
        xs=o[0]+(np.arange(full.shape[0])+0.5)*p; added=full&~art['shell']; ax=added.any(axis=(1,2))
        far=float(xs[ax].max()) if ax.any() else float(xs[full.any(axis=(1,2))].max()); rears[tid]=far
        fsum['candidates'][tid]={'full_sha':man['full_occ_sha'],'obs_sha':man['obs_only_occ_sha'],'stats':stats,'hidden_rear_x':round(far,4)}
        print(tid,'iou',dg['mask_iou'],'p95',dg['depth_p95_mm'],flush=True)
    first=sorted(tasks)[0]
    def pid(p): return hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:16]
    fp={'raise_z':0.06,'ramp_steps':100,'speed':0.15,'lower_at_x':round(rears[first]+0.10,4),
        'end_x':2.6,'stop_tilt_deg':12.0,'far_edge_source':f'stage013_{first}_hidden_rear'}
    op={'raise_z':0.06,'ramp_steps':100,'speed':0.15,'lower_at_x':2.45,'end_x':2.6,'stop_tilt_deg':12.0,'far_edge_source':'unknown_hold'}
    fsum['plans']={'full':dict(fp,plan_id=pid(fp)),'obs':dict(op,plan_id=pid(op))}
    fsum['plan_source_note']='fixed BODY plan from first downloaded input-batch candidate; never truth rear'
    (reg/'registration.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2))
    (fus/'fusion_summary.json').write_text(json.dumps(fsum,ensure_ascii=False,indent=2))
    print(json.dumps({'downloaded':len(tasks),'rejected':len(rejected),'plan':fsum['plans']['full']},ensure_ascii=False))
    return 0
if __name__=='__main__': sys.exit(main())
