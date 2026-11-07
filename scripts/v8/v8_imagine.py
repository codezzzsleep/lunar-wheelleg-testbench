"""V8 想象与自检：一块目标石头的观测目录 + Lux3D 候选 GLB -> 每份候选的配准、自检结果、所占格子。

沿用 V7 已验证的链条，只改"看不清的像素不算对也不算错"这一处：
  栅格 / 观测体   v3_fuse.observe_volume —— 黑影像素没有深度（NaN），自然不参与"已知空地"的雕刻
  配准           v3_register.register —— 轮廓 IoU 只在能判断的像素上算：
                   黑影（太暗，没有深度）里的不算；被更近的东西挡住的（观测深度比候选近 5 cm 以上）也不算。
                   两种影子同一个道理：看不见的地方，候选在那里有没有东西都不能算错。
  准入           v5_core.admission_metrics + configs/v5_admission.json（门槛冻结，与 V7 相同）
                 尺寸比从地面量起（v7_encounter.scale_ratio_ground，metric_version 2）
栅格比 V7 大：V8 的石头更大（宽 1.2 m、厚 0.7 m），往后至少 1.6 m、两侧各多留 0.45 m，候选不会被栅格截断。

想象出的石头所占格子 = 被采纳候选的"柱状填充"体素在地面上的投影（世界坐标，5 cm 格）。
"""
import json
import pathlib
import sys

import numpy as np
import trimesh

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(ROOT / 'scripts/v7'))
import v3_fuse, v3_register as REG, v5_core as C  # noqa: E401,E402
import v7_encounter as VE  # noqa: E402
import v8_nav as N  # noqa: E402

PROTO = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
ADM = VE.ADM


# ---------------------------------------------------------------- 黑影感知的配准（替换 v3_register 里的三个函数）
_orig_load = REG.load_observation


def load_observation(obs_dir):
    obs = _orig_load(obs_dir)
    from PIL import Image
    p = pathlib.Path(obs_dir) / 'dark.png'
    dark = (np.array(Image.open(p).convert('L')) > 127) if p.exists() else np.zeros_like(obs['mask'])
    obs['care'] = ~dark | obs['mask']           # 能判断的像素：亮处（目标亮面本身当然算）
    return obs


OCCL_M = 0.05


def _iou_care(m, mask, care, cand_depth=None, obs_depth=None):
    if cand_depth is not None:
        with np.errstate(invalid='ignore'):
            occl = (obs_depth < cand_depth - OCCL_M) & ~mask      # 观测到的表面比候选近：候选在这里被挡住了
        care = care & ~occl
    inter = int((m & mask).sum()); union = int(((m | mask) & care).sum())
    return inter / max(1, union)


def observation_score(mesh, obs, M, samples=8000):
    import trimesh as _tm
    surf = np.asarray(_tm.sample.sample_surface(mesh, samples, seed=0)[0], float)
    Q = surf @ np.asarray(M)[:3, :3].T + np.asarray(M)[:3, 3]
    u, v, z = REG._project(Q, obs['camera'])
    H, W = obs['mask'].shape
    good = np.isfinite(u) & np.isfinite(v) & (z > 0)
    ui = np.round(u[good]).astype(np.int64); vi = np.round(v[good]).astype(np.int64); zz = z[good]
    inside = (ui >= 0) & (ui < W) & (vi >= 0) & (vi < H)
    ui, vi, zz = ui[inside], vi[inside], zz[inside]
    if len(ui) < 50:
        return {'depth_median_mm': float('nan'), 'depth_p95_mm': float('nan'), 'coverage': 0.0, 'iou_points': 0.0, 'n_visible': int(len(ui))}
    depth = np.full((H, W), np.inf); np.minimum.at(depth, (vi, ui), zz)
    m = np.isfinite(depth); mask = obs['mask']; care = obs.get('care', np.ones_like(mask))
    obs_depth = obs['depth']
    both = m & mask & np.isfinite(obs_depth)
    if both.sum() > 20:
        dd = np.abs(depth[both] - obs_depth[both]) * 1000; med = float(np.median(dd)); p95 = float(np.percentile(dd, 95))
    else:
        med = p95 = float('nan')
    return {'depth_median_mm': round(med, 3), 'depth_p95_mm': round(p95, 3),
            'coverage': round(float((m & mask).sum() / max(1, int(mask.sum()))), 4),
            'iou_points': round(_iou_care(m, mask, care, np.where(m, depth, np.inf), obs_depth), 4), 'n_visible': int(len(ui))}


def evaluate_matrix(mesh, obs, M):
    mask = obs['mask']; care = obs.get('care', np.ones_like(mask))
    m, dm = REG.rasterize_mesh(mesh, obs, M)
    iou = _iou_care(m, mask, care, np.where(m, dm, np.inf), obs['depth'])
    with np.errstate(invalid='ignore'):
        occl_px = int(((obs['depth'] < np.where(m, dm, np.inf) - OCCL_M) & ~mask & m).sum())
    iou_plain = float((m & mask).sum()) / max(1, int((m | mask).sum()))
    depth = obs['depth']
    both = m & mask & np.isfinite(dm) & np.isfinite(depth)
    if both.sum() > 20:
        dd = np.abs(dm[both] - depth[both]) * 1000; depth_p95 = float(np.percentile(dd, 95)); depth_med = float(np.median(dd))
    else:
        depth_p95 = depth_med = float('nan')
    V = np.asarray(trimesh.sample.sample_surface(mesh, 30000, seed=0)[0], dtype=np.float64)
    Q = V @ np.asarray(M)[:3, :3].T + np.asarray(M)[:3, 3]
    from scipy.spatial import cKDTree
    d, _ = cKDTree(Q[::max(1, len(Q) // 20000)]).query(obs['points']); d = d * 1000
    return {'mask_iou': round(iou, 4), 'mask_iou_all_pixels': round(iou_plain, 4),
            'outside_lit_px': int((m & ~mask & care).sum()), 'in_dark_px': int((m & ~care).sum()), 'occluded_px': occl_px,
            'depth_median_mm': round(depth_med, 3), 'depth_p95_mm': round(depth_p95, 3),
            'visible_median_mm': round(float(np.median(d)), 3), 'visible_p95_mm': round(float(np.percentile(d, 95)), 3),
            'n_candidate_pixels': int(m.sum()), 'n_mask_pixels': int(mask.sum())}


def coarse_search(mesh, obs, cfg, n_points=4000, top_k=6):
    """与 v3 相同的 24 朝向 × 尺度 × 偏航粗搜索，只是 IoU 的并集里去掉黑影像素。"""
    P = np.asarray(trimesh.sample.sample_surface(mesh, int(n_points), seed=0)[0], dtype=np.float64)
    cam = obs['camera']
    mask, depth4, W4, H4 = REG._downsample_mask(obs['mask'], np.nan_to_num(obs['depth'], nan=np.inf), 4)
    depth4_flat = depth4.ravel()
    care = obs.get('care', np.ones_like(obs['mask']))
    Hc, Wc = care.shape
    care4 = care[:H4 * 4, :W4 * 4].reshape(H4, 4, W4, 4).all(axis=(1, 3)) | mask
    vis = obs['points']
    x_front = float(vis[:, 0].min()); y_center = float((vis[:, 1].min() + vis[:, 1].max()) / 2.0)
    H_vis = float(vis[:, 2].max()); W_vis = float(np.ptp(vis[:, 1]))
    mask_flat = mask.ravel(); care_flat = care4.ravel()
    yaws = np.deg2rad(np.arange(0, 360, float(cfg.get('coarse_yaw_step_deg', 5.0))))
    out = []
    for ri, R0 in enumerate(REG.rotations24()):
        Q = P @ R0.T
        e = Q.max(0) - Q.min(0)
        if np.any(e < 1e-9):
            continue
        for s0 in {H_vis / e[2], W_vis / e[1]}:
            Qs = Q * s0
            for yaw in yaws:
                c, si = np.cos(yaw), np.sin(yaw)
                Rz = np.array([[c, -si, 0], [si, c, 0], [0, 0, 1]])
                Qy = Qs @ Rz.T
                t = np.array([x_front - Qy[:, 0].min(), y_center - (Qy[:, 1].min() + Qy[:, 1].max()) / 2.0, -Qy[:, 2].min()])
                u, v, z = REG._project(Qy + t, cam)
                ok = np.isfinite(u) & np.isfinite(v) & (z > 0)
                ui = np.floor(u[ok] / 4.0).astype(np.int64); vi = np.floor(v[ok] / 4.0).astype(np.int64)
                inb = (ui >= 0) & (ui < W4) & (vi >= 0) & (vi < H4)
                if inb.sum() < 20:
                    continue
                idx = vi[inb] * W4 + ui[inb]
                occ = np.zeros(W4 * H4, dtype=bool); occ[idx] = True
                cd = np.full(W4 * H4, np.inf); np.minimum.at(cd, idx, z[ok][inb])
                occl = (depth4_flat < cd - OCCL_M) & ~mask_flat
                inter = int((occ & mask_flat).sum()); union = int(((occ | mask_flat) & care_flat & ~occl).sum())
                if union == 0:
                    continue
                iou = inter / union
                M = np.eye(4); M[:3, :3] = (Rz @ R0) * s0; M[:3, 3] = t
                out.append({'score': float(iou), 'iou': float(iou), 'depth_err_m': None, 'R_index': ri, 'R0': R0,
                            'yaw_deg': float(np.rad2deg(yaw)), 'scale': float(s0), 'M': M})
    out.sort(key=lambda r: -r['score'])
    seen, picked = set(), []
    for r in out:
        if r['R_index'] in seen:
            continue
        seen.add(r['R_index']); picked.append(r)
        if len(picked) >= top_k:
            break
    return picked, len(out)


REG.load_observation = load_observation
REG.observation_score = observation_score
REG.evaluate_matrix = evaluate_matrix
REG.coarse_search = coarse_search


# ---------------------------------------------------------------- 栅格与观测体
def frozen_grid_v8(vis, pitch0=0.004, max_voxels=14_000_000):
    hidden = max(1.6, 1.3 * max(float(vis['W_vis']), float(vis['H_vis'])))
    half_y = float(vis['W_vis']) / 2.0 + max(0.45, 0.5 * float(vis['W_vis']))
    z_top = float(vis['H_vis']) * 1.25 + 0.05
    lo = np.array([float(vis['x_front']) - 0.05, float(vis['y_center']) - half_y, 0.0])
    hi = np.array([float(vis['x_front']) + hidden, float(vis['y_center']) + half_y, z_top])
    pitch = pitch0
    while True:
        lo_a = np.floor(lo / pitch) * pitch
        dims = np.maximum(np.ceil((hi - lo_a) / pitch).astype(int), 8)
        if int(np.prod(dims)) <= max_voxels:
            break
        pitch = round(pitch * 1.15, 6)
    g = {'origin': lo_a, 'pitch': pitch, 'dims': dims}
    g['xs'] = lo_a[0] + (np.arange(dims[0]) + 0.5) * pitch
    g['ys'] = lo_a[1] + (np.arange(dims[1]) + 0.5) * pitch
    g['zs'] = lo_a[2] + (np.arange(dims[2]) + 0.5) * pitch
    return g


def build_volume(obs_dir):
    st = json.loads((pathlib.Path(obs_dir) / 'state.json').read_text())
    g = frozen_grid_v8(st['visible'])
    proto = json.loads(json.dumps(PROTO)); proto['visibility']['band_m'] = max(0.006, 2.5 * g['pitch'])
    proto['visibility']['free_epsilon_m'] = max(0.004, 1.5 * g['pitch'])
    space, shell, stats, _ = v3_fuse.observe_volume(obs_dir, g, proto)
    V = {'shell': shell, 'space': space, 'origin': np.asarray(g['origin'], float), 'pitch': np.float64(g['pitch']),
         'dims': np.asarray(g['dims'], int)}
    return V, C.grid_from_V(V), st, stats


def admitted(m):
    return VE.admitted(m)


def footprint_world(P, g, local_frame, z_min=0.04):
    """柱状填充体素 P（局部栅格）-> 世界坐标 5 cm 导航格。"""
    zs = np.asarray(g['zs'])
    col = (P & (zs[None, None, :] >= z_min)).any(axis=2)
    ix, iy = np.nonzero(col)
    xl, yl = np.asarray(g['xs'])[ix], np.asarray(g['ys'])[iy]
    c, s = np.cos(local_frame['yaw0']), np.sin(local_frame['yaw0'])
    xw = local_frame['x0'] + c * xl - s * yl; yw = local_frame['y0'] + s * xl + c * yl
    out = np.zeros((N.NX, N.NY), bool)
    i = ((xw - N.X0) / N.RES).astype(int); j = ((yw - N.Y0) / N.RES).astype(int)
    ok = (i >= 0) & (i < N.NX) & (j >= 0) & (j < N.NY)
    out[i[ok], j[ok]] = True
    from scipy import ndimage
    return ndimage.binary_closing(out, iterations=1) | out


def decide_target(obs_dir, glbs, out_dir):
    """glbs: [{'id', 'glb'}]。返回 {'candidates': [...], 'admitted_ids', 'footprint': bool 网格（被采纳候选的并集）}。"""
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    V, g, st, stats = build_volume(obs_dir)
    obs = REG.load_observation(str(obs_dir))
    rows, union = [], np.zeros((N.NX, N.NY), bool)
    fps = {}
    for c in glbs:
        rd = out / 'reg' / c['id']; rd.mkdir(parents=True, exist_ok=True)
        rec = REG.register(str(c['glb']), str(obs_dir), PROTO, rd, top_k=6)
        M = np.asarray(rec['best']['M'], float)
        mesh = trimesh.load(str(c['glb']), force='mesh', process=False)
        ev = evaluate_matrix(mesh, obs, M)
        m = C.admission_metrics(mesh, M, V, g, ev)
        m['scale_ratio_v5'] = m['scale_ratio']; m['scale_ratio'] = VE.scale_ratio_ground(m['P'], V, g)
        fp = footprint_world(m['P'], g, st['local_frame'])
        row = {k: v for k, v in m.items() if k != 'P'}
        row.update({'id': c['id'], 'glb': str(c['glb']), 'M': M.tolist(), 'admitted': admitted(m),
                    'eval': ev, 'footprint_cells': int(fp.sum()),
                    'footprint_x': [float(N.GX[fp].min()), float(N.GX[fp].max())] if fp.any() else None,
                    'footprint_y': [float(N.GY[fp].min()), float(N.GY[fp].max())] if fp.any() else None})
        rows.append(row); fps[c['id']] = fp
        np.save(out / f'footprint_{c["id"]}.npy', fp)
        if row['admitted']:
            union |= fp
    res = {'schema': 'v8-target-decision/v1', 'metric_version': 2, 'obs': str(obs_dir), 'grid': {'pitch': float(g['pitch']),
           'dims': [int(x) for x in g['dims']]}, 'volume_stats': stats, 'thresholds': ADM,
           'candidates': rows, 'admitted_ids': [r['id'] for r in rows if r['admitted']]}
    (out / 'target_decision.json').write_text(json.dumps(res, indent=2, ensure_ascii=False))
    np.save(out / 'footprint_union.npy', union)
    res['footprint'] = union; res['footprints'] = fps
    return res


# ---------------------------------------------------------------- 在想象里预演
def candidate_world_mesh(glb, M, local_frame, out_obj):
    """候选 GLB -> 配准矩阵 M（局部）-> 世界坐标网格，写成 OBJ。"""
    mesh = trimesh.load(str(glb), force='mesh', process=False)
    mesh.apply_transform(np.asarray(M, float))
    c, s = np.cos(local_frame['yaw0']), np.sin(local_frame['yaw0'])
    T = np.array([[c, -s, 0, local_frame['x0']], [s, c, 0, local_frame['y0']], [0, 0, 1, 0], [0, 0, 0, 1.0]])
    mesh.apply_transform(T)
    out_obj = pathlib.Path(out_obj); out_obj.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out_obj))
    return out_obj


def rehearsal_spec(base_spec, cand_objs, out_dir):
    """预演场景：只放机器人知道的东西——地形（轨道图）、右侧禁行线外的一堵墙、想象出的石块。"""
    import copy
    spec = copy.deepcopy(base_spec)
    objs = []
    for k, obj in enumerate(cand_objs):
        pd = pathlib.Path(out_dir) / f'posed_{k}'; pd.mkdir(parents=True, exist_ok=True)
        (pd / 'manifest.json').write_text(json.dumps({'schema': 'v8-posed/v1', 'coordinate_frame': 'world',
                                                     'parts': [str(pathlib.Path(obj).resolve())]}))
        objs.append({'posed_dir': str(pd)})
    wall = pathlib.Path(out_dir) / 'wall.obj'
    if not wall.exists():
        import v8_scene as S
        b = trimesh.creation.box(extents=[18.0, 1.2, 1.0]); b.apply_translation([5.0, S.WALL['y_inner'] - 0.6, 0.5])
        b.export(str(wall))
    pdw = pathlib.Path(out_dir) / 'posed_wall'; pdw.mkdir(parents=True, exist_ok=True)
    (pdw / 'manifest.json').write_text(json.dumps({'schema': 'v8-posed/v1', 'coordinate_frame': 'world', 'parts': [str(wall.resolve())]}))
    objs.append({'posed_dir': str(pdw)})
    spec['objects'] = objs
    return spec
