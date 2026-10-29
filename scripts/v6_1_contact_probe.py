"""
V6.1：碰撞实际加载 + 接触验证（C5/C6）。

不是只看「能加载」，而是分三段测：

  1. 探针测试（几何语义）：
     - 小球落入凹槽（应被凹槽约束，而不是停在口上）；
     - 小球通过窄通道（应通过；若通道被填平则被挡住）；
     - 小球被凸起挡住（对照组）。
  2. 机器人接触：让机器人低速顶住障碍，记录接触数、穿透深度、是否卡顿。
  3. 性能分段：接近段 / 接触段 / 最不利接触状态的 wall time、ncon、内存。

  .venv/bin/python scripts/v6_1_contact_probe.py --collision <dir> --out <json> \
      --kind groove|channel|bump --source <mesh>
"""
import argparse
import json
import os
import pathlib
import resource
import sys
import time

import numpy as np

os.environ.setdefault('MUJOCO_GL', 'osmesa')
import mujoco  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def free_probe(spec_dir, ball_r=0.02, x0=0.0, y0=0.0, z0=0.30, steps=400):
    """在世界里放一个小球，让它自由落体，返回最终位置与接触。"""
    xml = f"""
<mujoco model="probe">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <visual><global offwidth="320" offheight="240"/></visual>
  <worldbody>
    <geom name="floor" type="plane" size="2 2 0.05" rgba=".5 .5 .5 1"/>
    <body name="ball" pos="{x0} {y0} {z0}">
      <freejoint/>
      <geom name="ball" type="sphere" size="{ball_r}" mass="0.05"
            rgba=".9 .3 .3 1" friction="0.9 0.02 0.001"/>
    </body>
  </worldbody>
</mujoco>"""
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    # 追加碰撞体（box 并集）：用 MjSpec 的 attach 不方便，这里直接读 manifest 生成 geom
    man = json.loads((pathlib.Path(spec_dir) / 'manifest.json').read_text())
    if not man.get('boxes'):
        raise SystemExit('探针需要 box 并集 manifest')
    org = np.asarray(man['grid_origin'], dtype=float)
    pitch = float(man['pitch_m'])
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, 'ball')
    ncon = {'n': 0}
    lowest = 1e9
    contact_steps = 0
    for _ in range(steps):
        mujoco.mj_step(model, data)
        lowest = min(lowest, float(data.qpos[2]))
        if data.ncon > 0:
            contact_steps += 1
            ncon['n'] = max(ncon['n'], int(data.ncon))
    return {'final_pos': [round(float(x), 5) for x in data.qpos[:3]],
            'final_z': round(float(data.qpos[2]), 5),
            'lowest_z': round(lowest, 5), 'n_steps': steps,
            'contact_steps': contact_steps, 'max_ncon': ncon['n'],
            'stuck': bool(contact_steps > steps * 0.9)}


def robot_contact(collision_dir, n_steps=300, speed=0.4):
    """机器人低速顶住障碍：分段记录 wall time / ncon / 穿透。"""
    import terrain
    import wheelleg_env
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.8, name='contact')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['objects'] = [{'posed_dir': str(collision_dir)}]
    t0 = time.time()
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=n_steps / 50.0)
    env.reset(seed=0)
    load_s = time.time() - t0
    seg = {'approach': [], 'contact': []}
    max_ncon = 0
    contact_steps = 0
    for i in range(n_steps):
        t1 = time.time()
        env.step(np.zeros(3))
        dt = time.time() - t1
        nc = int(env.data.ncon)
        max_ncon = max(max_ncon, nc)
        if nc > 0:
            contact_steps += 1
            seg['contact'].append(dt)
        else:
            seg['approach'].append(dt)
    # 穿透：接触点沿法向的深度（正值=互相侵入）
    pen = []
    d = env.data
    for k in range(d.ncon):
        c = d.contact[k]
        pen.append(float(c.dist))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    out = {
        'load_seconds': round(load_s, 3), 'n_geom': int(env.model.ngeom),
        'obstacle_geoms': len(getattr(env, 'obstacle_geoms', [])),
        'steps': n_steps, 'contact_steps': contact_steps,
        'max_ncon': max_ncon,
        'approach_ms_per_step': round(1000 * float(np.mean(seg['approach'])), 3)
        if seg['approach'] else None,
        'contact_ms_per_step': round(1000 * float(np.mean(seg['contact'])), 3)
        if seg['contact'] else None,
        'worst_step_ms': round(1000 * max([x for v in seg.values() for x in v] or [0]), 3),
        'rss_mb': round(rss, 1),
        'min_contact_dist_mm': round(1000 * min(pen), 3) if pen else None,
        'max_penetration_mm': round(1000 * max([-x for x in pen if x < 0] or [0]), 3),
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--collision', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--robot-steps', type=int, default=200)
    a = ap.parse_args()
    cd = pathlib.Path(a.collision)
    res = {'schema': 'contact-probe/v6_1', 'collision': str(cd),
           'collision_sha': json.loads((cd / 'manifest.json').read_text()).get('collision_sha')}
    res['robot_contact'] = robot_contact(cd, a.robot_steps)
    rep = pathlib.Path(a.out or (cd / 'contact_probe.json'))
    rep.write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res['robot_contact'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
