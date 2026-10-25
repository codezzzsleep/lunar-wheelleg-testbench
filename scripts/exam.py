"""
考场运行器：把一个已处理好的障碍物放进月面场景，让轮腿机器人开过去，判分。

判分（与计划书一致）：
  完成 = 在限时内到达终点且未倾覆
  倾覆 / 卡住 / 超时 = 三类失败，各存证据

用法：
  python scripts/exam.py --asset assets/processed/cargo_crate --stance low --distance 2.0
"""
import argparse, json, pathlib, sys, time
import numpy as np
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from drive_test import ids, LEG, STANCE, STANCE_HIGH
from build_scene import build as build_base

GO2W_DIR = pathlib.Path('vendor/unitree_mujoco/unitree_robots/go2w')
WHEEL_R = 0.086


def compose_xml(asset_dir, out_xml):
    """go2w + 月面 + 障碍物（静态，多块凸包拼成一个 body）。"""
    base = pathlib.Path(build_base())          # 已含重力与地面的 moon_flat.xml
    xml = base.read_text()
    man = json.loads((pathlib.Path(asset_dir) / 'manifest.json').read_text())
    parts = [pathlib.Path(p).resolve() for p in man['parts']]

    assets, geoms = [], []
    for i, p in enumerate(parts):
        assets.append(f'<mesh name="obs{i}" file="{p}"/>')
        geoms.append(f'<geom type="mesh" mesh="obs{i}" rgba=".72 .56 .36 1" '
                     f'friction=".9 .02 .001" contype="1" conaffinity="1"/>')
    block = (
        f'\n    <body name="obstacle" pos="2.0 0 0">'
        f'{"".join(geoms)}</body>'
    )
    xml = xml.replace('</worldbody>', block + '\n  </worldbody>')
    xml = xml.replace('<asset>', '<asset>' + ''.join(assets))
    out = GO2W_DIR / 'moon_exam.xml'
    out.write_text(xml)
    return out, man


def obstacle_geom_ids(m, body='obstacle'):
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, body)
    return {g for g in range(m.ngeom) if m.geom_bodyid[g] == bid}


def run(asset_dir, stance='low', target_x=2.0, seconds=18.0, v_target=1.0, ramp=2.0):
    xml_path, man = compose_xml(asset_dir, None)
    m = mujoco.MjModel.from_xml_path(str(xml_path))
    d = mujoco.MjData(m)
    J = ids(m)
    obs = obstacle_geom_ids(m)

    st = STANCE if stance == 'low' else STANCE_HIGH
    for leg in LEG:
        d.qpos[J[f'{leg}_thigh_joint']['qadr']] = st['thigh']
        d.qpos[J[f'{leg}_calf_joint']['qadr']] = st['calf']
    d.qpos[2] = 0.50
    mujoco.mj_forward(m, d)

    KP = KD = None
    kp, kd = 150.0, 5.0
    start = d.qpos[:2].copy()
    dt = m.opt.timestep
    n = int(seconds / dt)
    tilts, xs = [], []
    first_contact = None
    contact_steps = 0
    outcome = None
    t_contact_wall = None

    t0 = time.time()
    for i in range(n):
        t = i * dt
        for leg in LEG:
            for p in ('hip', 'thigh', 'calf'):
                e = J[f'{leg}_{p}_joint']
                d.ctrl[e['act']] = np.clip(kp * (st[p] - d.qpos[e['qadr']]) - kd * d.qvel[e['vadr']], -45, 45)
            e = J[f'{leg}_wheel_joint']
            vt = v_target * min(1.0, t / ramp)
            d.ctrl[e['act']] = np.clip(1.2 * (vt / WHEEL_R - d.qvel[e['vadr']]), -15, 15)

        mujoco.mj_step(m, d)

        # 接触检测
        hit = False
        for c in d.contact[:d.ncon]:
            if c.geom1 in obs or c.geom2 in obs:
                hit = True
                break
        if hit:
            contact_steps += 1
            if first_contact is None:
                first_contact = round(t, 3)

        w, x, y, z = d.qpos[3:7]
        up = 1 - 2 * (x * x + y * y)
        tilt = float(np.degrees(np.arccos(np.clip(up, -1, 1))))
        tilts.append(tilt)
        xs.append(float(d.qpos[0]))

        if tilt > 75:
            outcome = 'tipped'
            break
        if d.qpos[0] >= target_x + 1.0:
            outcome = 'completed'
            break
    wall = time.time() - t0

    if outcome is None:
        recent = xs[-int(3.0 / dt):]
        moved = max(recent) - min(recent) if recent else 0
        outcome = 'stuck' if moved < 0.1 else 'timeout'

    return {
        'asset': str(asset_dir),
        'stance': stance,
        'outcome': outcome,
        'final_x': round(float(d.qpos[0]), 3),
        'distance_m': round(float(d.qpos[0] - start[0]), 3),
        'max_tilt_deg': round(float(max(tilts)), 1),
        'first_contact_s': first_contact,
        'contact_steps': contact_steps,
        'sim_seconds': round(len(tilts) * dt, 2),
        'wall_seconds': round(wall, 2),
        'obstacle': {k: man[k] for k in ('rel_height', 'rel_width', 'concavity',
                                          'coacd_parts', 'hit_part_cap', 'height_m')},
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--asset', required=True)
    ap.add_argument('--stance', default='low', choices=['low', 'high'])
    ap.add_argument('--distance', type=float, default=2.0)
    a = ap.parse_args()
    r = run(a.asset, a.stance, a.distance)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    pathlib.Path('runs').mkdir(exist_ok=True)
    pathlib.Path('runs/gate1_exam.json').write_text(json.dumps(r, indent=2, ensure_ascii=False))
    print('GATE-1 ITEM 3:', 'PASS' if r['first_contact_s'] is not None else 'FAIL')
    raise SystemExit(0 if r['first_contact_s'] is not None else 1)
