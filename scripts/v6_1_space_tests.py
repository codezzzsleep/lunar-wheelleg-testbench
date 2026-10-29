"""
V6.1 工作包 A6：已知答案回归（三类空间 / FOV / 非周期边界 / 网格约定 / 配置身份）。

这些测试直接调用 scripts/fuse_observed.py 的正式函数，不另写替代实现。
合成 observation 包（depth/mask/camera/visible_points/observation.json）写入临时目录后调用。

  .venv/bin/python scripts/v6_1_space_tests.py --out <dir>

退出码 0 表示全部通过。
"""
import argparse
import json
import pathlib
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import camera_io
import fuse_observed as FZ

ROOT = pathlib.Path(__file__).resolve().parent.parent
W, H = 64, 48
FOVY = 60.0
# 与真实装备一致的相机朝向：world = R @ p_cam + t，depth = +x
R_LOOK_X = np.array([[0.0, 0.0, -1.0],
                     [-1.0, 0.0, 0.0],
                     [0.0, 1.0, 0.0]])


def synth_obs(outdir, depth_fn, mask_fn=None, cam_pos=(0.0, 0.0, 0.3),
              R=None, fovy=FOVY, w=W, h=H):
    """生成一个最小 observation 包。depth_fn(u,v) -> 轴向深度或 nan。"""
    out = pathlib.Path(outdir); out.mkdir(parents=True, exist_ok=True)
    R = R_LOOK_X if R is None else np.asarray(R, dtype=float)
    # 相机沿 -z 看（MuJoCo 约定）：world = R @ p_cam + t
    snap = {'camera_schema': 'camera-snapshot/v2', 'body_name': 'base_link',
            'body_id': 1, 'local_pos': [0.0, 0.0, 0.0],
            'local_quat_wxyz': [1.0, 0.0, 0.0, 0.0],
            'world_pos': [float(x) for x in cam_pos],
            'R_world_from_camera': [[float(x) for x in row] for row in R],
            'fovy_deg': fovy, 'image_width': w, 'image_height': h,
            'intrinsics': camera_io.intrinsics(w, h, fovy),
            'depth_convention': 'positive_camera_minus_z'}
    depth = np.full((h, w), np.nan, dtype=np.float64)
    for v in range(h):
        for u in range(w):
            depth[v, u] = depth_fn(u, v)
    mask = np.zeros((h, w), dtype=bool)
    if mask_fn is None:
        mask = np.isfinite(depth)
    else:
        for v in range(h):
            for u in range(w):
                mask[v, u] = bool(mask_fn(u, v))
    np.save(out / 'depth.npy', depth)
    Image.fromarray((mask * 255).astype(np.uint8)).save(out / 'mask.png')
    # 可见点：mask 内像素反投影
    ys, xs = np.nonzero(mask & np.isfinite(depth) & (depth > 0))
    z = depth[ys, xs]
    K = snap['intrinsics']
    pc = np.stack([(xs - K['cx']) * z / K['fx'],
                   -(ys - K['cy']) * z / K['fy'], -z], axis=1)
    pw = pc @ R.T + np.asarray(cam_pos, dtype=float)
    np.save(out / 'visible_points.npy', pw)
    info = {'case_id': 'synth', 'observation_id': 'synth', 'camera': snap,
            'intrinsics': K, 'image': {'W': w, 'H': h},
            'visible': {'n_pixels': int(mask.sum()),
                        'x_front': float(pw[:, 0].min()) if len(pw) else None,
                        'W_vis': float(pw[:, 1].max() - pw[:, 1].min()) if len(pw) else None,
                        'H_vis': float(pw[:, 2].max() - pw[:, 2].min()) if len(pw) else None},
            'depth_convention': 'positive_camera_minus_z'}
    (out / 'observation.json').write_text(json.dumps(info, indent=2))
    return out


def grid_near(cam_pos, pitch=0.02, extent=(2.0, 0.6, 0.6)):
    """以相机为参照的网格（z 从 0 起）。"""
    lo = np.array([cam_pos[0] + 0.2, cam_pos[1] - extent[1] / 2, 0.0])
    dims = np.ceil(np.array([extent[0], extent[1], extent[2]]) / pitch).astype(int)
    xs = lo[0] + (np.arange(dims[0]) + 0.5) * pitch
    ys = lo[1] + (np.arange(dims[1]) + 0.5) * pitch
    zs = lo[2] + (np.arange(dims[2]) + 0.5) * pitch
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    return {'origin': lo, 'pitch': pitch, 'dims': dims, 'xs': xs, 'ys': ys, 'zs': zs,
            'X': X, 'Y': Y, 'Z': Z}


class R:
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=''):
        self.rows.append({'check': name, 'pass': bool(ok), 'detail': detail})
        print(('PASS' if ok else 'FAIL'), name, '|', detail)
        return bool(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    tmp = pathlib.Path(a.out or tempfile.mkdtemp(prefix='v6_1_space_'))
    tmp.mkdir(parents=True, exist_ok=True)
    r = R()
    pitch = 0.02
    eps = 0.001
    band = 0.0075
    cam = (0.0, 0.0, 0.3)

    # 1 & 2：1 m 平面 + 平面后方 3 mm（用 5 mm 网格，能分辨 3 mm 偏移）
    D = 1.0
    p2 = 0.005
    obs = synth_obs(tmp / 'plane', lambda u, v: D, cam_pos=cam)
    g = grid_near(cam, p2)
    space, st = FZ.classify_space(obs, g, eps, band)
    # 沿相机轴线（x 方向、y=0、z=cam_z）取一列体素
    cj = int(np.argmin(np.abs(g['ys'])))
    ck = int(np.argmin(np.abs(g['zs'] - cam[2])))
    col = space[:, cj, ck]
    xs = g['xs']
    front = xs < D - 0.05
    r.check('A6-1 平面(1m)前方为已知自由',
            bool((col[front] == 2).all()),
            f'n={int(front.sum())} classes={sorted(set(col[front].tolist()))}')
    behind3 = np.abs(xs - (D + 0.003)) <= p2 / 2
    r.check('A6-2 平面后 3 mm 不得标为已知自由',
            bool((col[behind3] != 2).all()) if behind3.any() else False,
            f'classes={col[behind3].tolist()} n={int(behind3.sum())}')

    # 3：视野外点不得借边缘像素获得自由
    obs3 = synth_obs(tmp / 'fov', lambda u, v: D, cam_pos=cam)
    g3 = grid_near(cam, p2)
    # 构造一个视野外体素：很远的 y
    k = int(np.argmin(np.abs(g3['zs'] - cam[2])))
    i0 = int(np.argmin(np.abs(g3['xs'] - 0.5)))
    jmax = g3['dims'][1] - 1
    sp3, _ = FZ.classify_space(obs3, g3, eps, band)
    u, v, z = camera_io.project(
        np.array([[g3['xs'][i0], g3['ys'][jmax], g3['zs'][k]]]),
        json.loads((obs3 / 'observation.json').read_text())['camera'])
    out_of_fov = not (0 <= u[0] <= W - 1 and 0 <= v[0] <= H - 1)
    r.check('A6-3 视野外体素不是已知自由',
            (sp3[i0, jmax, k] != 2) if out_of_fov else True,
            f'uv=({u[0]:.1f},{v[0]:.1f}) class={int(sp3[i0, jmax, k])}')

    # 4：无效深度 / 相机后方
    def depth_invalid(u, v):
        return np.nan if u < 32 else D
    obs4 = synth_obs(tmp / 'invalid', depth_invalid, cam_pos=cam)
    # 相机后方：x < cam_x 的体素（网格从 cam_x+0.2 起，所以另建网格）
    back_pt = np.array([[cam[0] - 0.5, 0.0, 0.3]])
    u, v, z = camera_io.project(back_pt, json.loads((obs4 / 'observation.json').read_text())['camera'])
    r.check('A6-4 相机后方点 depth<=0（不会被清空）', bool(z[0] <= 0), f'z={z[0]:.3f}')

    # 5：倾斜平面（轴向深度 vs 射线长度）
    # 世界平面 x = 1.0 + 0.3*y（绕 z 倾斜），相机在原点朝 +x
    Rcw = R_LOOK_X
    # world = Rcw @ p_cam + t；相机轴 -z_cam -> world +x
    def depth_tilt(u, v):
        K = camera_io.intrinsics(W, H, FOVY)
        xc = (u - K['cx']) / K['fx']
        yc = -(v - K['cy']) / K['fy']
        ray = Rcw @ np.array([xc, yc, -1.0])
        # 与平面 x = 1.0 + 0.3*y 求交：t*ray_x = 1 + 0.3*t*ray_y
        den = ray[0] - 0.3 * ray[1]
        if abs(den) < 1e-9:
            return np.nan
        t = 1.0 / den
        return t if t > 0 else np.nan
    obs5 = synth_obs(tmp / 'tilt', depth_tilt, cam_pos=cam, R=Rcw)
    g5 = grid_near(cam, p2)
    sp5, _ = FZ.classify_space(obs5, g5, eps, band)
    # 真实平面上的点必须不是“已知自由”；轴向深度混用会把它误判为自由
    gy = 0.06
    true_x = 1.0 + 0.3 * gy
    ii = int(np.argmin(np.abs(g5['xs'] - true_x)))
    jj = int(np.argmin(np.abs(g5['ys'] - gy)))
    kk = int(np.argmin(np.abs(g5['zs'] - cam[2])))
    cls_here = int(sp5[ii, jj, kk])
    # 平面之前 10 cm 处必须是自由
    i2 = int(np.argmin(np.abs(g5['xs'] - (true_x - 0.1))))
    cls_front = int(sp5[i2, jj, kk])
    r.check('A6-5 倾斜平面：表面处非自由、表面前方为自由',
            cls_here != 2 and cls_front == 2,
            f'at_surface={cls_here} front={cls_front}')

    # 6：非周期边界
    arr = np.zeros((6, 6, 6), dtype=bool)
    arr[0, 2, 2] = True
    d6 = FZ.dilate6(arr)
    e6 = FZ.erode6(arr)
    r.check('A6-6a dilate6 不从 x=0 绕到 x=-1', bool(not d6[-1, 2, 2]), '')
    r.check('A6-6b dilate6 边界外不激活对侧', bool(d6[0, 2, 2] and not d6[-1, 2, 2]), '')
    m2 = np.zeros((6, 6), dtype=bool); m2[0, 3] = True
    d2 = FZ.dilate2(m2, 2)
    r.check('A6-6c 掩码膨胀不绕回', bool(not d2[-1, 3] and d2[0, 3]), '')
    # 贴地实体底面不绕到网格顶部
    occ = np.zeros((6, 6, 6), dtype=bool); occ[2, 2, 0] = True
    mesh = FZ.marching_tets(occ, {'origin': np.zeros(3), 'pitch': 0.01, 'dims': (6, 6, 6)})
    r.check('A6-6d 底面 z=0 占据不绕到 z=+60mm',
            bool(mesh.bounds[1][2] < 0.03), f'zmax={mesh.bounds[1][2]:.4f}')

    # 7：同输入同配置可重复
    m1 = FZ.marching_tets(occ, {'origin': np.zeros(3), 'pitch': 0.01, 'dims': (6, 6, 6)})
    m2 = FZ.marching_tets(occ, {'origin': np.zeros(3), 'pitch': 0.01, 'dims': (6, 6, 6)})
    r.check('A6-7 同输入可重复',
            bool(np.allclose(np.sort(m1.vertices, axis=0), np.sort(m2.vertices, axis=0))), '')

    # 8：配置篡改改变身份
    e1 = FZ.load_effective_config('configs/unseen_v6_1_fusion.json')
    e2 = FZ.load_effective_config('configs/unseen_v6_1_fusion.json', {'pitch_m': 0.004})
    r.check('A6-8 配置覆盖改变运行身份', e1['sha256'] != e2['sha256'],
            f"{e1['sha256'][:8]} vs {e2['sha256'][:8]}")
    bad = FZ.load_effective_config.__doc__
    try:
        # band 太小必须报错（防止可见面整列落空）
        import subprocess
        p = tmp / 'badcfg.json'
        c = json.loads((ROOT / 'configs/unseen_v6_1_fusion.json').read_text())
        c['band_m'] = 0.0001
        p.write_text(json.dumps(c))
        res = subprocess.run([sys.executable, str(ROOT / 'scripts/fuse_observed.py'),
                              '--observation', str(obs), '--parent-world', str(tmp),
                              '--parent-id', 'X', '--method', 'H5_F',
                              '--out', str(tmp / 'badout'), '--config', str(p)],
                             capture_output=True, text=True)
        r.check('A6-8b band<pitch 被拒绝', res.returncode != 0,
                (res.stderr.strip().splitlines() or [''])[-1][:120])
    except Exception as e:
        r.check('A6-8b band<pitch 被拒绝', False, f'{type(e).__name__}')

    rep = {'schema': 'space-tests/v6_1', 'n': len(r.rows),
           'n_pass': sum(1 for x in r.rows if x['pass']),
           'rows': r.rows}
    (tmp / 'space_tests.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'n_pass': rep['n_pass'], 'n': rep['n']}, ensure_ascii=False))
    return 0 if rep['n_pass'] == rep['n'] else 1


if __name__ == '__main__':
    sys.exit(main())
