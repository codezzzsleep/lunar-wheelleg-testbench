import json,pathlib,sys
import numpy as np,trimesh
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import stage8_matrix2 as M,v3_fuse,wheelleg_env,skills,runner,v3_record,v7_soil
T=ROOT/'runs/v3/stage008/truth_v2'
def main():
 out=ROOT/'runs/v4/wp7/A2_gravel'; out.mkdir(parents=True,exist_ok=True)
 z=np.load(T/'fusion/V.npz'); o=np.asarray(z['origin'],float); pitch=float(z['pitch']); dims=tuple(int(x) for x in z['dims'])
 g={'origin':o,'pitch':pitch,'dims':np.array(dims)}
 g['xs']=o[0]+(np.arange(dims[0])+0.5)*pitch; g['ys']=o[1]+(np.arange(dims[1])+0.5)*pitch; g['zs']=o[2]+(np.arange(dims[2])+0.5)*pitch
 mesh=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False)
 P0,_=v3_fuse.voxelize_columns(mesh,g)
 low=(g['zs'][None,None,:]<0.05); P0=P0&low
 Ps=[]
 for x,y in ((1.0,0.0),(2.0,0.15),(3.0,-0.15)):
  sx=int(round((x-1.0)/pitch)); sy=int(round(y/pitch)); Q=np.zeros_like(P0)
  Q[max(0,sx):,max(0,sy):]=P0[:P0.shape[0]-max(0,sx) if sx>0 else P0.shape[0],:P0.shape[1]-max(0,sy) if sy>0 else P0.shape[1]]
  Ps.append(Q)
 P=np.logical_or.reduce(Ps)
 td=out/'coll'; td.mkdir(exist_ok=True)
 spec,env,sha=M.make_scene(M.resample_walls(P,o,pitch),td,'wp7_gravel')
 spec['terrain']['field_x_max']=10.0; spec['goal_x']=4.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=v7_soil.resolve('nominal')
 (out/'scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
 (out/'assets').mkdir(exist_ok=True); mesh.export(out/'assets'/'rock_small.obj')
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=30); env.reset(seed=0); snap=env.save_state()
 rec=v3_record.Recorder(out/'record',{'scene':'A2_gravel','action':'R1'},hz=50.0)
 ep=runner.EpisodeRunner(env,skills.make_skill('R1'),visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=1500,seed=0,record_trajectory=True); ep.recorder=rec
 res=ep.run_from_state(snap,mode='same_scene'); rec.close()
 files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp7-scene/v1','scene':'A2_gravel','files':files},ensure_ascii=False,indent=2))
 print(json.dumps({'success':res.get('success'),'reason':res.get('reason'),'t_end':res.get('t_end'),'x':res.get('final_x'),'tilt':res.get('max_tilt')}))
if __name__=='__main__': main()
