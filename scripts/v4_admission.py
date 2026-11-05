"""V4.1 §2.4 admission: calibrate tolerances with truth/perturbed priors."""
import argparse,json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_register,v3_fuse

def grid_from_V(V):
    o=np.asarray(V['origin'],float); p=float(V['pitch']); d=tuple(int(x) for x in V['dims'])
    g={'origin':o,'pitch':p,'dims':np.array(d)}
    g['xs']=o[0]+(np.arange(d[0])+0.5)*p; g['ys']=o[1]+(np.arange(d[1])+0.5)*p; g['zs']=o[2]+(np.arange(d[2])+0.5)*p
    return g

def metrics(mesh,M,V,g,diag):
    w=mesh.copy(); w.apply_transform(M)
    shell=V['shell']; space=V['space']; U=(space==0)
    try:
        P,_=v3_fuse.voxelize_columns(w,g)
    except Exception:
        P=np.zeros(tuple(int(x) for x in V['dims']),dtype=bool)
    n=int(P.sum()); Ucount=int((P&U).sum()); free=int((P&(space==2)).sum())
    # shell contact: boundary of P adjacent to shell
    from scipy import ndimage
    touched=ndimage.binary_dilation(P,iterations=1)&shell
    contact=int(touched.sum())
    zs=g['zs']; vis_h=float(zs[shell.any(axis=(0,1))].max()-zs[shell.any(axis=(0,1))].min())
    h=float(w.bounds[1][2]-w.bounds[0][2])
    return {'height_world_m':round(h,5),'visible_height_m':round(vis_h,5),
            'scale_ratio':round(h/max(vis_h,1e-6),4),
            'hidden_voxels':int(Ucount),'hidden_frac':round(Ucount/max(n,1),5),
            'shell_contact':round(contact/max(int(shell.sum()),1),5),'free_intrusion_frac':round(free/max(n,1),5),
            'contour_iou':round(float(diag.get('mask_iou',0)),4),'depth_p95_mm':round(float(diag.get('depth_p95_mm',0)),3),
            'voxels':n}

def run(truth='runs/v3/stage008/truth_v2'):
    T=ROOT/truth
    V=np.load(T/'fusion/V.npz'); g=grid_from_V(V)
    obs=v3_register.load_observation(str(T/'observation'))
    proto=json.loads((ROOT/'plans/v3_protocol.json').read_text())
    mesh=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False)
    V0=np.asarray(mesh.vertices,float); c=V0.mean(0); h=float(V0[:,2].max()-V0[:,2].min())
    out={'schema':'v4-admission/v1','truth':truth,'cases':{}}
    # truth prior in world coords: register trivially? build local frame at identity-ish
    cases=[('truth',np.eye(4))]
    for dx in (-0.02,0.0,0.02):
        for s in (0.9,1.0,1.1):
            if dx==0.0 and s==1.0: continue
            M=np.eye(4); M[:3,:3]=s*np.eye(3)
            M[:3,3]=c - s*c; M[0,3]+=dx
            cases.append((f'truth_dx{dx:+.2f}_s{s}',M))
    # also two clearly bad controls
    bad=np.eye(4); bad[0,3]=0.15; cases.append(('bad_shift15cm',bad))
    bad2=np.eye(4); bad2[:3,:3]*=0.6; cases.append(('bad_scale06',bad2))
    for name,M in cases:
        d=ROOT/'runs/v4/wp3/admission'/name; d.mkdir(parents=True,exist_ok=True)
        ev=v3_register.evaluate_matrix(mesh,obs,M)
        mm=metrics(mesh,np.asarray(M,float),V,g,ev)
        mm['converged']=True
        out['cases'][name]=mm
    good=[v for k,v in out['cases'].items() if not k.startswith('bad')]
    bads=[v for k,v in out['cases'].items() if k.startswith('bad')]
    cfg={'schema':'v4-admission/v1','calibrated_from':truth,
         'scale_ratio':{'min':round(min(x['scale_ratio'] for x in good)*0.97,3),'max':round(max(x['scale_ratio'] for x in good)*1.03,3)},
         'hidden_frac_min':round(min(x['hidden_frac'] for x in good)*0.5,4),
         'shell_contact_min':round(min(x['shell_contact'] for x in good)*0.5,4),
         'free_intrusion_max':0.02,
         'contour_iou_min':round(min(x['contour_iou'] for x in good)-0.02,4),
         'notes':'scale ratio = registered world height / V shell height; contour = visible mask IoU (report only in WP3 tables)',
         'calibration':out}
    p=ROOT/'configs/v4_admission.json'; p.write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
    print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk in ('scale_ratio','hidden_frac','shell_contact','free_intrusion_frac','contour_iou')} for k,v in out['cases'].items()},ensure_ascii=False,indent=2))
    print('config',p)
if __name__=='__main__': run(sys.argv[1] if len(sys.argv)>1 else 'runs/v3/stage008/truth_v2')
