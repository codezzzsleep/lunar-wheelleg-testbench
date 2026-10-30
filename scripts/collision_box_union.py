"""
合并 box 碰撞参考路线（V6.1 工作包 C4）。

从**已验证的占据**构造轴对齐 box：沿 x 取连续实心 run，再把相同 run 沿 y、z 合并，
得到不跨越空隙的盒子集合。不填凹槽、不改变坐标、不二次缩放。

输出与 physicalize 相同的 manifest 形态（parts/*.stl + collision_sha），
使现有加载器可以直接把 boxes 当成碰撞部件使用。

用法：
  .venv/bin/python scripts/collision_box_union.py \
      --mesh <source.stl> --out <dir> --pitch 0.005 --hypothesis-id H5_F_box
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fuse_observed as FZ

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 'box-union/v1'


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def occupancy_from_mesh(mesh, pitch, margin=2):
    """表面采样 -> 壳 -> 非周期膨胀 -> 外部 flood fill（与融合一致的占据语义）。"""
    grid = FZ.make_grid(mesh, np.asarray(mesh.vertices), pitch, margin)
    occ, stats = FZ.parent_solid(mesh, grid, 1)
    return occ, grid, stats


def runs_along_x(occ):
    """每个 (j,k) 行上的连续 True 段：[i0, i1] 闭区间。"""
    nx, ny, nz = occ.shape
    runs = np.zeros((ny, nz), dtype=object)
    for j in range(ny):
        for k in range(nz):
            row = occ[:, j, k]
            if not row.any():
                runs[j, k] = [] if False else tuple()
                continue
            d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
            starts = np.nonzero(d == 1)[0]
            ends = np.nonzero(d == -1)[0] - 1
            runs[j, k] = tuple((int(a), int(b)) for a, b in zip(starts, ends))
    return runs


def merge_boxes_greedy(occ):
    """
    贪心最大盒：取字典序第一个剩余体素，先沿 x 尽量长，再沿 y、z 扩展，
    每次扩展都要求整块仍是实心。不跨越空隙、不填凹槽。
    """
    rem = occ.copy()
    nx, ny, nz = rem.shape
    boxes = []
    while rem.any():
        idx = np.argwhere(rem)
        i0, j0, k0 = (int(x) for x in idx[0])
        i1 = i0
        while i1 + 1 < nx and rem[i1 + 1, j0, k0]:
            i1 += 1
        j1 = j0
        while j1 + 1 < ny and rem[i0:i1 + 1, j1 + 1, k0].all():
            j1 += 1
        k1 = k0
        while k1 + 1 < nz and rem[i0:i1 + 1, j0:j1 + 1, k1 + 1].all():
            k1 += 1
        rem[i0:i1 + 1, j0:j1 + 1, k0:k1 + 1] = False
        boxes.append((i0, i1, j0, j1, k0, k1))
    return boxes


def merge_boxes(occ):
    """
    先把 x-runs 沿 y 合并成 (i0,i1,j0,j1,k)，再沿 z 合并成 box。
    只有 run 完全相同才合并，因此不会跨越空隙、不会填平凹槽。
    """
    nx, ny, nz = occ.shape
    runs = runs_along_x(occ)
    # y 方向合并
    slabs = {}   # (i0,i1) -> list of (j0,j1,k)
    for k in range(nz):
        active = {}   # run -> j0
        for j in range(ny):
            here = set(runs[j, k])
            for r in list(active):
                if r not in here:
                    j0 = active.pop(r)
                    slabs.setdefault(r, []).append((j0, j - 1, k))
            for r in here:
                if r not in active:
                    active[r] = j
        for r, j0 in active.items():
            slabs.setdefault(r, []).append((j0, ny - 1, k))
    # z 方向合并：(i0,i1,j0,j1) 连续 k
    boxes = []
    open_ = {}
    for k in range(nz):
        cur = {}
        for r, lst in slabs.items():
            for (j0, j1, kk) in lst:
                if kk == k:
                    cur[(r[0], r[1], j0, j1)] = True
        for key in list(open_):
            if key not in cur:
                boxes.append((*key, open_.pop(key), k - 1))
        for key in cur:
            if key not in open_:
                open_[key] = k
    for key, k0 in open_.items():
        boxes.append((*key, k0, nz - 1))
    return boxes


def box_mesh(i0, i1, j0, j1, k0, k1, grid):
    """cell 索引闭区间 -> 轴对齐盒（面在 cell 边界上，与 cell-center 约定一致）。"""
    pitch = grid['pitch']; origin = grid['origin']
    lo = origin + np.array([i0, j0, k0]) * pitch
    hi = origin + np.array([i1 + 1, j1 + 1, k1 + 1]) * pitch
    ext = np.maximum(hi - lo, 1e-6)
    m = trimesh.creation.box(extents=ext)
    m.apply_translation(list((lo + hi) / 2.0))
    return m


def cache_ok(outdir, mesh, pitch):
    """已有缓存是否可用于这份源网格与这个构建分辨率。"""
    mf = pathlib.Path(outdir) / 'manifest.json'
    if not mf.exists():
        return False, 'no manifest'
    man = json.loads(mf.read_text())
    ci = man.get('cache_identity') or {}
    if ci.get('source_sha') != sha_file(mesh):
        return False, 'source_sha mismatch'
    if abs(float(ci.get('build_pitch_m', -1)) - float(pitch)) > 1e-12:
        return False, 'pitch mismatch'
    if ci.get('algorithm') != VERSION:
        return False, 'algorithm mismatch'
    if ci.get('collision_sha') != man.get('collision_sha'):
        return False, 'collision_sha mismatch'
    return True, 'ok'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--pitch', type=float, default=0.005)
    ap.add_argument('--hypothesis-id', default='box_union')
    ap.add_argument('--max-geoms', type=int, default=0,
                    help='>0 时若超过则报错而不是悄悄降级')
    ap.add_argument('--reuse', action='store_true',
                    help='若缓存身份匹配则直接复用（不重建）；不匹配则报错退出')
    ap.add_argument('--force', action='store_true', help='配合 --reuse 时强制重建')
    a = ap.parse_args()
    src = pathlib.Path(a.mesh)
    if a.reuse and not a.force:
        ok, why = cache_ok(a.out, src, a.pitch)
        if ok:
            print(json.dumps({'reused': True, 'why': why, 'out': a.out}, ensure_ascii=False))
            return
        # 身份不匹配时**拒绝**复用，也不覆盖旧缓存（避免一次错参数把合格缓存冲掉）
        raise SystemExit(f'缓存身份不匹配（{why}）：拒绝复用；如确需重建请去掉 --reuse 或加 --force')
    mesh = FZ._load_mesh(src)
    occ, grid, stats = occupancy_from_mesh(mesh, a.pitch, margin=1)
    boxes = merge_boxes_greedy(occ)
    out = pathlib.Path(a.out); (out / 'parts').mkdir(parents=True, exist_ok=True)
    files = []
    total = 0.0
    for i, b in enumerate(boxes):
        m = box_mesh(*b, grid)
        rel = f'parts/box_{i:04d}.stl'
        m.export(out / rel)
        files.append(rel)
        total += float(np.prod(m.extents))
    h = hashlib.sha256()
    for rel in files:
        h.update(rel.encode())
        h.update(sha_file(out / rel).encode())
    collision_sha = h.hexdigest()[:32]
    man = {
        'schema': 'asset-manifest/v1', 'asset_id': out.name,
        'boxes': [[int(v) for v in b] for b in boxes],
        'hypothesis_id': a.hypothesis_id, 'version': VERSION,
        'coordinate_frame': 'world', 'source_kind': 'box_union',
        'parts': files, 'T_world_from_asset': np.eye(4).tolist(),
        'body_pose_expected': {'pos': [0.0, 0.0, 0.0], 'quat': [1.0, 0.0, 0.0, 0.0]},
        'world_sha': sha_file(src), 'raw_sha': sha_file(src),
        'collision_sha': collision_sha,
        'pitch_m': a.pitch, 'n_boxes': len(boxes),
        'n_source_voxels': int(occ.sum()),
        'boxes_volume_m3': round(float(total), 9),
        'grid_origin': [float(x) for x in grid['origin']],
        'grid_dims': [int(x) for x in grid['dims']],
        'pass': True, 'rest_pose': False, 'rescaled': False,
        'cache_identity': {
          'source_sha': sha_file(src),
          'build_pitch_m': float(a.pitch),
          'algorithm': VERSION,
          'solid_method': stats.get('solid_method'),
          'octree_or_parts': 'boxes',
          'n_boxes': int(len(boxes)),
          'collision_sha': collision_sha,
          'cache_key': None,
        },
        'near_convex_hull_substituted': False,
        'note': ('占据 -> 轴对齐 box 合并；不跨越空隙、不填凹槽、不改坐标。'
                 '碰撞几何与源网格仍有半体素离散误差，见 collision metrics。'),
    }
    ci = man['cache_identity']
    ci['cache_key'] = hashlib.sha256(json.dumps(
        {k: ci[k] for k in ('source_sha', 'build_pitch_m', 'algorithm', 'solid_method',
                            'n_boxes', 'collision_sha')}, sort_keys=True).encode()).hexdigest()[:32]
    # 原子写：进程被杀时不能留下半截 JSON（曾导致 metrics 反复失败却看不出原因）
    _tmp = out / 'manifest.json.tmp'
    _tmp.write_text(json.dumps(man, ensure_ascii=False, indent=2))
    _tmp.replace(out / 'manifest.json')
    if a.max_geoms and len(boxes) > a.max_geoms:
        raise SystemExit(f'box 数 {len(boxes)} 超过上限 {a.max_geoms}')
    print(json.dumps({'n_boxes': len(boxes), 'collision_sha': collision_sha,
                      'boxes_volume_m3': man['boxes_volume_m3'],
                      'source_voxels': man['n_source_voxels']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
