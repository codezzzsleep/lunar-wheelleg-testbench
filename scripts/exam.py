"""
考场运行器：把一个处理好的障碍物放进月面场景，让轮腿机器人开过去，判分。

判据（全部显式定义，写进每条记录）：

  completed  机体中心 x ≥ obstacle_x + 障碍半深 + CLEARANCE，且全程倾角未超 TIP_DEG
  tipped     任一时刻倾角 > TIP_DEG
  stuck      最后一 STUCK_WINDOW 秒内位移 < STUCK_EPS
  timeout    限时内既没完成也没倾覆、且还在动
  precheck_failed  资产本身不合格（**不是**机器人的失败）
  ERROR      仿真/加载异常（**不是**物理结果）

资产解析、路径约定与哈希统一由 runio.resolve_asset 完成：预检、哈希、XML 加载
都用同一份文件列表，避免"哈希算的文件"与"实际参与仿真的文件"不一致。
"""
import json
import pathlib
import sys
import time
import traceback

import numpy as np
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import controllers
import runio
from build_scene import moon_scene_xml, DEFAULT_GRAVITY, DEFAULT_FRICTION
from drive_test import ids, LEG, STANCE, STANCE_HIGH

WHEEL_R = 0.086
TIP_DEG = 75.0
STUCK_WINDOW = 3.0
STUCK_EPS = 0.10
CLEARANCE = 0.25
PRE_CHECK_SECONDS = 0.02

KP, KD = 150.0, 5.0
WHEEL_KP = 1.2
WHEEL_TORQUE_MAX = 15.0
LEG_TORQUE_MAX = 45.0


def control_fingerprint():
    """所有会改变 trial 结果的控制与判据参数，参与运行身份。"""
    return {'kp': KP, 'kd': KD, 'wheel_kp': WHEEL_KP,
            'wheel_torque_max': WHEEL_TORQUE_MAX, 'leg_torque_max': LEG_TORQUE_MAX,
            'wheel_r': WHEEL_R, 'tip_deg': TIP_DEG, 'stuck_window': STUCK_WINDOW,
            'stuck_eps': STUCK_EPS, 'clearance': CLEARANCE,
            'precheck_seconds': PRE_CHECK_SECONDS,
            'stance_low': dict(STANCE), 'stance_high': dict(STANCE_HIGH),
            'controllers': sorted(controllers.REGISTRY) if hasattr(controllers, 'REGISTRY')
            else ['hold', 'step', 'adapt']}


def scene_fingerprint(gravity=DEFAULT_GRAVITY, friction=DEFAULT_FRICTION):
    return {'gravity': gravity, 'friction': friction, 'default_timestep': 0.002}


# ------------------------------------------------------------------ 场景组装

def compose_xml(part_paths, y_offset=0.0, obstacle_x=2.0,
                gravity=DEFAULT_GRAVITY, friction=DEFAULT_FRICTION):
    """part_paths 为 runio 解析出的**实际文件列表**；None 表示平地基线。"""
    xml = moon_scene_xml(gravity=gravity, friction=friction)
    if part_paths is None:
        return xml
    assets, geoms = [], []
    for i, p in enumerate(part_paths):
        assets.append(f'<mesh name="obs{i}" file="{_xml_attr(p)}"/>')
        geoms.append(f'<geom type="mesh" mesh="obs{i}" rgba=".72 .56 .36 1" '
                     f'friction="{_xml_attr(friction)}" contype="1" conaffinity="1"/>')
    block = (f'\n    <body name="obstacle" pos="{obstacle_x:.4f} {y_offset:.4f} 0">'
             f'{"".join(geoms)}</body>')
    xml = xml.replace('</worldbody>', block + '\n  </worldbody>')
    xml = xml.replace('<asset>', '<asset>' + ''.join(assets))
    return xml


def _xml_attr(s):
    """路径与数值都可能含空格或特殊字符，属性值统一转义。"""
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


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

def _base_record(asset_dir, resolved, controller, stance, y_offset, obstacle_x,
                 gravity, friction, seconds):
    flat = asset_dir is None
    man = (resolved or {}).get('manifest') or {}
    name = pathlib.Path(asset_dir).name if asset_dir else 'flat'
    return {
        'asset_id': 'flat' if flat else (man.get('asset_id') or name),
        'asset_dir_name': name,
        'family': 'flat' if flat else (man.get('family') or name),
        'source_kind': 'none' if flat else (man.get('source_kind') or 'unknown'),
        'shape': 'none' if flat else (man.get('shape') or 'mesh'),
        'collision_sha': (resolved or {}).get('collision_sha'),
        'path_mode': (resolved or {}).get('path_mode'),
        'dimensions': ({k: man.get(k) for k in
                        ('height_m', 'width_x_m', 'width_y_m', 'rel_height',
                         'rel_width', 'concavity', 'coacd_parts')} if man else None),
        'controller': controller, 'stance': stance, 'y_offset': y_offset,
        'obstacle_x': obstacle_x, 'gravity': gravity, 'friction': friction,
        'time_limit_s': seconds, 'timestep': None,
        'control': {'kp': KP, 'kd': KD, 'wheel_kp': WHEEL_KP,
                    'wheel_torque_max': WHEEL_TORQUE_MAX,
                    'leg_torque_max': LEG_TORQUE_MAX, 'clearance': CLEARANCE,
                    'tip_deg': TIP_DEG, 'stuck_window': STUCK_WINDOW,
                    'stuck_eps': STUCK_EPS},
    }


def _fail(base, status, reason, detail=None):
    return {**base, 'status': status, 'reason': reason,
            'outcome': status, 'detail': detail,
            'contact_any': None, 'contact_wheel': None,
            'first_contact_s': None, 'first_wheel_contact_s': None,
            'final_x': None, 'distance_m': None, 'max_tilt_deg': None,
            'sim_seconds': 0.0, 'wall_seconds': 0.0, 'brain': None}


def run(asset_dir, stance='low', controller='hold', y_offset=0.0,
        obstacle_x=2.0, seconds=18.0, v_target=1.0, ramp=2.0,
        gravity=DEFAULT_GRAVITY, friction=DEFAULT_FRICTION,
        on_frame=None, frame_fps=30):
    flat = asset_dir is None
    if flat:
        resolved = {'ok': True, 'reason': 'flat_baseline', 'manifest': None,
                    'part_paths': None, 'collision_sha': None, 'path_mode': None}
    else:
        resolved = runio.resolve_asset(asset_dir)

    base = _base_record(asset_dir, resolved, controller, stance, y_offset,
                        obstacle_x, gravity, friction, seconds)
    if not resolved['ok']:
        return _fail(base, 'precheck_failed', resolved['reason'],
                     {'missing': resolved.get('missing'),
                      'path_mode': resolved.get('path_mode')})

    man = resolved['manifest'] or {}
    try:
        xml = compose_xml(resolved['part_paths'], y_offset=y_offset,
                          obstacle_x=obstacle_x, gravity=gravity, friction=friction)
        m = mujoco.MjModel.from_xml_string(xml)
        d = mujoco.MjData(m)
    except Exception as e:
        return _fail(base, 'ERROR', 'model_load_failed',
                     {'exception': type(e).__name__, 'message': str(e)[:400],
                      'traceback': traceback.format_exc()[-800:]})

    try:
        return _simulate(m, d, resolved, base, stance, controller, y_offset,
                         obstacle_x, seconds, v_target, ramp,
                         on_frame=on_frame, frame_fps=frame_fps)
    except Exception as e:
        return _fail(base, 'ERROR', 'simulation_exception',
                     {'exception': type(e).__name__, 'message': str(e)[:400],
                      'traceback': traceback.format_exc()[-800:]})


def _simulate(m, d, resolved, base, stance, controller, y_offset, obstacle_x,
              seconds, v_target, ramp, on_frame=None, frame_fps=30):
    flat = resolved['part_paths'] is None
    man = resolved['manifest'] or {}
    J = ids(m)
    obs = obstacle_geom_ids(m) if not flat else set()
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

    # 出生穿模：一开始就与障碍物接触，说明摆放/尺寸有问题
    if not flat:
        for _ in range(int(PRE_CHECK_SECONDS / dt)):
            mujoco.mj_step(m, d)
            for c in d.contact[:d.ncon]:
                if (c.geom1 in obs and c.geom2 in robot_geoms) or \
                   (c.geom2 in obs and c.geom1 in robot_geoms):
                    if d.qpos[0] < obstacle_x - 0.6:
                        return _fail(base, 'precheck_failed', 'spawn_penetration',
                                     {'x': round(float(d.qpos[0]), 3)})
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
    outcome = reason = None

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
    print(json.dumps(run(a.asset, stance=a.stance, controller=a.controller,
                         y_offset=a.y_offset), indent=2, ensure_ascii=False))
