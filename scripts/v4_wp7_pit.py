"""WP7 B2: boulder with a pit on one side; choose the clear side."""
import json,pathlib,sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import terrain,wheelleg_env,skills,runner,v3_record
def main():
 out=ROOT/'runs/v4/wp7/B2_pit_side'; out.mkdir(parents=True,exist_ok=True)
 spec=terrain.make_spec(kind='flat',seed=14,pits=1,pit_depth=0.30,goal_x=3.0,name='wp7_B2',span=10.0)
 spec['terrain']['field_x_max']=8.0; spec['channel']={'center_y':0.0,'half_width':1.2}; spec['soil']=__import__('v7_soil').resolve('nominal')
 # inspect pit location
 h,meta=terrain.build_heightfield(spec); yy,xx=np.unravel_index(np.argmin(h),h.shape); print('pit min at x',round(float(xx)/h.shape[1]*10-5,2),'y',round(float(yy)/h.shape[0]*10-5,2),'depth',round(float(h.min()),2))
 (out/'scene.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
 env=wheelleg_env.WheelLegEnv(spec,max_seconds=30); env.reset(seed=0); env.nav_target_y=-0.45; snap=env.save_state()
 rec=v3_record.Recorder(out/'record',{'scene':'B2_pit_side','action':'D2'},hz=50.0)
 ep=runner.EpisodeRunner(env,skills.make_skill('D1'),visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=2000,seed=0,record_trajectory=True); ep.recorder=rec
 res=ep.run_from_state(snap,mode='same_scene'); rec.close()
 (out/'decision.json').write_text(json.dumps({'chosen':'D1','reason':'pit on right, choose left'},indent=2))
 files=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 (out/'manifest.json').write_text(json.dumps({'schema':'v4-wp7-scene/v1','scene':'B2_pit_side','files':files},ensure_ascii=False,indent=2))
 print(json.dumps({'success':res.get('success'),'reason':res.get('reason'),'t_end':res.get('t_end'),'x':res.get('final_x'),'tilt':res.get('max_tilt')}))
if __name__=='__main__': main()
