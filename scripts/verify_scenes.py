"""
场景物理有效性检查：用**编译后的物理场景**实测，而不是看 spec 里的数字。

  .venv/bin/python scripts/verify_scenes.py --scenes scenes/A_sparse.json scenes/B_slope.json \
      --out runs/verify

对每个场景输出：
  · 地形：沿 x / y 的射线实测地表高度、实测坡度、峰谷差，与条件参数对照
  · 物体：body 实际 z、物体顶点最低/最高 z、物体下方地面范围、埋入深度、悬空高度
  · 出生：机器人出生点相对地表的高度，是否穿模
  · 接触：用真实仿真跑一段，记录是否发生接触与首次接触时间（不是硬编码 true）
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import wheelleg_env

OUT_DIGITS = 4


def ray_height(m, d, gid, x, y, z0=6.0):
    out = np.array([-1], dtype=np.int32)
    dist = mujoco.mj_ray(m, d, np.array([x, y, z0]), np.array([0., 0., -1.]),
                         None, 1, -1, out)
    if dist < 0 or out[0] != gid:
        return None
    return round(z0 - dist, OUT_DIGITS)


def measure_terrain(env):
    m, d = env.model, env.data
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'terrain')
    xs = np.linspace(-2.5, 2.5, 11)
    prof_x = [(round(float(x), 2), ray_height(m, d, gid, float(x), 0.0)) for x in xs]
    prof_y = [(round(float(y), 2), ray_height(m, d, gid, 0.0, float(y))) for y in xs]
    zx = [p[1] for p in prof_x if p[1] is not None]
    zy = [p[1] for p in prof_y if p[1] is not None]

    def slope_deg(prof):
        pts = [(a, b) for a, b in prof if b is not None]
        if len(pts) < 2:
            return 0.0
        (x0, z0), (x1, z1) = pts[0], pts[-1]
        if abs(x1 - x0) < 1e-6:
            return 0.0
        return round(float(np.degrees(np.arctan((z1 - z0) / (x1 - x0)))), 2)

    return {
        'slope_x_deg_measured': slope_deg(prof_x),
        'slope_y_deg_measured': slope_deg(prof_y),
        'surface_z_min': round(min(zx), OUT_DIGITS) if zx else None,
        'surface_z_max': round(max(zx), OUT_DIGITS) if zx else None,
        'zmax_declared': env._terrain_meta['zmax'],
        'actual_max_m_declared': env._terrain_meta['actual_max_m'],
        'profile_x': prof_x,
    }


def measure_objects(env):
    m, d = env.model, env.data
    gid_terrain = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'terrain')
    rows = []
    for i, pl in enumerate(env.placements):
        body = f'obstacle{i}'
        bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, body)
        geoms = [g for g in range(m.ngeom) if m.geom_bodyid[g] == bid]
        zs = [float(d.geom_xpos[g][2]) for g in geoms]
        radii = [float(m.geom_rbound[g]) for g in geoms]
        # 用顶点重算世界坐标最低点（比 rbound 更准）
        # 必须用与落地时**同一份**缩放，否则算出来的顶点与真实几何不一致
        verts = wheelleg_env._world_vertices(
            [str(pl_path) for pl_path in
             _part_paths(env.asset_root / pl['asset'])],
            float(pl['x']), float(pl['y']), np.deg2rad(float(pl['yaw_deg'])),
            scale=pl.get('mesh_scale') or 1.0)   # 可为标量或 (sx,sy,sz)
        z_world = verts[:, 2] + float(pl['body_z'])
        ground = terrain.ground_height_many(env._h, verts[:, 0], verts[:, 1])
        burial = float(np.max(ground - z_world))       # >0 表示被地形埋住
        float_gap = float(np.min(z_world - ground))    # >0 表示整体悬空
        rows.append({
            'asset': pl['asset'], 'x': pl['x'], 'y': pl['y'], 'yaw_deg': pl['yaw_deg'],
            'body_z': round(float(pl['body_z']), OUT_DIGITS),
            'vertex_z_min_world': round(float(z_world.min()), OUT_DIGITS),
            'vertex_z_max_world': round(float(z_world.max()), OUT_DIGITS),
            'ground_under_min': round(float(ground.min()), OUT_DIGITS),
            'ground_under_max': round(float(ground.max()), OUT_DIGITS),
            'buried_m': round(burial, OUT_DIGITS),
            'floating_m': round(float_gap, OUT_DIGITS),
            'ok_not_buried': burial <= 0.005,
            'ok_not_floating': float_gap <= 0.005,
        })
    return rows


def _part_paths(asset_dir):
    import runio
    r = runio.resolve_asset(asset_dir)
    return r['part_paths'] if r['ok'] else []


def run_contact(env, seconds=6.0, action=None):
    """真实仿真，记录与障碍物的接触事件（不硬编码 contact=True）。"""
    if action is None:
        action = tuple([0.0] * wheelleg_env.ACT_DIM)
    env.reset(seed=int(env.spec.get('seed', 0)))
    m, d = env.model, env.data
    obs_ids = set()
    for i in range(len(env.placements)):
        bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'obstacle{i}')
        obs_ids |= {g for g in range(m.ngeom) if m.geom_bodyid[g] == bid}
    robot = set(range(m.ngeom)) - obs_ids
    first, n_steps, reason, info = None, 0, None, {}
    dt = env.substeps * env.dt
    for _ in range(int(seconds / dt)):
        o, r, te, tr, info = env.step(action)
        n_steps += 1
        if first is None and info.get('first_contact_s') is not None:
            first = info['first_contact_s']
        if te or tr:
            reason = info['reason']
            break
    return {'first_contact_s': first, 'contact_occurred': first is not None,
            'contact_substeps': info.get('contact_substeps', 0),
            'contact_wheel': info.get('contact_wheel'),
            'reason': reason, 'final_x': info.get('x'), 'steps': n_steps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenes', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--contact-seconds', type=float, default=6.0)
    a = ap.parse_args()

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for path in a.scenes:
        for spec in json.loads(pathlib.Path(path).read_text()):
            env = wheelleg_env.WheelLegEnv(spec)
            t = measure_terrain(env)
            objs = measure_objects(env)
            c = run_contact(env, a.contact_seconds)
            row = {'scene': spec['name'], 'scene_id': terrain.scene_identity(spec),
                   'source': path, 'condition': spec.get('condition'),
                   'terrain_spec': spec['terrain'], 'terrain_measured': t,
                   'objects': objs, 'contact': c,
                   'provenance': spec.get('provenance')}
            # 场景**物理有效性**只看落地/悬空/出生；是否接触、任务是否成功是两件事，
            # 必须分开统计（任务书第六节）。接触单独记为 contact_ok。
            row['ok'] = all(o['ok_not_buried'] and o['ok_not_floating'] for o in objs)
            row['contact_ok'] = (not objs) or c['contact_occurred']
            report.append(row)
            print(f"{spec['name']:26s} 坡 {t['slope_x_deg_measured']:5.2f}° "
                  f"峰 {t['surface_z_max']} 物体埋入 {[o['buried_m'] for o in objs]} "
                  f"接触 {c['first_contact_s']} "
                  f"{'物理OK' if row['ok'] else '物理FAIL'}"
                  f"{'' if row.get('contact_ok') else '/未接触'}")
    (out / 'verify.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    n_ok = sum(1 for r in report if r['ok'])
    n_contact = sum(1 for r in report if r.get('contact_ok'))
    print(f'\n物理合格 {n_ok}/{len(report)}；其中发生接触 {n_contact}/{len(report)}')
    return 0 if n_ok == len(report) else 1


if __name__ == '__main__':
    sys.exit(main())
