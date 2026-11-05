import copy,json,pathlib,sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'scripts'))
import wheelleg_env,skills,runner,mujoco
T=ROOT/'runs/v3/stage008/truth_v2'; spec=json.loads((T/'scene_spec.json').read_text()); snap=json.loads((T/'state_snapshot.json').read_text())
orig=wheelleg_env.WheelLegEnv(spec,max_seconds=10); orig.reset(seed=0); orig.restore_state(snap,mode='same_scene')
ref=(np.asarray(orig.data.qpos,float).copy(),np.asarray(orig.data.qvel,float).copy())
variants=[('softD',{'kc':250.0,'kphi':50000.0,'cohesion_pa':35.0,'phi_deg':21.0,'k_shear':0.03}),
          ('softE',{'kc':220.0,'kphi':45000.0,'cohesion_pa':32.0,'phi_deg':20.5,'k_shear':0.03})]
for name,p in variants:
    s=copy.deepcopy(spec); s['soil']={'mode':'soil','label':name,'params':dict(n=1.0,**p)}
    env=wheelleg_env.WheelLegEnv(s,max_seconds=10); env.reset(seed=0); env.restore_state(snap,mode='project'); env.data.qpos[:]=ref[0]; env.data.qvel[:]=ref[1]; mujoco.mj_forward(env.model,env.data)
    ep=runner.EpisodeRunner(env,skills.make_skill('R1'),visible={'x_front':0.834,'W_vis':0.275,'H_vis':0.30},max_steps=500,seed=0,record_trajectory=False)
    out=ep.run_from_state(snap,mode='project'); q=env.data.qpos
    print(json.dumps({'variant':name,'params':p,'advance_m':round(float(q[0]-ref[0][0]),3),'z':round(float(q[2]),3),'t':round(float(env.t),2),'reason':out.get('reason')}),flush=True)
