import json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import terrain,wheelleg_env,skills,runner,v3_record,v7_soil
def main():
 out=ROOT/'runs/v4/wp7/A3_slope8'; out.mkdir(parents=True,exist_ok=True)
 spec=terrain.make_spec(kind='slope',seed=0,slope_deg=8.0,goal_x=5.0,name='v4_wp7_slope',span=12.0)
 spec['terrain']['field_x_max']=10.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=v7_soil.resolve('nominal')
 (out/'scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=60); env.reset(seed=0); snap=env.save_state()
 rec=v3_record.Recorder(out/'record',{'scene':'A3_slope8','action':'R1'},hz=50.0)
 ep=runner.EpisodeRunner(env,skills.make_skill('R1'),visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=3000,seed=0,record_trajectory=True); ep.recorder=rec
 res=ep.run_from_state(snap,mode='same_scene'); rec.close()
 files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp7-scene/v1','scene':'A3_slope8','files':files},ensure_ascii=False,indent=2))
 print(json.dumps({'success':res.get('success'),'reason':res.get('reason'),'t_end':res.get('t_end'),'x':res.get('final_x'),'tilt':res.get('max_tilt')}))
if __name__=='__main__': main()
