"""导出 Go2W 的真实关节/执行器映射（V1-A 第一步：不猜符号、腿长、轮径）。

  python scripts/v3_ctrl_map.py --out docs/evidence/v1_joint_map.json

只读模型：每个 关节 -> qadr/vadr/轴/range/限速；每个 执行器 -> trnid/gear/ctrlrange/
forcerange；轮半径来自模型几何（球/圆柱/网格包围盒）不写死。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='docs/evidence/v1_joint_map.json')
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    import terrain
    import wheelleg_env
    import mujoco
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.9, name='map')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=1.0)
    m, d = env.model, env.data
    joints, acts = [], []
    for j in range(m.njnt):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or f'joint{j}'
        info = {'name': name, 'type': int(m.jnt_type[j]),
                'qadr': int(m.jnt_qposadr[j]), 'dofadr': int(m.jnt_dofadr[j]),
                'axis': [float(x) for x in m.jnt_axis[j]],
                'range': [float(x) for x in m.jnt_range[j]],
                'limited': bool(m.jnt_limited[j])}
        # 限速：把上下限映射到 dof 的 jnt_actfrclimited 无法直接读，改用 range/时间常数标注
        joints.append(info)
    for i in range(m.nu):
        an = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i) or f'act{i}'
        acts.append({'index': i, 'name': an, 'trnid': int(m.actuator_trnid[i][0]),
                     'gear': [float(x) for x in m.actuator_gear[i]],
                     'ctrlrange': [float(x) for x in m.actuator_ctrlrange[i]],
                     'ctrllimited': bool(m.actuator_ctrllimited[i]),
                     'forcerange': [float(x) for x in m.actuator_forcerange[i]],
                     'forcelimited': bool(m.actuator_forcelimited[i])})
    # 轮几何：取四个 wheel body 的 geom 半径/包围盒
    wheels = {}
    wheel_bodies = {}
    for b in range(m.nbody):
        bn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or ''
        if 'wheel' in bn.lower():
            wheel_bodies[bn] = b
    for leg in ('FR', 'FL', 'RR', 'RL'):
        cand = [v for k, v in wheel_bodies.items() if k.upper().startswith(leg)]
        b = cand[0] if cand else -1
        if b < 0:
            continue
        gs = [g for g in range(m.ngeom) if m.geom_bodyid[g] == b]
        rad = [float(m.geom_size[g][0]) for g in gs if m.geom_type[g] in (2, 3, 5, 6)]
        wheels[leg] = {'body_id': int(b), 'n_geom': len(gs),
                       'geom_types': [int(m.geom_type[g]) for g in gs],
                       'radius_candidates': rad,
                       'geom_sizes': [[float(x) for x in m.geom_size[g]] for g in gs],
                       'geom_mesh_names': [
                           mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_MESH,
                                             int(m.geom_dataid[g]))
                           for g in gs if m.geom_type[g] == 7],
                       'body_name': mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b),
                       'body_pos': [float(x) for x in m.body_pos[b]]}
    out = {'schema': 'v3-ctrl-map/v1', 'model': 'Go2W (unitree_mujoco)',
           'nq': int(m.nq), 'nv': int(m.nv), 'nu': int(m.nu),
           'timestep_s': float(m.opt.timestep), 'gravity': [float(x) for x in m.opt.gravity],
           'joints': joints, 'actuators': acts, 'wheels': wheels,
           'notes': ('qadr/dofadr 是 MuJoCo 原生下标；gear 是执行器到关节的传动比；'
                     'radius_candidates 只作核对，生产用协议里的 wheel_radius_m')}
    p = ROOT / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'out': a.out, 'nq': out['nq'], 'nv': out['nv'], 'nu': out['nu'],
                      'n_joints': len(joints), 'n_actuators': len(acts),
                      'wheels': {k: v['radius_candidates'] for k, v in wheels.items()}},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
