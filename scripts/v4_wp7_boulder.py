"""WP7 B1: open boulder, choose a side and execute; save scene+record."""
import json,pathlib,sys,copy
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import stage8_matrix2 as M,wheelleg_env,skills,runner,v3_record,numpy as np
T=ROOT/'runs/v3/stage008/truth_v2'
def main():
    out=ROOT/'runs/v4/wp7/B1_boulder_detour'; out.mkdir(parents=True,exist_ok=True)
    z=np.load(T/'fusion/V.npz'); P=np.load(T/'truth_v2_occ.npz')['occupied'] if (T/'truth_v2_occ.npz').exists() else None
    # build truth occupancy from truth mesh on V grid
    import v3_fuse,trimesh
    V=z; o=np.asarray(V['origin'],float); pitch=float(V['pitch']); dims=tuple(int(x) for x in V['dims'])
    g={'origin':o,'pitch':pitch,'dims':np.array(dims)}
    g['xs']=o[0]+(np.arange(dims[0])+0.5)*pitch; g['ys']=o[1]+(np.arange(dims[1])+0.5)*pitch; g['zs']=o[2]+(np.arange(dims[2])+0.5)*pitch
    mesh=trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False)
    P,_=v3_fuse.voxelize_columns(mesh,g)
    # shift rock +0.5 m in x
    sh=int(round(0.5/pitch)); Q=np.zeros_like(P); Q[sh:]=P[:-sh]
    td=out/'coll'; td.mkdir(parents=True,exist_ok=True)
    spec,env,sha=M.make_scene(M.resample_walls(Q,o,pitch),td,'wp7_boulder')
    spec['terrain']['field_x_max']=12.0; spec['goal_x']=3.0
    (out/'scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
    # assets
    ad=out/'assets'; ad.mkdir(exist_ok=True)
    trimesh.load(str(T/'truth/body_world.stl'),force='mesh',process=False).export(ad/'body_world.stl')
    (ad/'pose.json').write_text(json.dumps({'shift_x_m':0.5,'source':'runs/v3/stage008/truth_v2/truth/body_world.stl'},indent=2))
    snap=json.loads((T/'state_snapshot.json').read_text())
    orig=wheelleg_env.WheelLegEnv(json.loads((T/'scene_spec.json').read_text()),max_seconds=5); orig.reset(seed=0); orig.restore_state(snap,mode='same_scene')
    ref=(np.asarray(orig.data.qpos,float).copy(),np.asarray(orig.data.qvel,float).copy())
    env=wheelleg_env.WheelLegEnv(spec,max_seconds=30); env.reset(seed=0); env.restore_state(snap,mode='project'); env.data.qpos[:]=ref[0]; env.data.qvel[:]=ref[1]
    # decision: boulder centered, channel half 1.2 -> both sides open; pick right (D2)
    env.nav_target_y=0.0
    rec=v3_record.Recorder(out/'record',{'scene':'B1_boulder_detour','action':'D2'},hz=50.0)
    ep=runner.EpisodeRunner(env,skills.make_skill('D2'),visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=1500,seed=0,record_trajectory=True)
    ep.recorder=rec; res=ep.run_from_state(snap,mode='project'); rec.close()
    (out/'decision.json').write_text(json.dumps({'chosen':'D2','reason':'both sides open, pick right','res':res},ensure_ascii=False,indent=2))
    files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
    (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp7-scene/v1','scene':'B1_boulder_detour','files':files},ensure_ascii=False,indent=2))
    print(json.dumps({'success':res.get('success'),'reason':res.get('reason'),'t_end':res.get('t_end'),'x':res.get('final_x'),'files':len(files)}))
if __name__=='__main__': main()
