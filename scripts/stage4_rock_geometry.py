"""Stage004：真实岩石状态 -> 走廊几何（真值 / 可见表面）。

  .venv/bin/python scripts/stage4_rock_geometry.py runs/v3/states/<sid> [<sid> ...]

真值几何来自 truth/truth_occ.npz（世界坐标体素）；可见几何只来自
observation/visible_points.npy，后缘不可见就保持未知（None）。
"""
import hashlib
import json
import pathlib
import sys

import numpy as np

CORRIDOR_HALF_Y = 0.22
MIN_H = 0.02


def _sha_file(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def corr_profile(state_dir):
    z = np.load(pathlib.Path(state_dir) / 'truth' / 'truth_occ.npz')
    occ, origin, pitch = z['occupied'], z['origin'].astype(float), float(z['pitch'])
    nx, ny, nz = occ.shape
    ys = origin[1] + (np.arange(ny) + 0.5) * pitch
    xs = origin[0] + (np.arange(nx) + 0.5) * pitch
    zs = origin[2] + (np.arange(nz) + 0.5) * pitch
    ysel = np.where(np.abs(ys) <= CORRIDOR_HALF_Y)[0]
    sub = occ[:, ysel, :]                      # x, ycorr, z
    h = np.zeros(nx)
    for i in range(nx):
        col = sub[i]
        if col.any():
            h[i] = zs[np.where(col.any(axis=0))[0].max()] + pitch / 2.0
    return xs, h, occ, origin, pitch


def truth_geometry(state_dir, y_half=CORRIDOR_HALF_Y):
    xs, h, occ, origin, pitch = corr_profile(state_dir)
    wet = np.where(h >= MIN_H)[0]
    if len(wet) == 0:
        return {'valid': False, 'reason': 'no_rock_in_corridor', 'source': 'truth_occ'}
    i0, i1 = int(wet[0]), int(wet[-1])
    face_x = float(xs[i0])
    far_x = float(xs[i1])
    top = h[i0:i1 + 1]
    top_z = float(top.max())
    # 顶面平台度：top 区内窗口均值的最大起伏
    k = max(1, int(0.02 / pitch))
    if len(top) >= k:
        sm = np.convolve(top, np.ones(k) / k, mode='valid')
        flat = float(sm.max() - sm.min())
    else:
        flat = float(top.max() - top.min())
    # 后缘落差：far_x 后 5 cm 内的高度
    j = min(len(xs) - 1, i1 + int(0.05 / pitch))
    back_drop = float(top_z - h[j])
    # y 覆盖：top 区里高度 >=0.7*top_z 的 y 跨度
    zs = origin[2] + (np.arange(occ.shape[2]) + 0.5) * pitch
    zi = int(np.argmin(np.abs(zs - 0.7 * top_z)))
    band = occ[i0:i1 + 1, :, zi:].any(axis=2).any(axis=0)
    yy = np.where(band)[0]
    y_span = (float(yy.max() - yy.min() + 1) * pitch) if len(yy) else 0.0
    return {'valid': True, 'face_x': round(face_x, 4), 'far_x': round(far_x, 4),
            'top_z': round(top_z, 4), 'top_len': round(far_x - face_x, 4),
            'top_flatness': round(flat, 4), 'back_drop_5cm': round(back_drop, 4),
            'y_span_top': round(y_span, 4),
            'source': 'truth_occ', 'truth_occ_sha': str(pathlib.Path(state_dir).parent.name),
            'grid': {'origin': origin.tolist(), 'pitch': pitch}}


def visible_geometry(state_dir):
    p = np.load(pathlib.Path(state_dir) / 'observation' / 'visible_points.npy')
    if p.size == 0:
        return {'valid': False, 'reason': 'no_visible_points', 'source': 'visible_points'}
    sel = np.abs(p[:, 1]) <= CORRIDOR_HALF_Y
    q = p[sel] if sel.any() else p
    face_x = float(q[:, 0].min())
    top_z = float(q[:, 2].max())
    return {'valid': True, 'face_x': round(face_x, 4), 'top_z': round(top_z, 4),
            'far_x': None, 'source': 'visible_points',
            'visible_x_max': round(float(q[:, 0].max()), 4),
            'unknowns': ['far_x', 'landing']}


def main():
    rows = []
    for sd in sys.argv[1:]:
        d = pathlib.Path(sd)
        try:
            t = truth_geometry(d)
            v = visible_geometry(d)
        except Exception as e:  # noqa: BLE001
            t = {'valid': False, 'reason': f'{type(e).__name__}: {e}'}
            v = {'valid': False, 'reason': 'skipped'}
        row = {'state': str(d), 'truth': t, 'visible': v}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    out = pathlib.Path('runs/v3/stage004/rock_geometry_scan.json')
    out.write_text(json.dumps({'rows': rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
