"""
考场运行器：把一个处理好的障碍物放进月面场景，让轮腿机器人开过去，判分。

判据（全部显式定义，写进每条记录）：

  completed  机体中心 x ≥ obstacle_x + 障碍半深 + CLEARANCE，且全程倾角未超 TIP_DEG
  tipped     任一时刻倾角 > TIP_DEG
  stuck      最后一 STUCK_WINDOW 秒内位移 < STUCK_EPS
  timeout    限时内既没完成也没倾覆、且还在动
  precheck_failed  资产本身不合格，**不是**机器人的失败

注意：
  · 「完成」只检查机体中心是否越过障碍后方一段净空，不等于整机完全通过。
  · 「接触」分两级：contact_any（任意机体 geom 碰到障碍）与
    contact_wheel（只有四个轮子的碰撞 geom 碰到）。报告主指标用 contact_wheel。
"""
import json
import pathlib
import sys
import time

import numpy as np
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import controllers
from build_scene import moon_scene_xml, DEFAULT_GRAVITY, DEFAULT_FRICTION
from drive_test import ids, LEG, STANCE, STANCE_HIGH

WHEEL_R = 0.086
TIP_DEG = 75.0
STUCK_WINDOW = 3.0
STUCK_EPS = 0.10
CLEARANCE = 0.25          # 障碍后方净空（米）
PRE_CHECK_SECONDS = 0.02   # 出生碰撞检测窗口

KP, KD = 150.0, 5.0
WHEEL_KP = 1.2
WHEEL_TORQUE_MAX = 15.0
LEG_TORQUE_MAX = 45.0


# ------------------------------------------------------------------ 资产预检

def precheck_asset(asset_dir):
    """返回 (ok, reason, manifest)。不合格的资产绝不能算成机器人的失败。"""
    d = pathlib.Path(asset_dir)
    mf = d / 'manifest.json'
    if not mf.exists():
        return False, 'manifest_missing', None
    try:
        man = json.loads(mf.read_text())
    except Exception as e:
        return False, f'manifest_unreadable:{e}', None
    if not man.get('pass', False):
        return False, 'manifest_pass_false', man
    parts = man.get('parts') or []
    if not parts:
        return False, 'no_collision_parts', man
    for p in parts:
        if not pathlib.Path(p).exists():
            return False, f'missing_part:{pathlib.Path(p).name}', man
    try:
        h = float(man['height_m'])
        w = float(man['rel_width'])
    except Exception:
        return False, 'bad_dimensions', man
    if not (np.isfinite(h) and np.isfinite(w)) or h <= 0 or w <= 0:
        return False, 'nonpositive_dimensions', man
    return True, 'ok', man


# ------------------------------------------------------------------ 场景组装

def compose_xml(asset_dir, man, y_offset=0.0, obstacle_x=2.0,
                gravity=DEFAULT_GRAVITY, friction=DEFAULT_FRICTION):
    """在内存里拼出完整 XML 字符串（不写任何共享文件）。man=None 表示平地基线。"""
    xml = moon_scene_xml(gravity=gravity, friction=friction)
    if man is None:
        return xml
    assets, geoms = [], []
    for i, p in enumerate(man['parts']):
        abs_p = str(pathlib.Path(p).resolve())
        assets.append(f'<mesh name="obs{i}" file="{abs_p}"/>')
        geoms.append(f'<geom type="mesh" mesh="obs{i}" rgba=".72 .56 .36 1" '
                     f'friction="{friction}" contype="1" conaffinity="1"/>')
    block = (f'\n    <body name="obstacle" pos="{obstacle_x:.4f} {y_offset:.4f} 0">'
             f'{"".join(geoms)}</body>')
    xml = xml.replace('</worldbody>', block + '\n  </worldbody>')
    xml = xml.replace('<asset>', '<asset>' + ''.join(assets))
    return xml


def _geom_ids_by_body(m, body_name):
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, body_name)
    if bid < 0:
        return set()
    return {g for g in range(m.ngeom) if m.geom_bodyid[g] == bid}


def obstacle_geom_ids(m, body='obstacle'):
    return _geom_ids_by_body(m, body)


def wheel_geom_ids(m):
    out = set()
    for leg in LEG:
        out |= _geom_ids_by_body(m, f'{leg}_wheel_link')
    return out


# ------------------------------------------------------------------ 单次试验

def run(asset_dir, stance='low', controller='hold', y_offset=0.0,
        obstacle_x=2.0, seconds=18.0, v_target=1.0, ramp=2.0,
        gravity=DEFAULT_GRAVITY, friction=DEFAULT_FRICTION,
        on_frame=None, frame_fps=30):
    flat = asset_dir is None
    if flat:
        ok, reason, man = True, 'flat_baseline', None
    else:
        ok, reason, man = precheck_asset(asset_dir)
    base = {
        'asset_id': 'flat' if flat else (man.get('asset_id') or pathlib.Path(asset_dir).name),
        'family': 'flat' if flat else (man.get('family') or pathlib.Path(asset_dir).name),
        'source_kind': 'none' if flat else man.get('source_kind', 'unknown'),
        'shape': 'none' if flat else man.get('shape', 'mesh'),
        'collision_sha': man.get('collision_sha') if man else None,
        'dimensions': {k: man.get(k) for k in
                       ('height_m', 'width_x_m', 'width_y_m', 'rel_height',
                        'rel_width', 'concavity', 'coacd_parts')} if man else None,
        'controller': controller, 'stance': stance, 'y_offset': y_offset,
        'obstacle_x': obstacle_x, 'gravity': gravity, 'friction': friction,
        'timestep': None, 'time_limit_s': seconds,
        'control': {'kp': KP, 'kd': KD, 'wheel_kp': WHEEL_KP,
                    'v_target': v_target, 'ramp_s': ramp},
    }
    if not ok:
        return {**base, 'status': 'precheck_failed', 'reason': reason,
                'outcome': 'precheck_failed', 'contact_any': False,
                'contact_wheel': False, 'first_contact_s': None,
                'first_wheel_contact_s': None, 'final_x': None, 'distance_m': None,
                'max_tilt_deg': None, 'brain': None}

    xml = compose_xml(asset_dir, man, y_offset=y_offset, obstacle_x=obstacle_x,
                      gravity=gravity, friction=friction)
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    J = ids(m)
    obs = obstacle_geom_ids(m)
    wheels = wheel_geom_ids(m)
    robot_geoms = set(range(m.ngeom)) - obs

    st = STANCE if stance == 'low' else STANCE_HIGH
    brain = controllers.make(controller, st)
    for leg in LEG:
        d.qpos[J[f'{leg}_thigh_joint']['qadr']] = st['thigh']
        d.qpos[J[f'{leg}_calf_joint']['qadr']] = st['calf']
    d.qpos[2] = 0.50
    mujoco.mj_forward(m, d)

    dt = m.opt.timestep
    base['timestep'] = dt

    # 出生穿模检查：一开始就贴着障碍物，说明场景摆放有问题
    for _ in range(int(PRE_CHECK_SECONDS / dt)):
        mujoco.mj_step(m, d)
        for c in d.contact[:d.ncon]:
            if (c.geom1 in obs and c.geom2 in robot_geoms) or \
               (c.geom2 in obs and c.geom1 in robot_geoms):
                if d.qpos[0] < obstacle_x - 0.6:
                    return {**base, 'status': 'precheck_failed',
                            'reason': 'spawn_penetration', 'outcome': 'precheck_failed',
                            'contact_any': True, 'contact_wheel': False,
                            'first_contact_s': 0.0, 'first_wheel_contact_s': None,
                            'final_x': round(float(d.qpos[0]), 3), 'distance_m': 0.0,
                            'max_tilt_deg': 0.0, 'brain': None}

    # 重新摆好姿态再正式开跑
    for leg in LEG:
        d.qpos[J[f'{leg}_thigh_joint']['qadr']] = st['thigh']
        d.qpos[J[f'{leg}_calf_joint']['qadr']] = st['calf']
    d.qpos[0] = 0.0
    d.qpos[2] = 0.50
    d.qvel[:] = 0
    mujoco.mj_forward(m, d)

    half_depth = 0.0 if flat else float(man.get('width_x_m') or 0.0) / 2.0
    finish_x = obstacle_x + half_depth + CLEARANCE

    start_x = float(d.qpos[0])
    xs, tilts = [], []
    first_contact = first_wheel = None
    contact_steps = wheel_steps = 0
    outcome, reason = None, None
    t_contact = None

    t0 = time.time()
    for i in range(int(seconds / dt)):
        t = i * dt
        tg = brain.targets(t, d.qpos, d.qvel, False)
        for leg in LEG:
            for p in ('hip', 'thigh', 'calf'):
                e = J[f'{leg}_{p}_joint']
                d.ctrl[e['act']] = np.clip(
                    KP * (tg[leg][p] - d.qpos[e['qadr']]) - KD * d.qvel[e['vadr']],
                    -LEG_TORQUE_MAX, LEG_TORQUE_MAX)
            e = J[f'{leg}_wheel_joint']
            vt = v_target * min(1.0, t / ramp) if ramp > 0 else v_target
            boost = brain.wheel_boost() if hasattr(brain, 'wheel_boost') else 1.0
            d.ctrl[e['act']] = np.clip(
                WHEEL_KP * boost * (vt / WHEEL_R - d.qvel[e['vadr']]),
                -WHEEL_TORQUE_MAX, WHEEL_TORQUE_MAX)

        mujoco.mj_step(m, d)

        # 帧回调：回放/渲染走的就是这条控制路径，不另写一套近似逻辑
        if on_frame is not None and frame_fps:
            every = max(1, int(round(1.0 / (frame_fps * dt))))
            if i % every == 0:
                on_frame(t, m, d)

        any_hit = wheel_hit = False
        for c in d.contact[:d.ncon]:
            g1, g2 = c.geom1, c.geom2
            if g1 in obs or g2 in obs:
                other = g2 if g1 in obs else g1
                if other in robot_geoms:
                    any_hit = True
                    if other in wheels:
                        wheel_hit = True
        if any_hit:
            contact_steps += 1
            if first_contact is None:
                first_contact = round(t, 3)
        if wheel_hit:
            wheel_steps += 1
            if first_wheel is None:
                first_wheel = round(t, 3)
        if first_wheel is not None and t_contact is None:
            t_contact = round(t, 3)

        w, x, y, z = d.qpos[3:7]
        up = 1.0 - 2.0 * (x * x + y * y)
        tilt = float(np.degrees(np.arccos(np.clip(up, -1.0, 1.0))))
        tilts.append(tilt)
        xs.append(float(d.qpos[0]))

        if tilt > TIP_DEG:
            outcome, reason = 'tipped', 'tilt_exceeded'
            break
        if d.qpos[0] >= finish_x:
            outcome, reason = 'completed', 'passed_finish_line'
            break

    if outcome is None:
        recent = xs[-int(STUCK_WINDOW / dt):]
        moved = (max(recent) - min(recent)) if recent else 0.0
        outcome = 'stuck' if moved < STUCK_EPS else 'timeout'
        reason = 'no_progress' if outcome == 'stuck' else 'time_limit'

    return {
        **base,
        'status': 'ok',
        'outcome': outcome,
        'reason': reason,
        'finish_x': round(finish_x, 4),
        'final_x': round(float(d.qpos[0]), 3),
        'distance_m': round(float(d.qpos[0]) - start_x, 3),
        'max_tilt_deg': round(float(max(tilts)), 1),
        'sim_seconds': round(len(tilts) * dt, 3),
        'wall_seconds': round(time.time() - t0, 3),
        'contact_any': first_contact is not None,
        'contact_wheel': first_wheel is not None,
        'first_contact_s': first_contact,
        'first_wheel_contact_s': first_wheel,
        'contact_steps': contact_steps,
        'wheel_contact_steps': wheel_steps,
        'brain': brain.stats() if hasattr(brain, 'stats') else None,
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--asset', required=True)
    ap.add_argument('--stance', default='low', choices=['low', 'high'])
    ap.add_argument('--controller', default='hold', choices=['hold', 'step', 'adapt'])
    ap.add_argument('--y-offset', type=float, default=0.0)
    a = ap.parse_args()
    r = run(a.asset, stance=a.stance, controller=a.controller, y_offset=a.y_offset)
    print(json.dumps(r, indent=2, ensure_ascii=False))
