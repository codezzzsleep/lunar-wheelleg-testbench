import mujoco, re, pathlib, numpy as np
src = pathlib.Path('vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml')
xml = src.read_text()
xml = re.sub(r'<option([^>]*)/>', r'<option\1 gravity="0 0 -1.62"/>', xml, count=1)
out = src.parent / 'go2w_moon.xml'; out.write_text(xml)
m = mujoco.MjModel.from_xml_path(str(out))
print('nq', m.nq, 'nv', m.nv, 'nu', m.nu, 'nbody', m.nbody)
print('timestep', m.opt.timestep, 'gravity', m.opt.gravity)
print('--- actuators ---')
for i in range(m.nu):
    n = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
    j = m.actuator_trnid[i,0]
    jn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j)
    print(f'{i:2d} {n:18s} -> joint {jn}')
print('--- keyframes ---', m.nkey)
print('qpos0', np.round(m.qpos0,3))
