"""v3 融合：公共观测 V + FULL/OBS_ONLY 匹配消融（fuse-observed/v3.1）。

与旧 v3 的三个实质差别（都来自 SPEC §6.3 的合同）：

1. **栅格只由公共观测决定**。旧实现 make_grid(parent, vis) 让父候选包围盒参与定栅格，
   于是同一状态不同候选的栅格不同，"同一栅格"无从谈起。这里用可见点 + 固定外扩。
2. **V 是候选无关的共享实体**。V 只由观测深度/掩码/测量带生成，一次算好写盘、哈希绑定；
   FULL 与 OBS_ONLY 都读同一份 V，`OBS_ONLY ≡ V` 是**同一个数组**，不是重算一次碰巧相等。
3. **FULL = V ∪ (P ∩ U)**。父候选只在未知区提供隐藏几何；测量带（B）内不得用父候选
   取代或补充观测，自由区（F）不得被生成实体占据。消融 = 只减 U∩P，之后**不做任何**
   组件清理/补洞/闭合/重贴地/换栅格。

  python scripts/v3_fuse.py --state runs/v3/states/<sid> --protocol plans/v3_protocol.json
  python scripts/v3_fuse.py --state ... --parent mesh.stl --out <dir>   # 单候选
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import camera_io
import fuse_observed as FZ

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 'fuse-observed/v3.1-common'


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def arr_sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:32]


# --------------------------------------------------------------------------- grid
def frozen_grid(proto, vis):
    """只由公共观测决定的冻结栅格。同一状态的所有候选/OBS_ONLY/真值共用。"""
    v = proto['visibility']
    pitch = float(v['pitch_m'])
    margin = float(v['grid_margin_m'])
    hidden = max(float(v['grid_hidden_extent_m']),
                 1.10 * max(float(vis['W_vis']), float(vis['H_vis'])))
    x_front = float(vis['x_front'])
    y_c = float(vis['y_center'])
    half_y = float(vis['W_vis']) / 2.0 + max(0.10, 0.35 * float(vis['W_vis']))
    z_top = float(vis['H_vis']) + max(0.07, 0.30 * float(vis['H_vis']))
    lo = np.array([x_front - margin, y_c - half_y, 0.0], dtype=np.float64)
    hi = np.array([x_front + hidden, y_c + half_y, z_top], dtype=np.float64)
    # 对齐到体素中心网格
    lo = np.floor(lo / pitch) * pitch
    dims = np.maximum(np.ceil((hi - lo) / pitch).astype(int), 8)
    # 大岩石的栅格会超过上限：按状态自动把 pitch 放大到能装下为止（记录实际 pitch），
    # 而不是把大岩石整体排除（否则筛选会系统性偏向小石头）。
    while int(np.prod(dims)) > int(v['grid_max_voxels']):
        pitch = round(pitch * 1.15, 6)
        lo = np.floor(np.array([x_front - margin, y_c - half_y, 0.0]) / pitch) * pitch
        dims = np.maximum(np.ceil(np.array([hi[0] + hidden, hi[1], hi[2]]) / pitch
                                  - lo / pitch).astype(int), 8)
    g = {'origin': lo, 'pitch': pitch, 'dims': dims}
    xs = lo[0] + (np.arange(dims[0]) + 0.5) * pitch
    ys = lo[1] + (np.arange(dims[1]) + 0.5) * pitch
    zs = lo[2] + (np.arange(dims[2]) + 0.5) * pitch
    g['xs'], g['ys'], g['zs'] = xs, ys, zs
    return g


def _slice_centers(g, axis, i):
    """返回该切片所有体素中心 (N,3)，避免整块 meshgrid 的内存峰值。"""
    if axis == 0:
        a, b = np.meshgrid(g['ys'], g['zs'], indexing='ij')
        return np.stack([np.full(a.size, g['xs'][i]), a.ravel(), b.ravel()], axis=1)
    raise ValueError(axis)


# --------------------------------------------------------------- observation volume
def observe_volume(obs_dir, grid, proto, *, with_shell=True):
    """F/B/U 分类 + 公共观测壳层 V。只读观测，不读任何真值。"""
    obs_dir = pathlib.Path(obs_dir)
    obs = json.loads((obs_dir / 'observation.json').read_text())
    depth = np.load(obs_dir / 'depth.npy').astype(np.float64)
    from PIL import Image
    mask = np.array(Image.open(obs_dir / 'mask.png').convert('L')) > 127
    H, W = depth.shape
    v = proto['visibility']
    eps = float(v['free_epsilon_m'])
    band = float(v['band_m'])
    off = float(v['shell_offset_voxels']) * float(grid['pitch'])
    dims = tuple(int(x) for x in grid['dims'])
    space = np.zeros(dims, dtype=np.uint8)
    shell = np.zeros(dims, dtype=bool)
    cam = obs['camera']
    valid_depth = np.isfinite(depth) & (depth > 0) & (depth < 100.0)
    stats_n = {'free': 0, 'band': 0, 'unknown': 0, 'in_fov': 0, 'masked_fov': 0}
    for i in range(dims[0]):
        pts = _slice_centers(grid, 0, i)
        u, vv, z = camera_io.project(pts, cam)
        finite = np.isfinite(u) & np.isfinite(vv) & np.isfinite(z)
        in_fov = finite & (u >= 0) & (u <= W - 1) & (vv >= 0) & (vv <= H - 1) & (z > 0)
        ui = np.clip(np.nan_to_num(u, nan=-1), 0, W - 1).astype(np.int64)
        vi = np.clip(np.nan_to_num(vv, nan=-1), 0, H - 1).astype(np.int64)
        d = depth[vi, ui]
        d_ok = in_fov & np.isfinite(d) & (d > 0) & (d < 100.0)
        cls = np.zeros(len(pts), dtype=np.uint8)
        # 已知自由：到测量面之前（测量带外）
        cls[d_ok & (z < d - eps)] = 2
        # 测量带：只在掩码内（掩码外没有目标表面，不能当已知）
        m = mask[vi, ui]
        band_v = d_ok & m & (z >= d - eps + off) & (z <= d + band + off)
        cls[band_v] = 1
        sl = (slice(i, i + 1), slice(None), slice(None))
        space[sl] = cls.reshape(1, dims[1], dims[2])
        if with_shell:
            shell[sl] = band_v.reshape(1, dims[1], dims[2])
        stats_n['free'] += int((cls == 2).sum())
        stats_n['band'] += int((cls == 1).sum())
        stats_n['unknown'] += int((cls == 0).sum())
        stats_n['in_fov'] += int(in_fov.sum())
        stats_n['masked_fov'] += int((in_fov & m).sum())
    stats = {'n_voxels': int(np.prod(dims)), 'n_free': stats_n['free'],
             'n_band': stats_n['band'], 'n_unknown': stats_n['unknown'],
             'n_in_fov': stats_n['in_fov'], 'n_masked_fov': stats_n['masked_fov'],
             'n_shell': int(shell.sum()),
             'valid_depth_frac': round(float(valid_depth.mean()), 6),
             'free_eps_m': eps, 'band_m': band, 'shell_offset_m': off,
             'pitch_m': float(grid['pitch']),
             'depth_convention': 'positive_camera_minus_z'}
    return space, shell, stats, obs


def write_v_artifact(state_dir, proto, out_dir=None):
    """把 V / space / 栅格落成共享实体，并用哈希绑定输入。"""
    state_dir = pathlib.Path(state_dir)
    st = json.loads((state_dir / 'state.json').read_text())
    obs_dir = state_dir / 'observation'
    grid = frozen_grid(proto, st['visible'])
    space, shell, stats, obs = observe_volume(obs_dir, grid, proto)
    out = pathlib.Path(out_dir or (state_dir / 'fusion'))
    out.mkdir(parents=True, exist_ok=True)
    v_sha = arr_sha(shell)
    space_sha = arr_sha(space)
    np.savez_compressed(out / 'V.npz',
                        shell=shell, space=space,
                        origin=np.asarray(grid['origin'], float),
                        pitch=np.float64(grid['pitch']),
                        dims=np.asarray(grid['dims'], int),
                        v_sha=np.array(v_sha), space_sha=np.array(space_sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    man = {'schema': 'v3-observed-volume/v1', 'version': VERSION,
           'state_id': st['state_id'], 'grid': {'origin': [float(x) for x in grid['origin']],
                                                'pitch_m': float(grid['pitch']),
                                                'dims': [int(x) for x in grid['dims']]},
           'visible': st['visible'],
           'space_stats': stats, 'v_sha': v_sha, 'space_sha': space_sha,
           'observation_sha256': st['observation_sha256'],
           'camera': obs['camera'],
           'rule': 'V = 掩码内、测量面之后 [d-eps+off, d+band+off] 的有限厚度壳层；'
                   '不向未知区无限挤出；不做组件清理/补洞。',
           'shared_by': 'all FULL/OBS_ONLY candidates of this state (same bytes)'}
    (out / 'V.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    return {'dir': str(out), 'grid': grid, 'space': space, 'shell': shell,
            'stats': stats, 'v_sha': v_sha, 'space_sha': space_sha, 'obs': obs, 'man': man}


def load_v_artifact(vdir):
    d = np.load(pathlib.Path(vdir) / 'V.npz')
    grid = {'origin': np.asarray(d['origin'], float), 'pitch': float(d['pitch']),
            'dims': np.asarray(d['dims'], int)}
    pitch = grid['pitch']
    grid['xs'] = grid['origin'][0] + (np.arange(grid['dims'][0]) + 0.5) * pitch
    grid['ys'] = grid['origin'][1] + (np.arange(grid['dims'][1]) + 0.5) * pitch
    grid['zs'] = grid['origin'][2] + (np.arange(grid['dims'][2]) + 0.5) * pitch
    return {'grid': grid, 'space': d['space'], 'shell': d['shell'],
            'v_sha': str(d['v_sha']), 'space_sha': str(d['space_sha']),
            'man': json.loads((pathlib.Path(vdir) / 'V.json').read_text())}


# ------------------------------------------------------------------ voxelization
def voxelize_columns(mesh, grid, z_start=-0.05):
    """按列向上打射线，用交点区间填实心。

    对"贴地扫描件"（底部开口）也成立：奇数次交会时，地面到第一个交点之间算实体。
    """
    dims = tuple(int(x) for x in grid['dims'])
    occ = np.zeros(dims, dtype=bool)
    xs, ys = grid['xs'], grid['ys']
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    pts = np.stack([X.ravel(), Y.ravel(), np.full(X.size, z_start)], axis=1)
    d = np.tile(np.array([0.0, 0.0, 1.0]), (len(pts), 1))
    inter = FZ.trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    loc, ray_i, _ = inter.intersects_location(pts, d, multiple_hits=True)
    order = np.argsort(ray_i, kind='stable')
    loc, ray_i = loc[order], ray_i[order]
    zs = loc[:, 2]
    # 逐列切段
    bounds = np.searchsorted(ray_i, np.arange(len(pts) + 1))
    breaks = np.searchsorted(ray_i, np.unique(ray_i))
    uniq = np.unique(ray_i)
    zc = grid['origin'][2] + (np.arange(dims[2]) + 0.5) * grid['pitch']
    for k, ridx in enumerate(uniq):
        s = breaks[k]
        e = breaks[k + 1] if k + 1 < len(breaks) else len(ray_i)
        zz = np.sort(zs[s:e])
        if len(zz) == 1:
            lo, hi = max(0.0, z_start), zz[0]
            pairs = [(lo, hi)]
        else:
            pairs = []
            idx = 0
            if len(zz) % 2 == 1:
                pairs.append((max(0.0, z_start), zz[0]))
                idx = 1
            while idx + 1 < len(zz):
                pairs.append((zz[idx], zz[idx + 1]))
                idx += 2
        i, j = divmod(int(ridx), dims[1])
        for lo, hi in pairs:
            occ[i, j] |= (zc >= lo) & (zc <= hi)
    return occ, {'method': 'column_rays', 'n_columns': int(len(pts)),
                 'n_columns_hit': int(len(uniq))}


def truth_occupancy(state_dir, proto):
    state_dir = pathlib.Path(state_dir)
    art = load_v_artifact(state_dir / 'fusion')
    import trimesh
    tm = trimesh.load(state_dir / 'truth' / 'body_world.stl', force='mesh', process=False)
    occ, info = voxelize_columns(tm, art['grid'])
    info['mesh'] = 'truth/body_world.stl'
    info['mesh_sha256'] = sha256_file(state_dir / 'truth' / 'body_world.stl')
    return occ, info, art


# ------------------------------------------------------------------------- fusion
def fuse_parent(art, parent_mesh, out_dir, parent_id, proto, with_mesh=False):
    """FULL = V ∪ (P ∩ U)；OBS_ONLY = V（同一份数组）。不做消融后处理。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    grid = art['grid']
    V = art['shell']
    space = art['space']
    U = (space == 0)
    B = (space == 1)
    F = (space == 2)
    P, pinfo = voxelize_columns(parent_mesh, grid)
    gen_U = P & U
    FULL = V | gen_U
    OBS = V                                   # 同一个对象/字节
    # ---- 合同断言（失败即拒绝，不静默继续） ----
    assert np.array_equal(OBS, V), 'OBS_ONLY 必须逐体素等于 V'
    diff = FULL & ~OBS
    assert not (diff & ~U).any(), 'FULL 与 OBS_ONLY 的差必须在 U 内'
    assert not (FULL & F).any(), '自由空间被实体占据'
    assert not (OBS & F).any(), 'V 落进自由空间'
    band_ok = np.array_equal(OBS & B, V & B) and np.array_equal(FULL & B & ~gen_U, OBS & B & ~gen_U)
    assert band_ok, '测量带在 FULL/OBS_ONLY 之间不一致'
    gen_in_B = int((P & B & ~V).sum())
    stats = {
        'n_parent_voxels': int(P.sum()), 'n_generated_unknown': int(gen_U.sum()),
        'n_full': int(FULL.sum()), 'n_obs_only': int(OBS.sum()),
        'n_v': int(V.sum()), 'n_free': int(F.sum()), 'n_unknown': int(U.sum()),
        'n_band': int(B.sum()),
        'parent_in_band_not_added': int(gen_in_B),
        'full_minus_obs': int(diff.sum()),
        'free_violations_full': int((FULL & F).sum()),
        'free_violations_obs': int((OBS & F).sum()),
        'kept_ratio_of_generated': round(float(gen_U.sum()) / max(1, int(P.sum())), 5),
        'assertions': {'obs_equals_v': True, 'diff_subset_u': True,
                       'free_clear': True, 'band_consistent': True},
    }
    full_sha = arr_sha(FULL)
    obs_sha = arr_sha(OBS)
    np.savez_compressed(out / 'occ_full.npz', occupied=FULL,
                        origin=np.asarray(grid['origin'], float),
                        pitch=np.float64(grid['pitch']),
                        dims=np.asarray(grid['dims'], int),
                        content_sha=np.array(full_sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    np.savez_compressed(out / 'occ_obs_only.npz', occupied=OBS,
                        origin=np.asarray(grid['origin'], float),
                        pitch=np.float64(grid['pitch']),
                        dims=np.asarray(grid['dims'], int),
                        content_sha=np.array(obs_sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    # 网格（只用于显示/揭晓；碰撞用 box union）
    mesh = None
    if with_mesh:
        try:
            mesh = FZ.marching_tets(FULL, grid)
            mesh.export(out / 'body.stl')
        except Exception as e:  # noqa: BLE001
            (out / 'mesh_error.txt').write_text(f'{type(e).__name__}: {e}')
    man = {'schema': 'v3-fused/v1', 'version': VERSION, 'parent_id': parent_id,
           'artifact_status': 'complete',
           'state_id': art['man']['state_id'],
           'grid': art['man']['grid'],
           'v_sha': art['v_sha'], 'space_sha': art['space_sha'],
           'observer_sha256': art['man']['observation_sha256'],
           'full_occ_sha': full_sha, 'obs_only_occ_sha': obs_sha,
           'parent_mesh_sha256': parent_id.get('mesh_sha256') if isinstance(parent_id, dict) else None,
           'parent_solid': pinfo, 'stats': stats,
           'formula': 'FULL = V | (P & U); OBS_ONLY = V',
           'ablation': {'mode': 'delete_generated_unknown_from_full',
                        'removed_voxels': int(gen_U.sum()),
                        'post_processing_after_ablation': 'none',
                        'note': '不重跑组件清理/补洞/闭合/重贴地/换栅格'},
           'mesh': ('body.stl' if mesh is not None else None),
           'seconds': None}
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    return man, stats


def write_truth_occ(state_dir, proto):
    occ, info, art = truth_occupancy(state_dir, proto)
    d = pathlib.Path(state_dir) / 'truth'
    np.savez_compressed(d / 'truth_occ.npz', occupied=occ,
                        origin=np.asarray(art['grid']['origin'], float),
                        pitch=np.float64(art['grid']['pitch']),
                        dims=np.asarray(art['grid']['dims'], int),
                        content_sha=np.array(arr_sha(occ)),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    (d / 'truth_occ.json').write_text(json.dumps(
        {'schema': 'v3-truth-occ/v1', **info, 'n_voxels': int(occ.sum()),
         'sha': arr_sha(occ)}, ensure_ascii=False, indent=2))
    return occ, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--parent', default=None, help='已配准到世界的父候选 body.stl')
    ap.add_argument('--parent-id', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--truth', action='store_true')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    if a.truth:
        occ, info = write_truth_occ(ROOT / a.state, proto)
        print(json.dumps({'truth_voxels': int(occ.sum()), **info}, ensure_ascii=False))
        return
    art = write_v_artifact(ROOT / a.state, proto)
    if a.parent:
        import trimesh
        m = trimesh.load(a.parent, force='mesh', process=False)
        out = a.out or str(pathlib.Path(a.state) / 'fusion' / 'parent_test')
        man, stats = fuse_parent(art, m, out, {'id': a.parent_id or 'parent',
                                               'mesh_sha256': sha256_file(a.parent)}, proto)
        print(json.dumps({'out': out, 'stats': stats}, ensure_ascii=False))
    else:
        print(json.dumps({'V': art['v_sha'], 'stats': art['stats']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
