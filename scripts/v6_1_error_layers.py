"""
V6.1：融合误差分层定位（S0–S3）。

同一相机快照、同一机器人状态、同一原生分辨率、同一冻结评价器下，逐层加入处理，
看误差**第一次出现在哪一步**：

  S0  真值世界网格，直接用正式 posed 路径加载并评价（不复制、不融合）
  S1  同一网格复制到新目录、重载后再评价（导出/放置/加载是否引入误差）
  S2  父候选只做占据化 + 网格提取（无自由空间雕刻、无观测壳）
  S3  加入自由空间雕刻（无观测壳）
  S4  再加入观测壳（当前正式融合规则）

每组输出：IoU、可见点距离、freespace（含违例像素/分母）、有符号深度残差、
内部/轮廓分列、残差热图、输入与网格身份。

  .venv/bin/python scripts/v6_1_error_layers.py \
      --observation runs/unseen/delivery_v6_1/v6_1_20261029/fixtures/F0/observation \
      --parent-world runs/unseen/delivery_v6_1/v6_1_20261029/fixtures/F0/truth \
      --out runs/unseen/delivery_v6_1/v6_1_20261029/layers/F0
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import align
import camera_io
import fuse_observed as FZ
from meshdist import point_to_mesh_distance

ROOT = pathlib.Path(__file__).resolve().parent.parent


def eval_mesh(mesh, observation, tag, outdir):
    """冻结评价器：与正式融合完全相同的调用路径。"""
    tmp = outdir / f'{tag}.stl'; mesh.export(tmp)
    m = align.render_eval(mesh, str(observation), tmpdir=str(tmp), W=None, H=None,
                          want_vis_pt=False)
    vis = np.load(pathlib.Path(observation) / 'visible_points.npy')
    if len(vis) > 1200:
        vis = vis[np.random.default_rng(0).choice(len(vis), 1200, replace=False)]
    nn = point_to_mesh_distance(mesh, vis, chunk=64) * 1000
    m['vis_pt_med_mm'] = round(float(np.median(nn)), 3)
    m['vis_pt_p95_mm'] = round(float(np.percentile(nn, 95)), 3)
    m['vis_pt_n'] = int(len(nn))
    m['watertight'] = bool(mesh.is_watertight)
    m['volume_m3'] = round(abs(float(mesh.volume)), 9) if mesh.is_watertight else None
    m['n_faces'] = int(len(mesh.faces))
    m['bounds'] = [[round(float(x), 5) for x in b] for b in mesh.bounds]
    return m


def residual_heatmap(mesh, observation, out_png, W=None, H=None):
    """有符号深度残差热图（候选 - 观测，负值=候选更近）。"""
    import mujoco
    import os
    out_png = pathlib.Path(out_png)
    obs = json.loads((pathlib.Path(observation) / 'observation.json').read_text())
    W = W or int(obs['image']['W']); H = H or int(obs['image']['H'])
    spec = {'objects': [{'posed_dir': str(out_png.with_suffix('.meshdir'))}], 'seed': 0}
    d = out_png.with_suffix('.meshdir'); d.mkdir(parents=True, exist_ok=True)
    mesh.export(d / 'body.stl')
    (d / 'manifest.json').write_text(json.dumps({'parts': ['body.stl']}))
    import terrain, wheelleg_env
    s = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.8, name='resid')
    s['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    s['skill_cfg'] = {'task': 'M'}
    s['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    s['objects'] = [{'posed_dir': str(d)}]
    s['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0,
                      'fovy': obs['camera']['fovy_deg']}
    env = wheelleg_env.WheelLegEnv(s); env.reset(seed=0)
    m, dd = env.model, env.data
    m.vis.global_.offwidth = W; m.vis.global_.offheight = H
    mujoco.mj_forward(m, dd)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    camera_io.restore(m, dd, cid, obs['camera'])
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    r = mujoco.Renderer(m, H, W); r.enable_depth_rendering()
    r.update_scene(dd, camera=cid); with_obj = r.render().copy()
    keep = m.body_pos[bid].copy(); m.body_pos[bid] = [0, 0, -80]; mujoco.mj_forward(m, dd)
    r.update_scene(dd, camera=cid); without = r.render().copy()
    m.body_pos[bid] = keep; mujoco.mj_forward(m, dd)
    od = np.load(pathlib.Path(observation) / 'depth.npy')
    valid = np.isfinite(od) & (od > 0)
    cand = with_obj < without - 1e-3
    resid = np.full((H, W), np.nan)
    sel = cand & valid
    resid[sel] = (with_obj[sel] - od[sel]) * 1000.0
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[..., 0] = 40
    img[..., 1] = 40
    img[..., 2] = 40
    v = np.clip(resid, -20, 20)
    img[..., 0][sel & (v > 0)] = 220        # 候选更远 = 红（漏填/后移）
    img[..., 1][sel & (v > 0)] = 80
    img[..., 2][sel & (v > 0)] = 80
    img[..., 1][sel & (v < 0)] = 220        # 候选更近 = 绿（前突）
    img[..., 0][sel & (v < 0)] = 80
    img[..., 2][sel & (v < 0)] = 80
    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(out_png)
    return {'png': str(out_png), 'n_cand_px': int(cand.sum()),
            'resid_pct_mm': (np.nanpercentile(v[sel], [5, 25, 50, 75, 95]).round(3).tolist()
                             if sel.any() else None)}


def build_variants(observation, parent_world, cfg, ablate):
    parent = FZ._load_mesh(parent_world / 'body.stl')
    vis = np.load(pathlib.Path(observation) / 'visible_points.npy')
    pitch = float(cfg['pitch_m'])
    grid = FZ.make_grid(parent, vis, pitch, int(cfg['margin_cells']))
    space, space_stats = FZ.classify_space(observation, grid,
                                           float(cfg['free_epsilon_m']),
                                           float(cfg['band_m']),
                                           (float(cfg['depth_edge_threshold_m'])
                                            if cfg.get('use_depth_edge_exclusion') else 0.0))
    parent_inside, parent_stats = FZ.parent_solid(parent, grid, int(cfg['parent_dilate_voxels']))
    keep_p = parent_inside & (space != 2)
    obs = json.loads((pathlib.Path(observation) / 'observation.json').read_text())
    mask = np.array(Image.open(pathlib.Path(observation) / 'mask.png').convert('L')) > 127
    H, W = mask.shape
    mask_d = FZ.dilate2(mask, int(cfg['mask_dilate_px']))
    u, v, z = camera_io.project(
        np.stack([grid['X'].ravel(), grid['Y'].ravel(), grid['Z'].ravel()], axis=1),
        obs['camera'])
    in_fov = (np.isfinite(u) & np.isfinite(v) & (z > 0)
              & (u >= 0) & (u <= W - 1) & (v >= 0) & (v <= H - 1))
    ui = np.clip(np.nan_to_num(u, nan=-1), 0, W - 1).astype(np.int64)
    vi = np.clip(np.nan_to_num(v, nan=-1), 0, H - 1).astype(np.int64)
    depth = np.load(pathlib.Path(observation) / 'depth.npy')
    d_at = np.full(len(in_fov), np.nan)
    sel = in_fov & np.isfinite(z)
    d_at[sel] = depth[vi[sel], ui[sel]]
    off = float(cfg.get('shell_offset_voxels', 0.5)) * pitch
    shell = (in_fov & mask_d[vi, ui] & np.isfinite(d_at)
             & (z >= d_at - float(cfg['free_epsilon_m']) + off)
             & (z <= d_at + float(cfg['band_m']) + off)).reshape(grid['dims'])
    out = {}
    variants = {
        'S2_parent_only': parent_inside,
        'S3_carved': keep_p,
        'S4_carved_plus_shell': keep_p | shell,
    }
    for k, occ in variants.items():
        if ablate and k not in ablate:
            continue
        o = occ.copy()
        o, _ = FZ.largest_component(o)
        mesh = FZ.marching_tets(o, grid)
        if len(mesh.faces) and not mesh.is_watertight and cfg.get('fill_holes', True):
            trimesh.repair.fill_holes(mesh); trimesh.repair.fix_normals(mesh)
        out[k] = mesh
    return out, {'space': space_stats, 'parent': parent_stats, 'n_shell': int(shell.sum()),
                 'n_parent_inside': int(parent_inside.sum()), 'n_carved': int(keep_p.sum()),
                 'n_shell_outside_parent': int((shell & ~parent_inside).sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--observation', required=True)
    ap.add_argument('--parent-world', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--config', default='configs/unseen_v6_1_fusion.json')
    ap.add_argument('--label', default='S0-S4')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfg = FZ.load_effective_config(a.config)
    rows = []
    # S0：真值/父实体原始文件直接评价
    raw = FZ._load_mesh(pathlib.Path(a.parent_world) / 'body.stl')
    rows.append({'step': 'S0_raw_direct', 'what': '原文件直接加载评价，无复制、无融合',
                 **eval_mesh(raw, a.observation, 'S0', out)})
    rows[-1]['heatmap'] = residual_heatmap(raw, a.observation, out / 'heat_S0.png')
    # S1：复制 + 重载（模拟导出/放置/加载）
    d1 = out / 'reload'; d1.mkdir(exist_ok=True)
    raw.export(d1 / 'body.stl')
    (d1 / 'manifest.json').write_text(json.dumps({'parts': ['body.stl']}))
    m1 = FZ._load_mesh(d1 / 'body.stl')
    rows.append({'step': 'S1_reload', 'what': '导出→重载→正式 posed 路径加载，无融合',
                 'sha_equal': bool(FZ.sha_file(d1 / 'body.stl')
                                   == FZ.sha_file(pathlib.Path(a.parent_world) / 'body.stl')),
                 **eval_mesh(m1, a.observation, 'S1', out)})
    rows[-1]['heatmap'] = residual_heatmap(m1, a.observation, out / 'heat_S1.png')
    # S2/S3/S4：占据化 / 加雕刻 / 加壳
    meshes, info = build_variants(a.observation, pathlib.Path(a.parent_world), cfg, None)
    for k, mesh in meshes.items():
        rows.append({'step': k, 'what': ('父候选仅占据化+网格提取' if k == 'S2_parent_only'
                                         else ('加自由空间雕刻' if k == 'S3_carved'
                                               else '再加观测壳（正式融合规则）')),
                     **eval_mesh(mesh, a.observation, k, out)})
        rows[-1]['heatmap'] = residual_heatmap(mesh, a.observation, out / f'heat_{k}.png')
    rep = {'schema': 'error-layers/v6_1', 'label': a.label,
           'observation': str(a.observation), 'parent_world': str(a.parent_world),
           'config': cfg, 'grid_info': info,
           'camera_sha': FZ.sha_file(pathlib.Path(a.observation) / 'observation.json'),
           'rows': rows,
           'reading': ('S0/S1 正常而 S2 开始变差 -> 离散化；S2/S3 正常而 S4 变差 -> 观测壳；'
                       'S0 已异常 -> 观测/评价一致性')}
    (out / 'layers.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    for r in rows:
        print(r['step'], 'iou', r.get('iou'), 'p95', r.get('vis_pt_p95_mm'),
              'free', r.get('freespace_violation'),
              'signed_med', (r.get('heatmap') or {}).get('resid_pct_mm'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
