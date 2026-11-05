"""Evaluate WP3 candidates: observation build, registration, admission, signed metrics."""
import json,pathlib,sys,csv
import numpy as np
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import v3_register,v3_fuse,camera_io,v4_admission,v3_generate
import trimesh

def build_obs(rock,yaw):
    if rock=='moon_rock_05' and int(yaw)==0:
        return ROOT/'runs/v3/stage008/truth_v2/observation',0
    view=ROOT/'runs/v4/wp3/views'/rock/f'yaw{yaw:+d}'
    cam=json.loads((view/'camera.json').read_text())
    d=ROOT/'runs/v4/wp3/obs'/rock/f'yaw{yaw:+d}'; d.mkdir(parents=True,exist_ok=True)
    depth=np.load(view/'depth.npy').astype(np.float64); mask=np.asarray(Image.open(view/'mask.png').convert('L'))>127
    depth_m=np.where(mask,depth,np.nan)
    pts,_,_=camera_io.unproject_depth(depth_m,cam)
    np.save(d/'depth.npy',depth_m); np.save(d/'visible_points.npy',pts)
    Image.open(view/'mask.png').save(d/'mask.png'); Image.open(view/'rgb.png').save(d/'rgb.png')
    (d/'observation.json').write_text(json.dumps({'camera':cam,'intrinsics':cam['intrinsics'],
        'view_yaw_deg':cam.get('view_yaw_deg'),'source_rock':rock},ensure_ascii=False,indent=2))
    return d,len(pts)

def main():
    tasks=json.loads((ROOT/'runs/v4/wp3/tasks.json').read_text())['tasks']
    first=[t for t in tasks if t['create_order']<=18]
    cfg=json.loads((ROOT/'configs/v4_admission.json').read_text())
    T=ROOT/'runs/v3/stage008/truth_v2'; V=np.load(T/'fusion/V.npz'); g=v4_admission.grid_from_V(V)
    truth_mesh=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False)
    rows=[]; obs_cache={}
    for t in first:
        key=(t['rock'],t['view_yaw_deg'])
        if key not in obs_cache: obs_cache[key]=build_obs(*key)[0]
        obs_dir=obs_cache[key]
        ident=v3_generate.identity_of(t); cache=ROOT/'runs/v3/generation/cache'/ident/'model.glb'
        row={'task':t['id'],'rock':t['rock'],'yaw':t['view_yaw_deg'],'crop':t['crop'],'repeat':t['repeat_idx'],'identity':ident,
             'glb_exists':cache.exists()}
        if not cache.exists(): rows.append(row); continue
        d=ROOT/'runs/v4/wp3/registered'/ident; d.mkdir(parents=True,exist_ok=True)
        proto=json.loads((ROOT/'plans/v3_protocol.json').read_text())
        rec=v3_register.register(str(cache),str(obs_dir),proto,d,top_k=6)
        M=np.asarray(rec['best']['M'],float); ev=v3_register.evaluate_matrix(trimesh.load(str(cache),force='mesh',process=False),v3_register.load_observation(str(obs_dir)),M)
        m=v4_admission.metrics(trimesh.load(str(cache),force='mesh',process=False),M,V,g,ev)
        ok=(cfg['scale_ratio']['min']<=m['scale_ratio']<=cfg['scale_ratio']['max'] and m['hidden_frac']>=cfg['hidden_frac_min']
            and m['shell_contact']>=cfg['shell_contact_min'] and m['free_intrusion_frac']<=cfg['free_intrusion_max'] and m['contour_iou']>=cfg['contour_iou_min'])
        row.update({'admitted':ok,'M':M.tolist(),'metrics':m})
        # signed bulk metrics vs truth hidden mesh (same grid)
        full=V['shell']|(v3_fuse.voxelize_columns(trimesh.load(str(cache),force='mesh',process=False).apply_transform(M),g)[0]&(V['space']==0))
        Truth,_=v3_fuse.voxelize_columns(truth_mesh,g)
        def rear(P):
            xs=g['xs']; ax=P.any(axis=(1,2)); return float(xs[ax].max()) if ax.any() else None
        def top(P):
            zs=g['zs']; ax=P.any(axis=(0,1)); return float(zs[ax].max()) if ax.any() else None
        row.update({'rear_candidate':rear(full),'rear_truth':rear(Truth),'rear_err_m':None if rear(full) is None else round(rear(full)-rear(Truth),4),
                    'top_candidate':top(full),'top_truth':top(Truth),'top_err_m':None if top(full) is None else round(top(full)-top(Truth),4)})
        rows.append(row); print(json.dumps({k:row.get(k) for k in ('task','admitted','rear_err_m','top_err_m')},ensure_ascii=False),flush=True)
        out=ROOT/'runs/v4/wp3'; (out/'candidates.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    if rows:
        keys=['task','rock','yaw','crop','repeat','identity','admitted','rear_err_m','top_err_m']
        with (ROOT/'runs/v4/wp3/candidates.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows([{k:r.get(k) for k in keys} for r in rows])
    print('done',len(rows),'admitted',sum(bool(r.get('admitted')) for r in rows))
if __name__=='__main__': main()
