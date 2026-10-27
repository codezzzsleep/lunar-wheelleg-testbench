"""
S0：实测机器人尺寸、动作方向与真正的刹停能力。不写死任何尺寸常数。

  .venv/bin/python scripts/measure_robot.py --out runs/unseen/prep/<run_id>/robot_dims.json
"""
import argparse, json, pathlib, sys
import numpy as np, mujoco
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain, wheelleg_env

LEGS = ('FL', 'FR', 'RL', 'RR')


def make_env(**kw):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=3.0, name='measure')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    return wheelleg_env.WheelLegEnv(spec, **kw)


def wheel_geoms(m, leg):
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
    return bid, [g for g in range(m.ngeom) if m.geom_bodyid[g] == bid]


def robot_geoms(m):
    """除地形以外的全部几何（用于最低点/包络）。"""
    terr = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'terrain')
    obs = set()
    for i in range(20):
        obs |= {g for g in range(m.ngeom)
                if m.geom_bodyid[g] == mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'obstacle{i}')}
    return [g for g in range(m.ngeom) if g != terr and g not in obs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)

    env = make_env()
    env.reset(seed=0)
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)

    wheels, radius, half_w = {}, [], []
    for leg in LEGS:
        bid, gs = wheel_geoms(m, leg)
        # mesh 几何的 size = 包围盒半尺寸：x=半宽, y/z=半径
        r = max(float(m.geom_size[g][2]) for g in gs)
        hw_ = max(float(m.geom_size[g][0]) for g in gs)
        radius.append(r); half_w.append(hw_)
        wheels[leg] = {'body_x': round(float(d.xpos[bid][0]), 5),
                       'body_y': round(float(d.xpos[bid][1]), 5),
                       'axle_z': round(float(d.xpos[bid][2]), 5),
                       'mesh_radius': round(r, 5), 'half_width': round(hw_, 5)}

    # 躯干：该模型**没有躯干碰撞几何**（碰撞只挂在髋/大腿/小腿/轮上）。
    # 因此 belly 用视觉网格的包围盒估算，并如实标注这一限制。
    wheel_ids = {gg for leg in LEGS for gg in wheel_geoms(m, leg)[1]}
    torso_z = {}
    for bid in range(m.nbody):
        nm = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, bid)
        if not nm or nm in ('world',) or nm.endswith(('_hip', '_thigh', '_calf', '_wheel_link')):
            continue
        if nm in ('obstacle0',) or nm.startswith('obstacle'):
            continue
        vis = [g for g in range(m.ngeom) if m.geom_bodyid[g] == bid]
        torso_z[nm] = round(float(d.xpos[bid][2]), 5)
    trunk_bid = max(torso_z, key=torso_z.get) if torso_z else None
    belly = None
    lb = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    if lb >= 0:
        tgs = [g for g in range(m.ngeom) if m.geom_bodyid[g] == lb]
        if tgs:
            belly = round(float(min(d.geom_xpos[g][2] - m.geom_rbound[g] for g in tgs)), 5)
    leg_bodies = {mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'{l}_{p}')
                  for l in LEGS for p in ('hip', 'thigh', 'calf', 'wheel_link')}
    terrain_gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'terrain')
    trunk_geoms = [g for g in range(m.ngeom)
                   if m.geom_bodyid[g] not in leg_bodies
                   and g != terrain_gid and m.geom_bodyid[g] != 0]
    has_trunk_collision = bool(trunk_geoms)

    def act_sign_scan():
        rows = []
        for v in (-1.0, -0.5, 0.0, 0.5, 1.0):
            for kind, act in (('front_leg', [v, 0.0, 0.0]), ('rear_leg', [0.0, v, 0.0])):
                env.reset(seed=0)
                for _ in range(100):
                    env.step(act)
                fl = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'FL_wheel_link')
                rl = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'RL_wheel_link')
                q = env.data.qpos[3:7]
                pitch = np.degrees(np.arcsin(np.clip(
                    -2 * (q[1] * q[3] - q[0] * q[2]), -1, 1)))
                rows.append({'kind': kind, 'value': v,
                             'front_axle_z': round(float(env.data.xpos[fl][2]), 5),
                             'rear_axle_z': round(float(env.data.xpos[rl][2]), 5),
                             'pitch_deg': round(float(pitch), 2)})
        return rows

    env.reset(seed=0)
    for _ in range(200):
        env.step([0, 0, 0])
    v_cruise = float(env.data.qvel[0])

    env.reset(seed=0)
    for _ in range(200):
        env.step([0, 0, 0])
    for _ in range(100):
        env.step([0, 0, -1.0])            # 旧接口"最低轮速"
    v_minus1 = float(env.data.qvel[0])

    # 真正的刹停：轮速目标固定为 0，走 drive=False 路径
    env.reset(seed=0)
    for _ in range(200):
        env.step([0, 0, 0])
    x0 = float(env.data.qpos[0])
    for _ in range(150):
        for _ in range(env.substeps):
            wb = env.data
            for leg in LEGS:
                e = env.J[f'{leg}_wheel_joint']
                wb.ctrl[e['act']] = float(np.clip(
                    -6.0 * wb.qvel[e['vadr']],
                    -wheelleg_env.WHEEL_MAX, wheelleg_env.WHEEL_MAX))
            mujoco.mj_step(env.model, env.data)
    v_brake = float(env.data.qvel[0])
    x_brake = float(env.data.qpos[0]) - x0

    dims = {
        'wheel_radius_m': round(float(np.mean(radius)), 5),
        'wheel_width_m': round(float(2 * np.mean(half_w)), 5),
        'half_track_m': round(float(abs(wheels['FL']['body_y'] - wheels['FR']['body_y']) / 2), 5),
        'track_m': round(float(abs(wheels['FL']['body_y'] - wheels['FR']['body_y'])), 5),
        'wheelbase_m': round(float(abs(wheels['FL']['body_x'] - wheels['RL']['body_x'])), 5),
        'belly_clearance_m': belly,
        'trunk_has_collision_geom': has_trunk_collision,
        'belly_clearance_note': ('该模型躯干无碰撞几何，托底不会发生，只能记录腿部接触'
                                 if not has_trunk_collision else '躯干有碰撞几何'),
        'wheels': wheels,
        'action_scan': act_sign_scan(),
        'brake': {'cruise_vx_mps': round(v_cruise, 4),
                  'vx_a2_minus1': round(v_minus1, 4),
                  'vx_after_explicit_brake': round(v_brake, 4),
                  'stopping_distance_m': round(x_brake, 4),
                  'a2_minus1_stops': bool(abs(v_minus1) < 0.05),
                  'explicit_brake_stops': bool(abs(v_brake) < 0.05)},
        'control_hz': round(1.0 / (env.substeps * env.dt), 3),
        'dt': float(env.dt), 'substeps': int(env.substeps),
        'action_dims': {'learner': wheelleg_env.ACT_DIM,
                        'ctrl': wheelleg_env.CTRL_DIM},
    }
    out.write_text(json.dumps(dims, indent=2, ensure_ascii=False))
    print(json.dumps({k: dims[k] for k in ('wheel_radius_m', 'wheel_width_m', 'track_m',
                                           'wheelbase_m', 'belly_clearance_m',
                                           'trunk_has_collision_geom')}, ensure_ascii=False))
    print('brake:', dims['brake'])
    print('->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
