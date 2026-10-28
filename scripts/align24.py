"""
24 朝向配准：先旋转资产、再估尺度，最后在原生分辨率用精确点面距离验收。

  .venv/bin/python scripts/align24.py --candidate <glb> --obs <obs_dir> --out <json>

与旧 align.py 的区别：
  · 不再把 raw extents[2] 当高度，而是枚举 24 个保持手性的轴对齐旋转；
  · 每个朝向先旋转网格，再用**旋转后**的宽/高估计尺度初值；
  · 粗筛用廉价指标（低分辨率 + 少量可见点），只把前若干名送原生精确验收；
  · 相机与观测共用 camera_io 的快照与恢复，恢复后校验世界位姿。

指标（align-metric/v2.1，阈值未放宽）：
  mask_iou >= 0.85
  vis_pt_p95 <= max(5 mm, 0.03 * H_vis)
  freespace_violation <= 0.05
"""
import argparse
import itertools
import json
import pathlib
import sys
import time

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import align as A
import camera_io
import fastscore
import mujoco
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()
COARSE_YAW = np.linspace(-25, 25, 7)
COARSE_SCALE = np.array([0.9, 1.0, 1.1])


def rotations24():
    """24 个保持手性的轴对齐旋转（det=+1，无反射）。"""
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((-1.0, 1.0), repeat=3):
            R = np.zeros((3, 3))
            R[np.arange(3), list(perm)] = signs
            if np.linalg.det(R) > 0.5:
                out.append(R)
    assert len(out) == 24, len(out)
    for R in out:
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-9)
        assert abs(np.linalg.det(R) - 1.0) < 1e-9
    return out


def transform(mesh, R_axis, scale, yaw_deg, tx, ty, tz):
    c, s = np.cos(np.deg2rad(yaw_deg)), np.sin(np.deg2rad(yaw_deg))
    Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    M = np.eye(4)
    M[:3, :3] = (Rz @ R_axis) * scale
    M[:3, 3] = [tx, ty, tz]
    return M


def eval_pose(mesh, M, obs_dir, tmp, W, H, want_vis_pt):
    mw = A.apply_T(mesh, M)
    mw.export(tmp)
    return A.render_eval(mw, obs_dir, tmpdir=tmp, W=W, H=H, want_vis_pt=want_vis_pt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--obs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--work-dir', default=None)
    ap.add_argument('--top-k', type=int, default=4)
    ap.add_argument('--coarse-points', type=int, default=120)
    ap.add_argument('--time-budget-s', type=float, default=1500.0)
    a = ap.parse_args()

    import tempfile
    work = pathlib.Path(a.work_dir or tempfile.mkdtemp())
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / 'cand.stl'

    obsd = json.loads((pathlib.Path(a.obs) / 'observation.json').read_text())
    vis = obsd['visible']
    H_vis, W_vis, x_front = float(vis['H_vis']), float(vis['W_vis']), float(vis['x_front'])
    mesh = A.load_mesh(a.candidate)
    raw_bounds = np.asarray(mesh.bounds).tolist()
    t0 = time.time()

    obs_raw = np.load(pathlib.Path(a.obs) / 'visible_points.npy')
    obs_pts = fastscore.prep_obs(obs_raw)
    surf = fastscore.sample_surface(mesh)

    def quick(M):
        pts = surf @ M[:3, :3].T + M[:3, 3]
        med, cov = fastscore.score(pts, obs_pts)
        return med, cov

    cands = []
    for Ri, R in enumerate(rotations24()):
        rot = mesh.copy()
        rot.apply_transform(np.block([[R, np.zeros((3, 1))], [np.zeros((1, 3)), 1]]))
        e = rot.extents
        # 旋转后再估尺度：高度轴是旋转后的 z，宽度轴是旋转后的 y
        s_h = H_vis / max(e[2], 1e-9)
        s_w = W_vis / max(e[1], 1e-9)
        for s0_name, s0 in (('H', s_h), ('W', s_w), ('geo', float(np.sqrt(s_h * s_w)))):
            for sc in COARSE_SCALE:
                for yaw in COARSE_YAW:
                    M0 = transform(mesh, R, s0 * sc, yaw, 0, 0, 0)
                    m0 = A.apply_T(mesh, M0)
                    b = m0.bounds
                    M = transform(mesh, R, s0 * sc, yaw,
                                  x_front - b[0][0],
                                  -(b[0][1] + b[1][1]) / 2,
                                  -b[0][2])
                    if time.time() - t0 > a.time_budget_s:
                        break
                    med, cov = quick(M)
                    score = (-med, cov)
                    cands.append({'R_index': Ri, 'init': s0_name, 'scale': s0 * sc,
                                  'yaw': float(yaw), 'M': M.tolist(), 'score': score,
                                  'quick': {'med_mm': med, 'cover': cov}})
                if time.time() - t0 > a.time_budget_s:
                    break
            if time.time() - t0 > a.time_budget_s:
                break
        if time.time() - t0 > a.time_budget_s:
            break

    cands.sort(key=lambda c: c['score'], reverse=True)
    top = cands[:a.top_k]

    best = None
    for c in top:
        M = np.asarray(c['M'])
        # 精修：坐标下降（尺度 / yaw / 平移），用便宜指标，最后原生精确验收
        cur = {'M': M, 'score': c['score']}
        for it in range(3):
            ds = [0.02, 0.01, 0.005][it]
            dy = [2.0, 1.0, 0.5][it]
            dt = [0.01, 0.005, 0.002][it]
            improved = False
            for var, dl in (('s', [1 - ds, 1 + ds]), ('y', [-dy, dy]),
                            ('tx', [-dt, dt]), ('ty', [-dt, dt])):
                for v in dl:
                    M2 = cur['M'].copy()
                    if var == 's':
                        M2[:3, :3] *= v
                    elif var == 'y':
                        c_, s_ = np.cos(np.deg2rad(v)), np.sin(np.deg2rad(v))
                        Rz = np.array([[c_, -s_, 0], [s_, c_, 0], [0, 0, 1]])
                        M2[:3, :3] = Rz @ M2[:3, :3]
                    elif var == 'tx':
                        M2[0, 3] += v
                    else:
                        M2[1, 3] += v
                    med2, cov2 = quick(M2)
                    if (-med2, cov2) > cur['score']:
                        cur['M'] = M2
                        cur['score'] = (-med2, cov2)
                        improved = True
            if not improved:
                break
        # ---- 最终 M：z_min 归零在**评估前**完成，指标用同一个 M 重算 ----
        Mm = cur['M'].copy()
        z0 = float(np.asarray(A.apply_T(mesh, Mm).bounds)[0][2])
        if abs(z0) > 1e-12:
            Mm[2, 3] -= z0
        cur['M'] = Mm
        native = eval_pose(mesh, Mm, a.obs, tmp, None, None, True)
        mw_final = A.apply_T(mesh, Mm)
        z_min = float(np.asarray(mw_final.bounds)[0][2])
        sc_real = float(np.cbrt(abs(np.linalg.det(Mm[:3, :3]))))
        R_real = Mm[:3, :3] / max(sc_real, 1e-12)
        shear = float(np.max(np.abs(Mm[:3, :3].T @ Mm[:3, :3]
                                    - (sc_real ** 2) * np.eye(3))))
        # 增量 yaw：相对于选定轴基 R_axis，用完整旋转求，不用 arctan2 单元素
        R_axis = rotations24()[c['R_index']]
        dR = R_axis.T @ R_real
        yaw_real = float(np.degrees(np.arctan2(dR[1, 0] - dR[0, 1],
                                                dR[0, 0] + dR[1, 1])))
        axis_real = (R_real @ np.eye(3)).round(3).tolist()
        rec = {'R_index': c['R_index'], 'init': c['init'],
               'scale_init': c['scale'], 'yaw_init': c['yaw'],
               'scale': round(sc_real, 5), 'yaw': round(yaw_real, 3),
               'R_axis_world': axis_real, 'shear_residual': round(shear, 9),
               'z_min_world_m': round(z_min, 9),
               'world_dir': str(world_dir),
               'M': cur['M'].tolist(),
               'native': native, 'threshold_p95_mm': round(thr, 3), 'pass': bool(ok)}
        if best is None or (rec['pass'], -(p95 or 9e9)) > (best['pass'],
                                                           -(best['native'].get('vis_pt_p95_mm') or 9e9)):
            best = rec

    # 朝向歧义只在**不同 R_index** 之间比较；同旋转不同尺度初值不算
    distinct = {}
    for c in top:
        distinct.setdefault(c['R_index'], c['score'][0])
    ranked = sorted(distinct.items(), key=lambda kv: kv[1])
    ambig = (len(ranked) > 1 and abs(ranked[0][1] - ranked[1][1]) < 1.0)
    out = {'candidate': str(a.candidate), 'observation': str(a.obs),
           'distinct_orientations_in_top': ranked,
           'metric_version': 'align-metric/v2.1',
           'camera_schema': obsd.get('camera_schema'),
           'raw_bounds': raw_bounds, 'raw_extents': [float(x) for x in mesh.extents],
           'n_coarse_evals': len(cands), 'wall_s': round(time.time() - t0, 1),
           'orientation_ambiguous': bool(ambig),
           'top': [{'R_index': c['R_index'], 'init': c['init'],
                    'scale': round(c['scale'], 5), 'yaw': round(c['yaw'], 2),
                    'quick_med_mm': round(-c['score'][0], 3),
                    'quick_cover': c['score'][1]} for c in top],
           'best': best,
           'pass': bool(best and best['pass']),
           }
    # ---- 只把真正的 best 写入正式目录（原子替换，不覆盖循环中的临时结果）----
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
    world_dir = p.parent / 'world' / p.stem
    world_dir.mkdir(parents=True, exist_ok=True)
    if best is not None:
        Mbest = np.asarray(best['M'])
        mw = A.apply_T(mesh, Mbest)
        part = world_dir / 'body.stl'
        tmpf = world_dir / '.body.stl.tmp'
        mw.export(tmpf); tmpf.replace(part)
        man = {'schema': 'asset-manifest/v1', 'version': 'align24/v3',
               'coordinate_frame': 'world', 'parts': ['body.stl'],
               'T_world_from_asset': Mbest.tolist(),
               'body_pose_expected': {'pos': [0, 0, 0], 'quat': [1, 0, 0, 0]},
               'source_sha': _sha(a.candidate),
               'world_sha': _sha(part),
               'observation': str(a.obs),
               'camera_schema': obsd.get('camera_schema'),
               'metric_version': 'align-metric/v2.1'}
        mant = world_dir / '.manifest.json.tmp'
        mant.write_text(json.dumps(man, indent=2, ensure_ascii=False))
        mant.replace(world_dir / 'manifest.json')
        # 一致性自检：best.M 应用于源网格 == 导出的世界网格
        rb = np.asarray(mw.bounds)
        rd = trimesh.load(str(part), force='mesh', process=False)
        dmax = float(np.max(np.abs(np.asarray(rd.bounds) - rb)))
        out['export_check'] = {'max_bound_diff_m': round(dmax, 9),
                               'consistent': dmax < 1e-6,
                               'world_sha': man['world_sha']}
        best['world_dir'] = str(world_dir)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({'candidate': pathlib.Path(a.candidate).parent.name[:8],
                      'pass': out['pass'], 'n_coarse': len(cands),
                      'best_R': best['R_index'] if best else None,
                      'best_iou': best['native']['mask_iou'] if best else None,
                      'best_p95_mm': best['native'].get('vis_pt_p95_mm') if best else None,
                      'wall_s': out['wall_s']}, ensure_ascii=False))
    return 0 if out['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
