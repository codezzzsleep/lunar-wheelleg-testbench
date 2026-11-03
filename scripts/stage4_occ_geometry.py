"""Stage004：从各臂实际占据提取局部几何，供 derive_skill_params 与适用性判断。"""
import hashlib
import json

import numpy as np

import stage4_geometry as S4G
import stage4_config as S4C

MIN_H = 0.02


def load_occ(path, space_path=None):
    z = np.load(path)
    shell = np.asarray(z['shell'] if 'shell' in z.files else z['occupied'], dtype=bool)
    space = None
    if space_path is not None:
        space = np.asarray(np.load(space_path)['space'], dtype=np.uint8)
    elif 'space' in z.files:
        space = np.asarray(z['space'], dtype=np.uint8)
    origin = np.asarray(z['origin'], dtype=float)
    pitch = float(z['pitch'])
    return shell, space, origin, pitch


def corridor_metrics(shell, space, origin, pitch, cfg):
    half_y = float(cfg['corridor_half_y_m'])
    nx, ny, nz = shell.shape
    ys = origin[1] + (np.arange(ny) + 0.5) * pitch
    xs = origin[0] + (np.arange(nx) + 0.5) * pitch
    zs = origin[2] + (np.arange(nz) + 0.5) * pitch
    ysel = np.where(np.abs(ys) <= half_y)[0]
    sub = shell[:, ysel, :]
    h = np.zeros(nx)
    for i in range(nx):
        col = sub[i]
        if col.any():
            h[i] = zs[np.where(col.any(axis=0))[0].max()] + pitch / 2.0
    wet = np.where(h >= MIN_H)[0]
    if len(wet) == 0:
        return {'valid': False, 'reason': 'no_surface_in_corridor'}
    i0, i1 = int(wet[0]), int(wet[-1])
    face_x, far_x = float(xs[i0]), float(xs[i1])
    top_z = float(h[i0:i1 + 1].max())
    top = h[i0:i1 + 1]
    flat = float(top.max() - top.min())
    # 顶带 y 宽：z >= top-0.02 且 x in [face, far] 的 shell y 跨度
    zsel = np.where(zs >= top_z - 0.02)[0]
    band = shell[i0:i1 + 1][:, :, zsel.min():].any(axis=2).any(axis=0)
    yy = np.where(band)[0]
    y_span = float((yy.max() - yy.min() + 1) * pitch) if len(yy) else 0.0
    # 后缘已知性：far 之后 2-6 cm 的低处是 free 还是 unknown
    far_known = None
    if space is not None:
        j0 = min(nx - 1, i1 + int(0.02 / pitch))
        j1 = min(nx, i1 + int(0.06 / pitch) + 1)
        zlow = np.where(zs <= 0.05)[0]
        reg = space[j0:j1][:, ysel, :][:, :, zlow]
        n_unknown = int((reg == 0).sum())
        n_free = int((reg == 1).sum())
        far_known = bool(n_free > n_unknown)
    back_drop = None
    if far_known:
        j = min(nx - 1, i1 + int(0.05 / pitch))
        back_drop = float(top_z - h[j])
    zs_band = zs[zsel.min():]
    return {'valid': True, 'face_x': round(face_x, 4), 'far_x': round(far_x, 4),
            'top_z': round(top_z, 4), 'top_len': round(far_x - face_x, 4),
            'top_flatness': round(flat, 4), 'y_span_top': round(y_span, 4),
            'back_drop_5cm': None if back_drop is None else round(back_drop, 4),
            'far_known': far_known}


def applicability(m, cfg):
    reasons = []
    if not m.get('valid'):
        return False, ['no_surface_in_corridor']
    if m['y_span_top'] < float(cfg['top_width_min_m']):
        reasons.append(f"top_too_narrow({m['y_span_top']:.3f}<{cfg['top_width_min_m']})")
    if m['top_len'] < float(cfg['top_len_min_m']):
        reasons.append(f"top_too_short({m['top_len']:.3f})")
    lo, hi = cfg['top_z_range_m']
    if not (lo <= m['top_z'] <= hi):
        reasons.append(f"top_z_out_of_range({m['top_z']:.3f})")
    if m['top_flatness'] > float(cfg['flatness_max_m']):
        reasons.append(f"top_not_flat({m['top_flatness']:.3f})")
    if m.get('far_known') is not True:
        reasons.append('far_edge_unknown')
    return (len(reasons) == 0), reasons


def plan_from_metrics(m, source, cfg):
    ok, reasons = applicability(m, cfg)
    obs = {'face_FR': m['face_x'], 'face_FL': m['face_x'], 'top_z': m['top_z'],
           'far_x': (m['far_x'] if m.get('far_known') else None),
           'landing': None, 'source': source}
    gp = S4G.derive_skill_params(obs)
    plan = {'action': 'CLIMB', 'geometry': m, 'applicable': bool(ok and gp['valid']),
            'reject_reasons': reasons + gp['invalid_reasons'],
            'params': gp['params'], 'param_sources': gp['sources'],
            'unknowns': gp['unknowns'], 'source': source}
    blob = json.dumps({'action': 'CLIMB', 'params': plan['params']}, sort_keys=True)
    plan['plan_id'] = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return plan
