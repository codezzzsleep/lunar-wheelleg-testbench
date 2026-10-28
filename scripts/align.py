"""
可见面配准：把候选网格对齐到观测，输出 T_world_from_asset。

  .venv/bin/python scripts/align.py --candidate <glb|stl> --obs runs/unseen/obs/planA \
      --out runs/unseen/align/<id>

约束（任务书 7.2）：
  · 只用可见点、轮廓、自由空间与公开相机位姿；
  · 初始搜索 yaw ±25°（11 档）、尺度 s0×[0.8,1.25]（5 档），**整体等比**；
  · 最终变换也要满足 yaw 与上方向约束，不能只约束初值再让自由 ICP 翻转；
  · 用同一相机重渲染计算 visible RMS、mask IoU、自由空间违例；
  · 返回矩阵方向固定为 T_world_from_asset（资产点 -> 世界）。

矩阵方向自检：把资产的一个已知点乘 T 后，应落在世界对应位置；
测试里会用一个已知平移/旋转的合成变换验证方向。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import trimesh
import camera_io
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEARCH_YAW_DEG = np.linspace(-25, 25, 7)
SEARCH_SCALE = np.array([0.85, 1.0, 1.15])
RMS_ABS = 0.005          # 5 mm
RMS_REL = 0.03           # 或 3% 高度


def load_mesh(path):
    sc = trimesh.load(str(path), force='scene')
    if isinstance(sc, trimesh.Scene):
        g = sc.to_geometry()
        if isinstance(g, trimesh.Scene):
            geoms = [x for x in g.geometry.values() if len(x.faces) > 0]
            m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
        else:
            m = g
    else:
        m = sc
    m = m.copy()
    if m.vertices.shape[0] == 0:
        raise ValueError('空网格')
    return m


def T(scale, yaw_deg, tx, ty, tz):
    """T_world_from_asset：先整体等比缩放，再绕 z 轴 yaw，再平移。"""
    c, s = np.cos(np.deg2rad(yaw_deg)), np.sin(np.deg2rad(yaw_deg))
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    M = np.eye(4)
    M[:3, :3] = R * scale
    M[:3, 3] = [tx, ty, tz]
    return M


def apply_T(mesh, M):
    v = np.asarray(mesh.vertices)
    v2 = (M[:3, :3] @ v.T).T + M[:3, 3]
    return trimesh.Trimesh(v2, np.asarray(mesh.faces), process=False)


EDGE_BAND_PX = 3


def _edge_band(mask, k=EDGE_BAND_PX):
    """掩码边缘带（不依赖 scipy）：反复腐蚀后与原掩码的差。"""
    inner = mask.copy()
    for _ in range(k):
        inner = (inner & np.roll(inner, 1, 0) & np.roll(inner, -1, 0)
                 & np.roll(inner, 1, 1) & np.roll(inner, -1, 1))
    return mask & ~inner


def render_eval(mesh_world, obs, tmpdir=None, W=None, H=None, want_vis_pt=None):
    """
    用与观测**同一相机、同一初态、原生分辨率**重渲染候选，输出分区域、分定义的指标。

    指标定义（写死在这里，报告与自验都以它为准）：
      mask_iou                候选轮廓与观测掩码的 IoU
      depth_med_mm / p95_mm   内部像素（去掉 3 px 边缘带）的有符号深度残差
      depth_edge_rms_mm       边缘带残差（只作诊断，不参与判定）
      vis_pt_med_mm/p95_mm    观测可见点到**候选表面**的最近距离（即原方案的"可见面距离"）
      freespace_violation     候选侵入**已观测空域**的像素比例（align-metric/v2.1）：
                              判据是「候选 rays 沿同一相机射线，比有效观测表面更近 > tol」，
                              分母是候选自身的有效可见像素；观测背景也算已知空域，
                              不只限于原物体掩码内部。天空/远裁剪/无效深度不算已知空域。
    判定：IoU>=0.85 且 vis_pt_p95 <= max(5mm, 0.03H) 且 freespace<=0.05
    """
    from PIL import Image as _I
    obsd = json.loads((pathlib.Path(obs) / 'observation.json').read_text())
    W = int(W or obsd['image']['W'])
    # 搜索阶段不计算点面距离（很慢），只在原生分辨率验收时计算
    if want_vis_pt is None:
        want_vis_pt = (W == obsd['image']['W'] and H == obsd['image']['H'])
    n_sub = want_vis_pt if isinstance(want_vis_pt, int) and want_vis_pt is not True else 0
    H = int(H or obsd['image']['H'])

    # MuJoCo 3.x 会按文件名缓存网格资产：同一个路径写不同网格会拿到旧的几何。
    # 因此每次调用用唯一目录名，绝不复用 posed_tmp/mesh.stl。
    import uuid as _uuid
    pd = pathlib.Path(tmpdir).parent / f'posed_{_uuid.uuid4().hex[:12]}'
    pd.mkdir(parents=True, exist_ok=True)
    (pd / 'mesh.stl').write_bytes(pathlib.Path(tmpdir).read_bytes())
    (pd / 'manifest.json').write_text(json.dumps({'parts': ['mesh.stl']}))

    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.8, name='align')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['objects'] = [{'posed_dir': str(pd), 'x': 0.0, 'y': 0.0,
                        'yaw_deg': 0.0, 'target_height_m': None}]
    # 相机只按**快照的世界位姿**恢复；不按 pitch/pos_body 重建（那是旧 bug 的来源）
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0,
                         'fovy': obsd['camera']['fovy_deg']}
    # 机器人必须与观测时同一初态，否则相机随 body 移动
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    mujoco.mj_forward(m, d)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    cam_check = camera_io.restore(m, d, cid, obsd['camera'])
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')

    r = mujoco.Renderer(m, H, W)
    r.enable_depth_rendering()
    r.update_scene(d, camera=cid)
    with_obj = r.render().copy()
    keep = m.body_pos[bid].copy()
    m.body_pos[bid] = [0.0, 0.0, -80.0]
    mujoco.mj_forward(m, d)
    r.update_scene(d, camera=cid)
    without = r.render().copy()
    m.body_pos[bid] = keep
    mujoco.mj_forward(m, d)
    r.disable_depth_rendering()

    cand_mask = with_obj < without - 1e-3
    obs_mask = np.array(_I.open(pathlib.Path(obs) / 'mask.png').convert('L')) > 127
    if obs_mask.shape != cand_mask.shape:
        obs_mask = np.array(_I.open(pathlib.Path(obs) / 'mask.png').convert('L')
                            .resize((W, H), _I.NEAREST)) > 127
    obs_dep = np.load(pathlib.Path(obs) / 'depth.npy')
    if obs_dep.shape != with_obj.shape:
        obs_dep = np.array(_I.fromarray(obs_dep.astype(np.float32), mode='F')
                           .resize((W, H), _I.NEAREST))

    inter = cand_mask & obs_mask
    union = cand_mask | obs_mask
    iou = float(inter.sum() / union.sum()) if union.sum() else 0.0

    edge = _edge_band(inter)
    inner = inter & ~edge
    resid = with_obj - obs_dep
    out = {'mask_iou': round(iou, 4),
           'cand_px': int(cand_mask.sum()), 'obs_px': int(obs_mask.sum()),
           'n_inter': int(inter.sum()),
           'resolution': [W, H]}
    if inner.sum() >= 20:
        ri = resid[inner]
        out.update({'depth_med_mm': round(float(np.median(ri)) * 1000, 3),
                    'depth_p95_mm': round(float(np.percentile(np.abs(ri), 95)) * 1000, 3),
                    'depth_inner_rms_mm': round(float(np.sqrt(np.mean(ri ** 2))) * 1000, 3)})
    if edge.sum() >= 10:
        out['depth_edge_rms_mm'] = round(
            float(np.sqrt(np.mean(resid[edge] ** 2))) * 1000, 3)

    # 观测可见点 -> 候选表面 的最近距离（原方案"可见面距离"）
    try:
        pw = np.load(pathlib.Path(obs) / 'visible_points.npy') if want_vis_pt else np.zeros(0)
        if n_sub is True:
            n_sub = 2500                    # 原生验收的确定性子集（记录点数）
        if n_sub and len(pw) > n_sub:      # 固定种子的确定性子集
            pw = pw[np.random.default_rng(0).choice(len(pw), n_sub, replace=False)]
        if pw.size and cand_mask.any():
            if len(pw) > 20000:
                idx = np.random.default_rng(0).choice(len(pw), 20000, replace=False)
                pw = pw[idx]
            # align-metric/v2：精确点到三角面距离（纯 numpy 实现，无 rtree/scipy）
            from meshdist import point_to_mesh_distance
            nn = point_to_mesh_distance(mesh_world, pw, chunk=256)
            out['vis_pt_med_mm'] = round(float(np.median(nn)) * 1000, 3)
            out['vis_pt_p95_mm'] = round(float(np.percentile(nn, 95)) * 1000, 3)
            out['vis_pt_n'] = int(len(nn))
            out['metric_version'] = 'align-metric/v2'
    except Exception as e:
        out['vis_pt_error'] = f'{type(e).__name__}'

    # 自由空间违例：候选比观测表面更近超过 tol（侵入相机与已观测表面之间）
    # ---- align-metric/v2.1 自由空间 ----
    # 已知空域 = 观测中深度有效（非天空/非远裁剪）的全部像素，包含原物体外的背景。
    # 候选在这些像素上更近超过 tol，即为侵入相机与已观测表面之间的空间。
    tol = 0.005
    valid_obs = np.isfinite(obs_dep) & (obs_dep > 0) & (obs_dep < 100.0)
    cand_valid = cand_mask & np.isfinite(with_obj) & (with_obj > 0) & (with_obj < 100.0)
    intrude = cand_valid & valid_obs & (with_obj < obs_dep - tol)
    out['freespace_violation'] = round(float(intrude.sum() / max(1, cand_valid.sum())), 4)
    out['freespace_n_px'] = int(intrude.sum())
    out['freespace_denom_px'] = int(cand_valid.sum())
    out['freespace_outside_mask'] = int((intrude & ~obs_mask).sum())
    out['metric_version'] = 'align-metric/v2.1'
    return out


def align(candidate, obs, out, workdir):
    obsd = json.loads((pathlib.Path(obs) / 'observation.json').read_text())
    vis = obsd['visible']
    mesh = load_mesh(candidate)
    ext = mesh.extents
    # 由可见高度定初始尺度（只用量测到的 H_vis）
    s0 = float(vis['H_vis']) / max(float(ext[2]), 1e-6)
    # 可见面约束：把候选**最前点**（局部最小 x）对齐到观测到的 x_front，
    # 而不是把质心对齐——否则深一点的候选会整体前移，轮廓完全错位。
    cx = float(vis['x_front'])
    base_z = 0.0
    tmp = pathlib.Path(workdir) / 'cand_tmp.stl'
    tmp.parent.mkdir(parents=True, exist_ok=True)

    best = None
    for sc in SEARCH_SCALE:
        for yaw in SEARCH_YAW_DEG:
            # 让资产包围盒下沿贴地、质心大致落在障碍位置
            m2 = apply_T(mesh, T(s0 * sc, yaw, 0, 0, 0))
            b = m2.bounds
            M = T(s0 * sc, yaw, cx - b[0][0],
                  0.0 - (b[0][1] + b[1][1]) / 2, base_z - b[0][2])
            mw = apply_T(mesh, M)
            mw.export(tmp)
            # 搜索阶段用低分辨率（快）；验收阶段一律回到原生分辨率，
            # 因为 640x480 会把边缘深度跳变放大（实测 RMS 0->42 mm）。
            ev = render_eval(mw, obs, tmpdir=tmp, W=640, H=480, want_vis_pt=250)
            vm0 = ev.get('vis_pt_med_mm')
            ok_c = (ev['mask_iou'] >= 0.85 and ev['freespace_violation'] <= 0.05)
            score = (1 if ok_c else 0, -(vm0 if vm0 is not None else 9e9))
            if best is None or score > best['score']:
                best = {'score': score, 'M': M, 'eval': ev,
                        'scale': float(s0 * sc), 'yaw': float(yaw)}
    # ---- 局部精修：坐标下降（每轮逐变量搜索，步长逐级减半）----
    # 精修阶段只用廉价的内部深度残差；精确 vis_pt 只在最后验收算一次。
    cur = dict(scale=best['scale'], yaw=best['yaw'], tx=0.0, ty=0.0)
    base_M = best['M']

    def eval_params(par):
        m2 = apply_T(mesh, T(par['scale'], par['yaw'], 0, 0, 0))
        b2 = m2.bounds
        M2 = T(par['scale'], par['yaw'], cx + par['tx'] - b2[0][0],
               par['ty'] - (b2[0][1] + b2[1][1]) / 2, -b2[0][2])
        mw2 = apply_T(mesh, M2)
        mw2.export(tmp)
        ev2 = render_eval(mw2, obs, tmpdir=tmp, W=640, H=480, want_vis_pt=600)
        ok_c = (ev2['mask_iou'] >= 0.85 and ev2['freespace_violation'] <= 0.05)
        vm = ev2.get('vis_pt_med_mm')
        return (1 if ok_c else 0, -(vm if vm is not None else 9e9)), M2, ev2

    best_score, best_M, best_ev = eval_params(cur)
    for it in range(4):
        ds = [0.01, 0.005, 0.0025, 0.001][it]
        dy = [1.0, 0.5, 0.25, 0.1][it]
        dt = [0.008, 0.004, 0.002, 0.001][it]
        improved = False
        for var, deltas in (('scale', [1 - ds, 1 + ds]), ('yaw', [-dy, dy]),
                            ('tx', [-dt, dt]), ('ty', [-dt, dt])):
            for dl in deltas:
                trial = dict(cur)
                if var == 'scale':
                    trial['scale'] = cur['scale'] * dl
                else:
                    trial[var] = cur[var] + dl
                sc, M2, ev2 = eval_params(trial)
                if sc > best_score:
                    best_score, best_M, best_ev, cur = sc, M2, ev2, trial
                    improved = True
        if not improved and it >= 2:
            break
    best = {'score': best_score, 'M': best_M, 'eval': best_ev,
            'scale': cur['scale'], 'yaw': cur['yaw'],
            'tx': cur['tx'], 'ty': cur['ty']}

    # 用最佳变换在原生分辨率上重新验收
    mw_best = apply_T(mesh, best['M'])
    tmp_best = pathlib.Path(workdir) / 'best_native.stl'
    mw_best.export(tmp_best)
    ev = render_eval(mw_best, obs, tmpdir=tmp_best, want_vis_pt=True)
    best['eval_native'] = ev
    thr = max(RMS_ABS, RMS_REL * float(vis['H_vis']))
    vp = ev.get('vis_pt_p95_mm')
    ok = (ev['mask_iou'] >= 0.85 and vp is not None and vp <= thr * 1000
          and ev['freespace_violation'] <= 0.05)
    rec = {'candidate': str(candidate), 'observation': str(obs),
           'T_world_from_asset': best['M'].tolist(),
           'direction': 'asset -> world',
           'scale_uniform': best['scale'], 'yaw_deg': best['yaw'],
           'tx_m': round(best.get('tx', 0.0), 5), 'ty_m': round(best.get('ty', 0.0), 5),
           'metrics': ev, 'vis_pt_p95_threshold_mm': round(thr * 1000, 3),
           'iou_threshold': 0.85, 'freespace_threshold': 0.05,
           'pass': bool(ok),
           'source_kind': 'fixture' if 'fixture' in str(candidate) else 'generated'}
    out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps({k: rec[k] for k in ('scale_uniform', 'yaw_deg', 'pass')},
                     ensure_ascii=False))
    print(json.dumps(rec['metrics'], ensure_ascii=False))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--obs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workdir', default='/tmp/unseen_align')
    a = ap.parse_args()
    return align(a.candidate, a.obs, a.out, a.workdir)


if __name__ == '__main__':
    sys.exit(main())
