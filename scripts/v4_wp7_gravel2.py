"""WP7 A2 gravel v2: three low true rocks on a coarse grid; wheel over."""
import json,pathlib,sys,hashlib
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import terrain,v3_core,v3_fuse,wheelleg_env,skills,runner,v3_record
T=ROOT/'runs/v3/stage008/truth_v2'
def main():
 out=ROOT/'runs/v4/wp7/A2_gravel'; out.mkdir(parents=True,exist_ok=True)
 zf=np.load(T/'fusion/V.npz'); of=np.asarray(zf['origin'],float); pf=float(zf['pitch']); df=tuple(int(x) for x in zf['dims'])
 gf={'origin':of,'pitch':pf,'dims':np.array(df)}
 gf['xs']=of[0]+(np.arange(df[0])+0.5)*pf; gf['ys']=of[1]+(np.arange(df[1])+0.5)*pf; gf['zs']=of[2]+(np.arange(df[2])+0.5)*pf
 mesh=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False); P,_=v3_fuse.voxelize_columns(mesh,gf)
 ix,iy,iz=np.nonzero(P); wx=of[0]+(ix+0.5)*pf; wy=of[1]+(iy+0.5)*pf; wz=of[2]+(iz+0.5)*pf
 ORIG=np.array([-1.5,-1.5,0.0]); PIT=0.03; DIMS=(260,100,50); Q=np.zeros(DIMS,bool)
 for x0,y0 in ((1.0,0.0),(2.0,0.22),(3.0,-0.22)):
  cx=np.floor((wx+(x0-1.0)-ORIG[0])/PIT).astype(int); cy=np.floor((wy+y0-ORIG[1])/PIT).astype(int); cz=np.floor((wz-ORIG[2])/PIT).astype(int)
  ok=(cx>=0)&(cx<DIMS[0])&(cy>=0)&(cy<DIMS[1])&(cz>=0)&(cz<DIMS[2]); Q[cx[ok],cy[ok],cz[ok]]=True
 zc=ORIG[2]+(np.arange(DIMS[2])+0.5)*PIT; Q[:,:,zc>0.07]=False
 print('occ',int(Q.sum()))
 td=out/'coll'; td.mkdir(exist_ok=True)
 np.savez(out/'occ.npz',occupied=Q,origin=ORIG,pitch=PIT,dims=DIMS,
          content_sha=np.array(hashlib.sha256(np.ascontiguousarray(Q).tobytes()).hexdigest()[:32]),
          convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
 r=v3_core.build_collision(out/'occ.npz',td,pitch=PIT,downsample=1); print('coll',r.get('ok'),r.get('n_boxes'))
 spec=terrain.make_spec(kind='flat',seed=0,goal_x=4.0,objects=[{'posed_dir':str(td)}],name='wp7_gravel2',span=8.0)
 spec['terrain']['field_x_max']=7.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=__import__('v7_soil').resolve('nominal')
 (out/'scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=40); env.reset(seed=0); snap=env.save_state()
 rec=v3_record.Recorder(out/'record',{'scene':'A2_gravel2','action':'R1'},hz=50.0)
 ep=runner.EpisodeRunner(env,skills.make_skill('R1'),visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=2000,seed=0,record_trajectory=True); ep.recorder=rec
 res=ep.run_from_state(snap,mode='same_scene'); rec.close()
 files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp7-scene/v1','scene':'A2_gravel2','files':files},ensure_ascii=False,indent=2))
 print(json.dumps({'success':res.get('success'),'reason':res.get('reason'),'t_end':res.get('t_end'),'x':res.get('final_x'),'tilt':res.get('max_tilt')}))
if __name__=='__main__': main()
