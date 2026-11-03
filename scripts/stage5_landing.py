"""Stage005：从 comp_main4 实际几何与机器人 S0 计算左右轮候选落点。"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import mujoco

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import v3_basic_cycle as bc  # noqa: E402
import stage4_config as S4C  # noqa: E402

LEG = bc.LEG
SCENE = ROOT / 'runs/v3/stage005/comp_main4'


def build_spec(scene):
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=scene['far_x'] + 0.6,
                             name='comp_main4_frozen',
                             objects=[{'posed_dir': str(ROOT / scene['collision']['coll_dir'])}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    return spec


def surface_from_occ(path):
    z = np.load(path)
    occ = np.asarray(z['occupied'], bool); origin = np.asarray(z['origin'], float)
    pitch = float(z['pitch'])
    xs = origin[0] + (np.arange(occ.shape[0]) + 0.5) * pitch
    ys = origin[1] + (np.arange(occ.shape[1]) + 0.5) * pitch
    zs = origin[2] + (np.arange(occ.shape[2]) + 0.5) * pitch
    h = np.full((occ.shape[0], occ.shape[1]), np.nan)
    has = occ.any(axis=2)
    ii, jj = np.where(has)
    for i, j in zip(ii, jj):
        h[i, j] = zs[np.where(occ[i, j])[0].max()] + pitch / 2
    return xs, ys, h


def wheel_metrics(xs, ys, h, y_w, edge_dx, proto):
    j = int(np.argmin(np.abs(ys - y_w)))
    band = slice(max(0, j - 8), min(h.shape[1], j + 9))
    col = np.nanmax(h[:, band], axis=1)
    wet = np.where(col >= 0.02)[0]
    if not len(wet):
        return None
    i0 = int(wet[0]); edge = float(xs[i0])
    window = slice(i0, min(h.shape[0], i0 + int(0.18 / (xs[1] - xs[0]))))
    top = float(np.nanmax(col[window]))
    i = int(np.argmin(np.abs(xs - (edge + edge_dx))))
    patch = h[max(0, i - 4):i + 5, max(0, j - 4):j + 5]
    finite = np.isfinite(patch)
    frac_finite = float(finite.mean()) if patch.size else 0.0
    zmed = float(np.median(patch[finite])) if finite.any() else float('nan')
    area = float((np.abs(patch[finite] - zmed) <= 0.01).mean()) if finite.any() else 0.0
    slope = 9.0
    if finite.sum() >= 9:
        ii, jj = np.where(finite)
        A = np.column_stack([ii * (xs[1] - xs[0]), jj * (ys[1] - ys[0]), np.ones(len(ii))])
        coef, *_ = np.linalg.lstsq(A, patch[ii, jj], rcond=None)
        slope = float(np.hypot(coef[0], coef[1]))
    seg = h[i0:i + 1, max(0, j - 1):j + 2]
    gap = float(np.sum(~np.isfinite(seg)) * (xs[1] - xs[0]))
    return {'y': round(float(ys[j]), 4), 'edge_x': round(edge, 4), 'target_x': round(float(xs[i]), 4),
            'z': round(float(zmed), 4), 'top_local': round(top, 4),
            'slope': round(slope, 3), 'finite_frac': round(frac_finite, 3),
            'flat_area_frac': round(area, 3), 'support_gap_m': round(gap, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage005/landing')
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    scene = json.loads((SCENE / 'scene.json').read_text())
    cfg = S4C.load()
    proto_r1 = json.loads((ROOT / 'configs/stage5_landing_protocol_R1.json').read_text())
    th = proto_r1['definitions']['thresholds']
    spec = build_spec(scene)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s']))
    env.reset(seed=0)
    snap = env.save_state()
    (out / 'state.json').write_text(json.dumps({'spec': spec, 'snapshot': snap}, ensure_ascii=False))
    d = env.data
    wheels = {}
    for leg in LEG:
        bid = bc.wheel_body(env, leg)
        p = np.asarray(d.xpos[bid], float)
        wheels[leg] = {'x': round(float(p[0]), 4), 'y': round(float(p[1]), 4),
                       'z': round(float(p[2]), 4)}
    xs, ys, h = surface_from_occ(SCENE / 'composite_occ.npz')
    top_global = float(np.nanmax(h))
    schemes = []
    # S0：按几何为每个轮独立选落点（不是固定 +0.07）
    per_best = {}
    for leg in LEG:
        y_w = wheels[leg]['y']
        j = int(np.argmin(np.abs(ys - y_w)))
        band = slice(max(0, j - 8), min(h.shape[1], j + 9))
        col = np.nanmax(h[:, band], axis=1)
        wet = np.where(col >= 0.02)[0]
        best = None
        if len(wet):
            i0 = int(wet[0])
            for k in range(i0 + int(0.03 / (xs[1] - xs[0])),
                           min(h.shape[0] - 1, i0 + int(0.17 / (xs[1] - xs[0])))):
                m = wheel_metrics(xs, ys, h, y_w, float(xs[k] - xs[i0]), proto_r1)
                if m is None:
                    continue
                ok = (m['finite_frac'] >= th['flat_area_frac_min']
                      and m['slope'] <= th['slope_max']
                      and m['flat_area_frac'] >= th['flat_area_frac_min']
                      and m['support_gap_m'] <= th['support_gap_max_m'])
                score = (0 if ok else 1, m['slope'], -m['flat_area_frac'])
                if best is None or score < best[0]:
                    best = (score, m)
        per_best[leg] = best[1] if best else None
    reasons = []
    for leg, m in per_best.items():
        if m is None:
            reasons.append(f'{leg}_no_surface'); continue
        if m['finite_frac'] < th['flat_area_frac_min']: reasons.append(f'{leg}_finite({m["finite_frac"]})')
        if m['slope'] > th['slope_max']: reasons.append(f'{leg}_slope({m["slope"]})')
        if m['flat_area_frac'] < th['flat_area_frac_min']: reasons.append(f'{leg}_flat_area({m["flat_area_frac"]})')
        if m['support_gap_m'] > th['support_gap_max_m']: reasons.append(f'{leg}_gap({m["support_gap_m"]})')
    schemes.append({'name': 'S0_per_wheel_geometric', 'delta_x': None,
                    'targets': {leg: (m['target_x'] if m else None) for leg, m in per_best.items()},
                    'wheels': per_best, 'applicable': len(reasons) == 0,
                    'reasons': reasons})
    for name, dx in (('S1_edge_plus_007', 0.07), ('S2_edge_plus_010', 0.10)):
        per = {}
        for leg in LEG:
            y_w = wheels[leg]['y']
            m = wheel_metrics(xs, ys, h, y_w, 0.07 if dx is None else dx, proto_r1)
            per[leg] = m
        reasons = []
        for leg, m in per.items():
            if m is None:
                reasons.append(f'{leg}_no_surface'); continue
            if m['finite_frac'] < th['flat_area_frac_min']:
                reasons.append(f'{leg}_finite({m["finite_frac"]})')
            if m['slope'] > th['slope_max']: reasons.append(f'{leg}_slope({m["slope"]})')
            if m['flat_area_frac'] < th['flat_area_frac_min']:
                reasons.append(f'{leg}_flat_area({m["flat_area_frac"]})')
            if m['support_gap_m'] > th['support_gap_max_m']:
                reasons.append(f'{leg}_gap({m["support_gap_m"]})')
        schemes.append({'name': name, 'delta_x': dx, 'wheels': per,
                        'applicable': len(reasons) == 0, 'reasons': reasons})
    res = {'schema': 'stage5-landing/v1', 'scene': 'comp_main4', 's0_state_hash': snap.get('state_hash'),
           'scene_sha': scene['grid']['content_sha'], 'wheels_s0': wheels,
           'top_global': round(top_global, 4), 'face_x': scene['face_x'],
           'far_x': scene['far_x'], 'schemes': schemes,
           'note': 'passable_columns is not used as bearing; each wheel has its own edge and target'}
    (out / 'landing.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'wheels': wheels, 'schemes': [
        (x['name'], x['applicable'], x['reasons']) for x in schemes]}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
