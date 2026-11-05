"""WP5 probe: uniform soft soil, WHEEL_ONLY entry, measure advance/sink/slip."""
import json,pathlib,sys,copy
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,skills,runner,v3_record
T=ROOT/'runs/v3/stage008/truth_v2'
spec=json.loads((T/'scene_spec.json').read_text())
soft=copy.deepcopy(spec); soft['soil']={'mode':'soil','label':'v4_soft','params':{'n':1.0,'kc':800.0,'kphi':300000.0,'cohesion_pa':80.0,'phi_deg':28.0,'k_shear':0.025}}
snap=json.loads((T/'state_snapshot.json').read_text())
orig=wheelleg_env.WheelLegEnv(spec,max_seconds=10); orig.reset(seed=0); orig.restore_state(snap,mode='same_scene')
ref=(np.asarray(orig.data.qpos,float).copy(),np.asarray(orig.data.qvel,float).copy())
env=wheelleg_env.WheelLegEnv(soft,max_seconds=10); env.reset(seed=0); env.restore_state(snap,mode='project'); env.data.qpos[:]=ref[0]; env.data.qvel[:]=ref[1]
import mujoco; mujoco.mj_forward(env.model,env.data)
sk=skills.make_skill('R1'); ep=runner.EpisodeRunner(env,sk,visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=500,seed=0,record_trajectory=True)
rec=v3_record.Recorder(ROOT/'runs/v4/wp5/probe/record',{'action':'R1','soil':'uniform_soft'},hz=50.0); ep.recorder=rec
out=ep.run_from_state(snap,mode='project'); rec.close()
q=np.array([f for c in sorted((ROOT/'runs/v4/wp5/probe/record').glob('chunk_*.npz')) for f in np.load(c)['qpos']])
qv=np.concatenate([np.load(c)['qvel'] for c in sorted((ROOT/'runs/v4/wp5/probe/record').glob('chunk_*.npz'))])
print(json.dumps({'success':out.get('success'),'reason':out.get('reason'),'steps':out.get('steps'),'advance_m':round(float(q[-1,0]-q[0,0]),3),'t_end':out.get('t_end'),'sink_max':round(float(np.max(np.abs(q[:,2]-q[0,2]))),3),'slip_med':round(float(np.median([(0.15 - v)/max(0.15,1e-3) for v in qv[:,0]])),3)},ensure_ascii=False))
