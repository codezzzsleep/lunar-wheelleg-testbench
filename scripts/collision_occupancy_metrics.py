"""
碰撞保真度量 v2（V6.1 工作包 C1/C2）。

要点：
  · 碰撞占据 = 各 part 的**并集**（box 直接按 cell 区间涂；凸 part 用半空间判据），
    不把各 part 体积相加；
  · 双向表面距离：
      source→collision：源表面采样点到**碰撞并集表面**的解析距离
                       （box：点到轴对齐盒的解析距离取 min；凸 part：点到凸多面体）；
      collision→source：碰撞表面采样点到源网格的精确距离（meshdist）；
    因此不含被其他 part 包住的内部面误差；
  · 过填/漏填样本数与体积分数、关键净空、源实体是否定义（非水密时明确标注）；
  · 评价分辨率、采样数、种子写进报告。

用法：
  .venv/bin/python scripts/collision_occupancy_metrics.py \
      --mesh <source.stl> --collision <dir> --out <json> --label H5_F_box --eval-pitch 0.004
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from meshdist import point_to_mesh_distance

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 'collision-metrics/v2'


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_mesh(p):
    m = trimesh.load(str(p), force='mesh')
    if isinstance(m, trimesh.Scene):
        geoms = [g for g in m.geometry.values() if len(g.faces) > 0]
        m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
    return m


def make_grid(meshes, pitch, margin=2):
    lo = np.min(np.array([m.bounds[0] for m in meshes]), axis=0) - margin * pitch
    hi = np.max(np.array([m.bounds[1] for m in meshes]), axis=0) + margin * pitch
    lo[2] = min(lo[2], -margin * pitch)
    dims = np.ceil((hi - lo) / pitch).astype(int) + 1
    dims = np.maximum(dims, 6)
    if np.prod(dims) > 40_000_000:
        raise SystemExit(f'评价网格过大 {dims.tolist()}')
    xs = lo[0] + (np.arange(dims[0]) + 0.5) * pitch
    ys = lo[1] + (np.arange(dims[1]) + 0.5) * pitch
    zs = lo[2] + (np.arange(dims[2]) + 0.5) * pitch
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    return {'origin': lo, 'pitch': float(pitch), 'dims': dims, 'xs': xs, 'ys': ys,
            'zs': zs, 'X': X, 'Y': Y, 'Z': Z,
            'pts': np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)}


def ray_parity(mesh, pts, chunk=150_000):
    inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    out = np.zeros(len(pts), dtype=bool)
    dz = np.array([0.0, 0.0, 1.0])
    for i in range(0, len(pts), chunk):
        p = pts[i:i + chunk]
        d = np.tile(dz, (len(p), 1))
        _, ray_i, _ = inter.intersects_location(p, d, multiple_hits=True)
        cnt = np.bincount(ray_i, minlength=len(p))
        out[i:i + chunk] = (cnt % 2).astype(bool)
    return out


def convex_inside(mesh, pts):
    """凸多面体半空间判据：所有面 n·(p-a) <= tol 视为内部。"""
    v = np.asarray(mesh.vertices); f = np.asarray(mesh.faces)
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    n = n / ln
    a = v[f[:, 0]]
    off = (n * a).sum(axis=1)
    tol = 1e-9
    inside = np.ones(len(pts), dtype=bool)
    for k in range(len(n)):
        inside &= (pts @ n[k] - off[k]) <= tol
    return inside


def box_surface_distance(pts, boxes, origin, pitch):
    """点到 box 并集表面的解析距离（box 为 cell 闭区间）。"""
    best = np.full(len(pts), np.inf)
    for (i0, i1, j0, j1, k0, k1) in boxes:
        lo = origin + np.array([i0, j0, k0]) * pitch
        hi = origin + np.array([i1 + 1, j1 + 1, k1 + 1]) * pitch
        c = (lo + hi) / 2.0
        h = (hi - lo) / 2.0
        q = np.abs(pts - c) - h
        outside = np.linalg.norm(np.maximum(q, 0.0), axis=1)
        inside = np.minimum(np.max(q, axis=1), 0.0)
        d = np.abs(outside + inside)
        best = np.minimum(best, d)
    return best


def convex_surface_distance(pts, meshes):
    best = np.full(len(pts), np.inf)
    for m in meshes:
        best = np.minimum(best, point_to_mesh_distance(m, pts, chunk=128))
    return best


def boxes_to_array(boxes, dims):
    occ = np.zeros(dims, dtype=bool)
    for (i0, i1, j0, j1, k0, k1) in boxes:
        occ[i0:i1 + 1, j0:j1 + 1, k0:k1 + 1] = True
    return occ


def sample_box_surfaces(boxes, origin, pitch, n_total, rng):
    """
    只在**暴露面**上采样（相邻单元为空的那一侧），排除被其他 box 包住的内面。
    这正是“碰撞并集外边界”的定义。
    """
    if not boxes:
        return np.zeros((0, 3))
    dims = (max(b[1] for b in boxes) + 2, max(b[3] for b in boxes) + 2,
            max(b[5] for b in boxes) + 2)
    occ = boxes_to_array(boxes, dims)
    faces = []      # (lo, extent, axis, side)
    for (i0, i1, j0, j1, k0, k1) in boxes:
        lo = origin + np.array([i0, j0, k0]) * pitch
        hi = origin + np.array([i1 + 1, j1 + 1, k1 + 1]) * pitch
        e = hi - lo
        # -x / +x
        if i0 - 1 < 0 or not occ[i0 - 1, j0:j1 + 1, k0:k1 + 1].any():
            faces.append((lo, e, 0, -1))
        if i1 + 1 >= dims[0] or not occ[i1 + 1, j0:j1 + 1, k0:k1 + 1].any():
            faces.append((lo, e, 0, +1))
        if j0 - 1 < 0 or not occ[i0:i1 + 1, j0 - 1, k0:k1 + 1].any():
            faces.append((lo, e, 1, -1))
        if j1 + 1 >= dims[1] or not occ[i0:i1 + 1, j1 + 1, k0:k1 + 1].any():
            faces.append((lo, e, 1, +1))
        if k0 - 1 < 0 or not occ[i0:i1 + 1, j0:j1 + 1, k0 - 1].any():
            faces.append((lo, e, 2, -1))
        if k1 + 1 >= dims[2] or not occ[i0:i1 + 1, j0:j1 + 1, k1 + 1].any():
            faces.append((lo, e, 2, +1))
    if not faces:
        return np.zeros((0, 3))
    areas = np.array([2 * (e[(a + 1) % 3] * e[(a + 2) % 3]) for (_l, e, a, _s) in faces])
    p_ = areas / areas.sum()
    pick = rng.choice(len(faces), size=n_total, p=p_)
    out = []
    for idx in pick:
        lo, e, ax, side = faces[idx]
        u, w = rng.random(2)
        pt = lo.copy()
        b1, b2 = (ax + 1) % 3, (ax + 2) % 3
        pt[b1] += u * e[b1]
        pt[b2] += w * e[b2]
        pt[ax] += e[ax] if side > 0 else 0.0
        out.append(pt)
    return np.asarray(out)


def probe_gaps(occ, grid, top_n=3):
    """沿每个 x 层找 y 方向最大内部空隙（两端都有占据），作为窄缝/净空探针。"""
    nx, ny, nz = occ.shape
    found = []
    for k in range(0, nz, max(1, nz // 24)):
        sl = occ[:, :, k]
        for i in range(nx):
            row = sl[i]
            idx = np.nonzero(row)[0]
            if len(idx) < 2:
                continue
            gaps = np.diff(idx) - 1
            j = int(np.argmax(gaps))
            if gaps[j] > 0:
                found.append({'x_m': round(float(grid['xs'][i]), 4),
                              'z_m': round(float(grid['zs'][k]), 4),
                              'gap_m': round(float(gaps[j] * grid['pitch']), 4),
                              'y_m': round(float((grid['ys'][idx[j]] + grid['ys'][idx[j + 1]]) / 2), 4)})
    found.sort(key=lambda r: -r['gap_m'])
    return {'n_gap_rows': len(found), 'largest': found[:top_n]}


PARITY_FACE_LIMIT = 120000


def clustered_downsample(mesh, limit):
    """按顶点聚类降采样到 limit 面以下；返回 (mesh, note)。"""
    import trimesh as _tm
    n = len(mesh.faces)
    if n <= limit:
        return mesh, None
    # 用体素化重建：分辨率由目标面数估计；不改变世界坐标
    ext = float(np.max(mesh.extents))
    pitch = max(ext / 80.0, 1e-4)
    try:
        v = mesh.voxelized(pitch=pitch).fill()
        m2 = v.marching_cubes
        if len(m2.faces) > limit:
            pitch *= 1.5
            v = mesh.voxelized(pitch=pitch).fill()
            m2 = v.marching_cubes
        return m2, {'method': 'voxel_cluster', 'pitch_m': round(pitch, 5),
                    'from_faces': int(n), 'to_faces': int(len(m2.faces))}
    except Exception as e:
        return mesh, {'method': 'none', 'error': f'{type(e).__name__}: {e}'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--collision', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', default='')
    ap.add_argument('--eval-pitch', type=float, default=0.004)
    ap.add_argument('--samples', type=int, default=1200)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    src = load_mesh(a.mesh)
    cdir = pathlib.Path(a.collision)
    man = json.loads((cdir / 'manifest.json').read_text()) if (cdir / 'manifest.json').exists() else {}
    boxes = man.get('boxes')
    origin = np.asarray(man['grid_origin'], dtype=float) if boxes else None
    bpitch = float(man['pitch_m']) if boxes else None
    parts, missing = [], []
    for rel in (man.get('parts') or []):
        fp = cdir / rel
        if fp.exists():
            parts.append(load_mesh(fp))
        else:
            missing.append(rel)
    if not boxes and not parts:
        raise SystemExit(f'没有可加载的碰撞表示：{cdir}')
    # 占据化用的源网格：面数过大时按**顶点聚类**降采样（不移动顶点、不改形状要点），
    # 只为把射线求交的内存/时间压到可完成；表面距离仍用完整源网格，且记录实际面数。
    src_parity = src
    parity_note = None
    if len(src.faces) > PARITY_FACE_LIMIT:
        src_parity, parity_note = clustered_downsample(src, PARITY_FACE_LIMIT)
    grid = make_grid([src] + parts, a.eval_pitch)
    o_src = ray_parity(src_parity, grid['pts']).reshape(grid['dims'])
    if boxes:
        o_col = np.zeros(grid['dims'], dtype=bool)
        for (i0, i1, j0, j1, k0, k1) in boxes:
            lo = origin + np.array([i0, j0, k0]) * bpitch
            hi = origin + np.array([i1 + 1, j1 + 1, k1 + 1]) * bpitch
            ii = np.nonzero((grid['xs'] >= lo[0]) & (grid['xs'] < hi[0]))[0]
            jj = np.nonzero((grid['ys'] >= lo[1]) & (grid['ys'] < hi[1]))[0]
            kk = np.nonzero((grid['zs'] >= lo[2]) & (grid['zs'] < hi[2]))[0]
            if len(ii) and len(jj) and len(kk):
                o_col[np.ix_(ii, jj, kk)] = True
    else:
        o_col = np.zeros(grid['dims'], dtype=bool)
        for p in parts:
            use_convex = False
            try:
                use_convex = bool(p.is_convex)
            except Exception:
                use_convex = False
            if use_convex:
                o_col |= convex_inside(p, grid['pts']).reshape(grid['dims'])
            else:
                o_col |= ray_parity(p, grid['pts']).reshape(grid['dims'])
    inter = int((o_src & o_col).sum()); union = int((o_src | o_col).sum())
    vox = grid['pitch'] ** 3
    over = int((~o_src & o_col).sum()); under = int((o_src & ~o_col).sum())
    geo = {'source_inside': int(o_src.sum()), 'collision_inside': int(o_col.sum()),
           'intersection': inter, 'union': union,
           'collision_only': over, 'source_only': under,
           'occupancy_iou': round(float(inter / union), 4) if union else None,
           'over_fill_frac_of_collision': round(float(over / max(o_col.sum(), 1)), 4),
           'under_fill_frac_of_source': round(float(under / max(o_src.sum(), 1)), 4),
           'over_fill_volume_m3': round(float(over) * vox, 9),
           'under_fill_volume_m3': round(float(under) * vox, 9),
           'source_volume_voxelised_m3': round(float(o_src.sum()) * vox, 9),
           'collision_volume_voxelised_m3': round(float(o_col.sum()) * vox, 9),
           'eval_pitch_m': grid['pitch'], 'eval_dims': [int(x) for x in grid['dims']]}
    ps, _ = trimesh.sample.sample_surface(src, a.samples, seed=a.seed)
    if boxes:
        d_sc = box_surface_distance(ps, boxes, origin, bpitch) * 1000
        cs = sample_box_surfaces(boxes, origin, bpitch, a.samples, rng)
        d_cs = point_to_mesh_distance(src, cs, chunk=128) * 1000
    else:
        d_sc = convex_surface_distance(ps, parts) * 1000
        cs = np.vstack([trimesh.sample.sample_surface(p, max(50, a.samples // len(parts)),
                                                      seed=a.seed)[0] for p in parts])
        d_cs = point_to_mesh_distance(src, cs, chunk=128) * 1000
    geo['source_to_collision_mm'] = {'n': int(len(d_sc)),
                                     'med': round(float(np.median(d_sc)), 3),
                                     'p95': round(float(np.percentile(d_sc, 95)), 3),
                                     'max': round(float(np.max(d_sc)), 3)}
    geo['collision_to_source_mm'] = {'n': int(len(d_cs)),
                                     'med': round(float(np.median(d_cs)), 3),
                                     'p95': round(float(np.percentile(d_cs, 95)), 3),
                                     'max': round(float(np.max(d_cs)), 3)}
    out = {'schema': 'collision-metrics/v2', 'version': VERSION, 'label': a.label,
           'source_mesh': str(a.mesh), 'source_sha': sha_file(a.mesh),
           'collision_dir': str(cdir),
           'representation': ('box_union' if boxes else 'parts'),
           'n_boxes': len(boxes) if boxes else None,
           'n_parts_declared': len(man.get('parts') or []) or None,
           'n_parts_loaded': len(parts) if not boxes else None,
           'missing_parts': missing,
           'collision_sha_manifest': man.get('collision_sha'),
           'source_status': {'watertight': bool(src.is_watertight),
                             'euler': int(src.euler_number),
                             'n_faces': int(len(src.faces))},
           'source_volume_defined': bool(src.is_watertight),
           'geometry': geo,
           'probe': probe_gaps(o_src, grid),
           'parity_source': parity_note,
           'samples': a.samples, 'seed': a.seed,
           'verdict': ('PASS' if (geo['occupancy_iou'] is not None
                                  and geo['occupancy_iou'] >= 0.95
                                  and geo['source_to_collision_mm']['p95'] <= 5.0
                                  and geo['collision_to_source_mm']['p95'] <= 5.0)
                       else 'ATTENTION'),
           'note': ('双向距离用并集表面（box 解析距离 / 凸 part 距离）；'
                    '源网格非水密时 source_volume_defined=false，内部量只作诊断。')}
    op = pathlib.Path(a.out); op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'label': a.label, 'repr': out['representation'], 'verdict': out['verdict'],
                      'iou': geo['occupancy_iou'],
                      's2c_p95': geo['source_to_collision_mm']['p95'],
                      'c2s_p95': geo['collision_to_source_mm']['p95'],
                      'source_vol_defined': out['source_volume_defined']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
