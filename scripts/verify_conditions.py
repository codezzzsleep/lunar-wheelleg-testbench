"""
条件敏感性验收：改条件 -> 物理场景确实改变（用射线实测，不看 spec 数字）。

  .venv/bin/python scripts/verify_conditions.py --out runs/conditions

对每组条件生成一个场景，编译后沿 x/y 射线实测地表，输出：
  · 实测坡度（沿 x）、峰谷差、表面高度的分位数
  · 与声明的 slope/roughness/pit_depth 对照
  · 场景身份哈希（不同条件必须不同）
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scene_compiler as C
import terrain
import wheelleg_env

CASES = [
    ('平地', {'scenario': '巡检区', 'slope': 0.0, 'roughness': 0.0, 'pits': 0, 'obstacles': 1}),
    ('坡 2 度', {'scenario': '坡地', 'slope': 2.0, 'roughness': 0.0, 'pits': 0, 'obstacles': 1}),
    ('坡 5 度', {'scenario': '坡地', 'slope': 5.0, 'roughness': 0.0, 'pits': 0, 'obstacles': 1}),
    ('坡 5 度 + 起伏 0.02', {'scenario': '坡地', 'slope': 5.0, 'roughness': 0.02, 'pits': 0,
                            'obstacles': 1}),
    ('坡 5 度 + 起伏 0.06', {'scenario': '坡地', 'slope': 5.0, 'roughness': 0.06, 'pits': 0,
                            'obstacles': 1}),
    ('坑 1 个 0.02 m', {'scenario': '坡地', 'slope': 0.0, 'roughness': 0.0, 'pits': 1,
                        'pit_depth': 0.02, 'obstacles': 1}),
    ('坑 1 个 0.08 m', {'scenario': '坡地', 'slope': 0.0, 'roughness': 0.0, 'pits': 1,
                        'pit_depth': 0.08, 'obstacles': 1}),
]


def surface(env):
    m, d = env.model, env.data
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'terrain')
    # 二维网格采样：坑可能偏离中线，只测 y=2.5 一条线会看不到
    gx = np.linspace(-2.5, 2.5, 21)
    grid = np.full((len(gx), len(gx)), np.nan)
    for i, yy in enumerate(gx):
        for j, xx in enumerate(gx):
            out = np.array([-1], dtype=np.int32)
            dist = mujoco.mj_ray(m, d, np.array([xx, yy, 6.0]), np.array([0., 0., -1.]),
                                 None, 1, -1, out)
            if dist > 0 and out[0] == gid:
                grid[i, j] = 6.0 - dist
    z_all = grid[np.isfinite(grid)]
    xs = np.linspace(-2.0, 2.0, 41)
    zx, zy = [], []
    for x in xs:
        out = np.array([-1], dtype=np.int32)
        dist = mujoco.mj_ray(m, d, np.array([x, 2.5, 4.0]), np.array([0., 0., -1.]),
                             None, 1, -1, out)
        zx.append(4.0 - dist if dist > 0 and out[0] == gid else np.nan)
        out2 = np.array([-1], dtype=np.int32)
        dist2 = mujoco.mj_ray(m, d, np.array([2.5, x, 4.0]), np.array([0., 0., -1.]),
                              None, 1, -1, out2)
        zy.append(4.0 - dist2 if dist2 > 0 and out2[0] == gid else np.nan)
    zx, zy = np.array(zx), np.array(zy)
    slope_x = np.degrees(np.arctan((zx[-1] - zx[0]) / (xs[-1] - xs[0])))
    slope_y = np.degrees(np.arctan((zy[-1] - zy[0]) / (xs[-1] - xs[0])))
    # 局部粗糙度：二阶差分的均方根（与整体坡度无关）
    rough = float(np.sqrt(np.nanmean(np.diff(zx, 2) ** 2))) if np.isfinite(zx).sum() > 3 else 0.0
    return {'grid_z_min': round(float(z_all.min()), 4) if z_all.size else None,
            'grid_z_max': round(float(z_all.max()), 4) if z_all.size else None,
            'slope_x_deg': round(float(slope_x), 2),
            'slope_y_deg': round(float(slope_y), 2),
            'roughness_rms_m': round(rough, 5),
            'z_min': round(float(z_all.min()), 4) if z_all.size else None,
            'z_max': round(float(z_all.max()), 4) if z_all.size else None,
            'z_profile': [None if not np.isfinite(v) else round(float(v), 3) for v in zx]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for label, cond in CASES:
        specs = C.compile_scenes(cond, 900, 1)
        spec = specs[0]
        env = wheelleg_env.WheelLegEnv(spec)
        s = surface(env)
        row = {'label': label, 'condition': cond, 'scene': spec['name'],
               'scene_id': terrain.scene_identity(spec),
               'declared': spec['terrain'], 'zmax': env._terrain_meta['zmax'],
               'components': env._terrain_meta['components'], 'measured': s}
        rows.append(row)
        print(f"{label:22s} 声明坡 {cond.get('slope', 0):4.1f}° 实测 {s['slope_x_deg']:5.2f}°  "
              f"粗糙度 RMS {s['roughness_rms_m']:.4f}  z∈[{s['z_min']},{s['z_max']}]  "
              f"id={row['scene_id']}")

    # 判定：不同条件的场景身份必须不同；坡度条件必须带来对应实测坡度
    ids = [r['scene_id'] for r in rows]
    uniq = len(set(ids)) == len(ids)
    slope_ok = all(
        abs(r['measured']['slope_x_deg'] - float(r['condition'].get('slope', 0))) < 0.35
        for r in rows)
    rough_vals = [(r['label'], r['measured']['roughness_rms_m']) for r in rows
                  if 'roughness' in r['condition']]
    rough_ok = all(rough_vals[i][1] < rough_vals[j][1]
                   for i in range(len(rough_vals)) for j in range(len(rough_vals))
                   if '0.02' in rough_vals[i][0] and '0.06' in rough_vals[j][0])
    pit_vals = [(r['label'], round(r['measured']['z_max'] - r['measured']['z_min'], 4))
                for r in rows if 'pit_depth' in r['condition']]
    pit_ok = len(pit_vals) == 2 and pit_vals[1][1] > pit_vals[0][1]

    verdict = {'all_scene_ids_unique': uniq,
               'slope_matches_declared': slope_ok,
               'roughness_increases': rough_ok,
               'pit_depth_increases': pit_ok,
               'roughness_pairs': rough_vals, 'pit_pairs': pit_vals}
    (out / 'conditions.json').write_text(json.dumps(
        {'cases': rows, 'verdict': verdict}, indent=2, ensure_ascii=False))
    print('\n判定:', json.dumps(verdict, ensure_ascii=False))
    ok = uniq and slope_ok and rough_ok and pit_ok
    print('总体:', '通过' if ok else '不通过')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
