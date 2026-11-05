"""V5 core: 2.5D column fill, hidden metrics, admission metrics."""
import pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v5_metrics_ref as R

def grid_from_V(V):
    o=np.asarray(V['origin'],float); p=float(V['pitch']); d=tuple(int(x) for x in V['dims'])
    g={'origin':o,'pitch':p,'dims':np.array(d)}
    g['xs']=o[0]+(np.arange(d[0])+0.5)*p; g['ys']=o[1]+(np.arange(d[1])+0.5)*p; g['zs']=o[2]+(np.arange(d[2])+0.5)*p
    return g

def clean_mesh(mesh):
    m=R.drop_small_fragments(mesh); return m

def P_of(mesh,g,M=None):
    m=mesh.copy()
    if M is not None: m.apply_transform(np.asarray(M,float))
    return R.column_fill_top(m,g)

def admission_metrics(mesh,M,V,g,ev=None):
    P=P_of(mesh,g,M); shell=V['shell']; U=(V['space']==0)
    # visible-surface scale: candidate height in columns where shell exists
    vis=shell.any(axis=2); zs=g['zs']
    vz=(P&vis[:,:,None]).any(axis=(0,1)); h=float(zs[vz].max()-zs[vz].min()) if vz.any() else 0.0
    shellh=float(zs[shell.any(axis=(0,1))].max()-zs[shell.any(axis=(0,1))].min())
    from scipy import ndimage
    touched=ndimage.binary_dilation(P,iterations=1)&shell
    intr=R.free_intrusion(P,V['space'],g)
    return {'P':P,'scale_ratio':round(h/max(shellh,1e-6),4),'hidden_frac':round(float((P&U).sum())/max(int(P.sum()),1),4),
            'shell_contact':round(float(touched.sum())/max(int(shell.sum()),1),4),
            'free_intrusion_frac':intr['free_intrusion_frac'],'intrusion_depth_p95_mm':intr['intrusion_depth_p95_mm'],
            'voxels':int(P.sum()),'contour_iou':None if ev is None else round(float(ev.get('mask_iou',0)),4)}
