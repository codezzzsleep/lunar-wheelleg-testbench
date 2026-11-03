"""V0：逐层追踪隐藏几何（S0 原始 GLB → S6 预演加载），并在同一栅格/ROI 下比真值。

  python scripts/v3_vtrace.py --state runs/v3/states/<sid> [--candidate A1]

对每个候选写 runs/v3/states/<sid>/vtrace/<cid>.json：
  S0 原始 GLB：mesh/scene 组成、顶点/面数、单位、AABB、连通分量、水密/开底、原始 SHA
  S1 精配准：最终 M、刚体/尺度部分、变换后 AABB/体积、parent_world SHA
  S2 占据化：P 总数、pitch/origin/dims、grid SHA、实体化方法、栅格外被裁剪比例
  S3 空间分类：P∩F / P∩B / P∩U 与 P 核对（守恒 P = 三者和）
  S4 融合：V、P∩U、FULL、FULL−V 的体素与哈希；FULL−V 必须恰等于 P∩U、OBS_ONLY 恰等于 V
  S5 碰撞：2mm→4mm 前后隐藏增量、源占据 SHA、实际 collision SHA（来自 coll/manifest）
  S6 预演加载：矩阵里记录的 initial_full_hash 与本次融合 FULL 哈希是否一致
真值比较：同一 grid/同一 U/同一 ROI 下 T∩U 与 P∩U 的交集、漏填、过填、IoU。

只读产物，不改任何几何；诊断切片只用于人看，不回灌规划栅格。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import v3_fuse as FZ


def jl(p, d=None):
    p = pathlib.Path(p)
    if not p.is_file():
        return d
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


def arr_sha(a):
    return FZ.arr_sha(np.ascontiguousarray(a))


def _mesh_info(mesh):
    import trimesh
    comps = mesh.split(only_watertight=False)
    return {'n_vertices': int(len(mesh.vertices)), 'n_faces': int(len(mesh.faces)),
            'aabb': [[float(x) for x in mesh.bounds[0]],
                     [float(x) for x in mesh.bounds[1]]],
            'extents': [float(x) for x in mesh.extents],
            'volume_m3': float(abs(mesh.volume)) if mesh.is_volume else None,
            'is_watertight': bool(mesh.is_watertight),
            'is_volume': bool(mesh.is_volume),
            'n_components': int(len(comps)),
            'units': 'm (glTF)'}


def _roi_mask(grid, proto, U):
    he = proto.get('hidden_error', {})
    half = float(he.get('corridor_half_m', 0.16))
    x_front = float(proto['scene'].get('obstacle_x', 1.35))
    extent = float(proto['visibility'].get('hidden_extent_m', 0.4))
    xs = grid['xs'][:, None, None]
    ys = grid['ys'][None, :, None]
    in_x = (xs >= x_front - 1e-6) & (xs <= x_front + extent + 1e-6)
    in_y = np.abs(ys) <= half
    m = np.broadcast_to(in_x & in_y, U.shape).copy()
    return m & U


def trace_candidate(state_dir, proto, cid):
    state_dir = pathlib.Path(state_dir)
    out = state_dir / 'candidates' / cid
    art = FZ.load_v_artifact(state_dir / 'fusion')
    grid = art['grid']
    V, space = art['shell'], art['space']
    U, B, F = (space == 0), (space == 1), (space == 2)
    cand = jl(out / 'candidate.json', {}) or {}
    tr = {'schema': 'v3-v0trace/v1', 'state_id': state_dir.name, 'candidate': cid,
          'grid': {'origin': [float(x) for x in grid['origin']],
                   'pitch': float(grid['pitch']),
                   'dims': [int(x) for x in grid['dims']],
                   'grid_sha256': jl(state_dir / 'fusion' / 'V.json', {}).get('grid_sha256')}}
    # ---- S0 原始 GLB ----
    raw = cand.get('glb_path') or cand.get('source_glb') or cand.get('parent_source')
    # 旧批次 candidate.json 没写 glb_path：用 identity 回到生成缓存里找原始 GLB，
    # 找不到就明确记 missing（不允许把 parent_world 当成原始件）。
    if not raw:
        ident = cand.get('identity')
        if isinstance(ident, dict):
            ident = ident.get('identity') or ident.get('id')
        cand_cache = state_dir.parent.parent / 'generation' / 'cache'
        for guess in ([cand_cache / str(ident) / 'model.glb'] if ident else []):
            if pathlib.Path(guess).is_file():
                raw = str(pathlib.Path(guess).relative_to(ROOT))
                break
    s0 = {'path': raw, 'status': 'missing'}
    if raw and (ROOT / raw).is_file():
        try:
            import trimesh
            m = trimesh.load(ROOT / raw, force='mesh', process=False)
            s0 = {'path': raw, 'status': 'ok', 'sha256': FZ.sha256_file(ROOT / raw),
                  **_mesh_info(m)}
        except Exception as e:  # noqa: BLE001
            s0 = {'path': raw, 'status': f'load_error:{type(e).__name__}: {e}'[:200]}
    tr['S0_raw_glb'] = s0
    # ---- S1 配准 ----
    mesh_p = out / 'parent_world' / 'body.stl'
    reg = cand.get('registration') or cand.get('align') or {}
    s1 = {'parent_world': str(mesh_p.relative_to(ROOT)), 'status': 'missing'}
    if mesh_p.is_file():
        try:
            import trimesh
            m = trimesh.load(mesh_p, force='mesh', process=False)
            s1 = {'parent_world': str(mesh_p.relative_to(ROOT)),
                  'status': 'ok', 'sha256': FZ.sha256_file(mesh_p), **_mesh_info(m)}
        except Exception as e:  # noqa: BLE001
            s1 = {'status': f'load_error:{type(e).__name__}: {e}'[:200]}
    s1['registration'] = {k: reg.get(k) for k in
                          ('matrix', 'scale', 'rigid', 'mask_iou', 'surface_median_mm',
                           'surface_p95_mm', 'method', 'matrix_sha256')
                          if k in reg} if isinstance(reg, dict) else reg
    if (s0.get('status') == 'ok' and s1.get('status') == 'ok'):
        s1['extent_ratio_parent_over_raw'] = [
            round(float(b) / float(a), 4) if a else None
            for a, b in zip(s0.get('extents') or [], s1.get('extents') or [])]
        s1['volume_ratio_parent_over_raw'] = (
            round(float(s1['volume_m3']) / float(s0['volume_m3']), 5)
            if s0.get('volume_m3') and s1.get('volume_m3') else None)
    tr['S1_registration'] = s1
    # ---- S2 占据化 ----
    P = None
    if mesh_p.is_file():
        try:
            import trimesh
            m = trimesh.load(mesh_p, force='mesh', process=False)
            P, pinfo = FZ.voxelize_columns(m, grid)
        except Exception as e:  # noqa: BLE001
            tr['S2_occupancy'] = {'status': f'voxelize_error:{type(e).__name__}: {e}'[:200]}
    if P is not None:
        b = m.bounds
        lo = np.asarray(grid['origin'], float)
        hi = lo + np.asarray(grid['dims'], float) * float(grid['pitch'])
        outside = np.clip(lo - b[0], 0, None) + np.clip(b[1] - hi, 0, None)
        frac_clip = float((outside > 0).any())
        tr['S2_occupancy'] = {
            'status': 'ok', 'n_parent_voxels': int(P.sum()),
            'pitch_m': float(grid['pitch']), 'dims': [int(x) for x in grid['dims']],
            'method': 'voxelize_columns（列射线区间填实心，开底扫描从地面起算）',
            'occ_sha256': arr_sha(P), 'mesh_bounds': [[float(x) for x in b[0]],
                                                      [float(x) for x in b[1]]],
            'clipped_by_grid_any_axis': frac_clip,
            'volume_voxel_m3': float(P.sum()) * float(grid['pitch']) ** 3}
    # ---- S3 空间分类 ----
    if P is not None:
        pF, pB, pU = int((P & F).sum()), int((P & B).sum()), int((P & U).sum())
        tr['S3_classification'] = {
            'P': int(P.sum()), 'P_and_F': pF, 'P_and_B': pB, 'P_and_U': pU,
            'conservation_ok': (pF + pB + pU) == int(P.sum()),
            'carved_by_free': pF, 'replaced_in_band': pB, 'kept_in_unknown': pU}
        # ---- S4 融合 ----
        gen_U = P & U
        FULL = V | gen_U
        full_saved = np.load(out / 'fused' / 'occ_full.npz')['occupied']
        obs_saved = np.load(out / 'fused' / 'occ_obs_only.npz')['occupied']
        tr['S4_fusion'] = {
            'n_v': int(V.sum()), 'n_generated_unknown': int(gen_U.sum()),
            'n_full_recomputed': int(FULL.sum()), 'n_full_saved': int(full_saved.sum()),
            'n_obs_saved': int(obs_saved.sum()),
            'full_minus_v': int((FULL & ~V).sum()),
            'full_minus_v_equals_p_and_u': bool(np.array_equal(FULL & ~V, gen_U)),
            'obs_equals_v': bool(np.array_equal(obs_saved, V)),
            'recomputed_equals_saved': bool(np.array_equal(FULL, full_saved.astype(bool))),
            'free_violations_full': int((FULL & F).sum()),
            'free_violations_obs': int((obs_saved.astype(bool) & F).sum())}
        # ---- S5 碰撞 ----
        coll = jl(out / 'coll' / 'manifest.json', {}) or {}
        coll_obs = jl(state_dir / 'obs_only' / 'coll' / 'manifest.json', {}) or {}
        fused_sha = arr_sha(full_saved.astype(bool))
        def _verdict(src):
            if not src:
                return 'unverifiable_legacy'
            if len(src) == 32:
                # 旧清单把内容 SHA 截断成 32 位：只能做前缀核对，不能判 mismatch
                return 'legacy_32hex_prefix_ok' if fused_sha.startswith(src) else \
                    'legacy_32hex_unverifiable'
            return 'ok' if src == fused_sha else 'mismatch'
        tr['S5_collision'] = {
            'identity_verdict': _verdict((coll.get('source') or {}).get('occ_sha256')),
            'fused_full_sha256': fused_sha,
            'hash_len_note': '全部为 64 位十六进制内容 SHA；初态哈希与几何哈希不同名不同义',
            'full': {'n_boxes': coll.get('n_boxes'), 'collision_sha': coll.get('collision_sha'),
                     'source': coll.get('source'), 'params': coll.get('params'),
                     'algo': coll.get('algo'), 'cache_key': coll.get('cache_key')},
            'obs_only': {'n_boxes': coll_obs.get('n_boxes'),
                         'collision_sha': coll_obs.get('collision_sha'),
                         'source': coll_obs.get('source'), 'params': coll_obs.get('params')},
            'hidden_increment_boxes': (None if coll.get('n_boxes') is None
                                       or coll_obs.get('n_boxes') is None
                                       else int(coll['n_boxes']) - int(coll_obs['n_boxes'])),
            'source_matches_fusion': _verdict((coll.get('source') or {}).get('occ_sha256')) == 'ok'}
        # ---- S6 预演加载 ----
        mat = state_dir / 'decision' / 'matrix_FULL.jsonl'
        hashes = set()
        if mat.is_file():
            for line in mat.read_text().splitlines():
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get('candidate') == cid and r.get('initial_full_hash'):
                    hashes.add(r['initial_full_hash'])
        geom_ids = set()
        if mat.is_file():
            for line in mat.read_text().splitlines():
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get('candidate') == cid and r.get('geometry_id'):
                    geom_ids.add(r['geometry_id'])
        tr['S6_rehearsal_loaded'] = {
            # 这两个是不同的东西：initial_full_hash 是 runner 对初态 qpos/qvel 的哈希，
            # geometry_id 是碰撞清单里源占据的内容 SHA。禁止交叉比较。
            'initial_state_hashes_in_matrix': sorted(hashes)[:4],
            'geometry_ids_in_matrix': sorted(geom_ids)[:4],
            'geometry_matches_fused_full': (fused_sha in geom_ids) if geom_ids else None,
            'geometry_status': ('ok' if geom_ids and fused_sha in geom_ids
                                else ('mismatch' if geom_ids else 'unverifiable_legacy')),
            'note': ('初态哈希 != 几何哈希；旧矩阵没有 geometry_id，只能记 unverifiable_legacy')}
        # ---- 真值（同一 grid/同一 U/同一 ROI）----
        T, tinfo, tart = FZ.truth_occupancy(state_dir, proto)
        # 真值必须与融合同一栅格：dims/pitch/origin 全一致才比较
        if tuple(int(x) for x in tart['grid']['dims']) != tuple(int(x) for x in grid['dims']):
            tr['truth_hidden'] = {'status': 'grid_mismatch',
                                  'truth_dims': [int(x) for x in tart['grid']['dims']],
                                  'fusion_dims': [int(x) for x in grid['dims']]}
        elif T is not None:
            roi = _roi_mask(grid, proto, U)
            T_h = T & roi
            P_h = gen_U & roi
            inter = int((T_h & P_h).sum())
            missing = int((T_h & ~P_h).sum())
            over = int((P_h & ~T_h).sum())
            iou = inter / max(1, int((T_h | P_h).sum()))
            tr['truth_hidden'] = {
                'roi': 'x∈[obstacle_x, obstacle_x+hidden_extent], |y|<=corridor_half, 且 U',
                'T_hidden': int(T_h.sum()), 'P_hidden': int(P_h.sum()),
                'intersection': inter, 'missing': missing, 'overfill': over,
                'missing_rate': round(missing / max(1, int(T_h.sum())), 5),
                'overfill_rate': round(over / max(1, int(P_h.sum())), 5),
                'iou': round(iou, 5)}
        else:
            tr['truth_hidden'] = {'status': 'truth_occ_missing'}
    return tr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--candidate', nargs='*', default=None)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    sd = (ROOT / a.state) if not pathlib.Path(a.state).is_absolute() else pathlib.Path(a.state)
    out_dir = sd / 'vtrace'
    out_dir.mkdir(parents=True, exist_ok=True)
    cids = a.candidate or [p.name for p in sorted((sd / 'candidates').glob('*'))
                           if (p / 'candidate.json').is_file()]
    rows = []
    for cid in cids:
        try:
            tr = trace_candidate(sd, proto, cid)
        except Exception as e:  # noqa: BLE001
            tr = {'schema': 'v3-v0trace/v1', 'state_id': sd.name, 'candidate': cid,
                  'error': f'{type(e).__name__}: {e}'}
        (out_dir / f'{cid}.json').write_text(json.dumps(tr, ensure_ascii=False, indent=2))
        s3 = tr.get('S3_classification') or {}
        th = tr.get('truth_hidden') or {}
        rows.append({'candidate': cid,
                     'P': s3.get('P'), 'P_U': s3.get('P_and_U'),
                     'n_v': (tr.get('S4_fusion') or {}).get('n_v'),
                     'full_minus_v_ok': (tr.get('S4_fusion') or {}).get(
                         'full_minus_v_equals_p_and_u'),
                     'missing_rate': th.get('missing_rate'), 'iou': th.get('iou'),
                     'err': tr.get('error')})
    (out_dir / 'index.json').write_text(json.dumps(
        {'schema': 'v3-v0trace-index/v1', 'state_id': sd.name, 'rows': rows},
        ensure_ascii=False, indent=2))
    print(json.dumps({'state': sd.name, 'n': len(rows),
                      'rows': [{k: r[k] for k in ('candidate', 'P', 'P_U', 'missing_rate',
                                                  'iou', 'err')} for r in rows]},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
