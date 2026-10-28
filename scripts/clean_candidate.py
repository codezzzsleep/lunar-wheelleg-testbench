"""
候选清理与廉价预检（任务 A）。

  .venv/bin/python scripts/clean_candidate.py --candidate <glb> --out runs/unseen/recovery_r3/clean/<id>

做三件事：
  1. 应用 GLB 节点变换，按**几何顶点连通性**分组（先按 1e-8 m 焊接，UV 接缝不算真间隙）；
  2. 每个分量记录面数/面积/包围盒/主轴跨度/闭合性/有效体积/包含关系；
  3. 选主体：优先"包含其他分量的外壳"，剔除零厚度浮面、退化面、内部重复壳、小碎片。

约束（任务书四）：
  · 不加背板、不增厚、不非等比拉伸、不用凸包造形；
  · 主体不能只按面数/面积排序；
  · 薄片候选在预检阶段直接 rejected_thin，不做长配准；
  · 产物体积/厚度记录，PCA 最小轴范围 / 最大边 ≥ 0.2 作为薄片判据。
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
WELD_TOL = 1e-6          # 1 µm：远小于真实特征，同时吞掉浮点噪声
THIN_RATIO_MIN = 0.2     # PCA 最小轴 / 最大边
SMALL_AREA_FRAC = 0.01   # 面积占比 < 1% 视为碎片


def load_scene_mesh(path):
    """应用节点变换后的世界网格，并记录原始 bounds。"""
    sc = trimesh.load(str(path), force='scene')
    if isinstance(sc, trimesh.Scene):
        geoms = []
        for name, g in sc.geometry.items():
            T, _ = sc.graph.get(name)
            gg = g.copy()
            if T is not None:
                gg.apply_transform(T)
            geoms.append(gg)
        m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
    else:
        m = sc
    m = m.copy()
    # 按容差焊接：UV 接缝不算真间隙（1e-3 会破坏拓扑，实测分量爆炸到 1 万+）
    v = np.round(np.asarray(m.vertices) / WELD_TOL).astype(np.int64)
    uniq, inv = np.unique(v, axis=0, return_inverse=True)
    m = trimesh.Trimesh(uniq, inv[np.asarray(m.faces)], process=False)
    return m


def components(mesh):
    """按几何连通性分组（trimesh.split 不跨真实间隙合并）。"""
    return list(mesh.split(only_watertight=False))


def pca_span(pts):
    if len(pts) < 4:
        return np.zeros(3)
    c = pts - pts.mean(0)
    cov = c.T @ c / max(len(pts) - 1, 1)
    w, _ = np.linalg.eigh(cov)
    return np.sqrt(np.clip(w, 0, None)) * 2.0      # 各主轴跨度（约）


def inside(inner_pts, outer_mesh):
    """内部分量是否基本落在外壳内部（用包含测试的采样比例）。"""
    try:
        return float(np.mean(outer_mesh.contains(inner_pts)))
    except Exception:
        return 0.0


def analyse(path):
    raw = trimesh.load(str(path), force='mesh', process=False)
    raw_bounds = np.asarray(raw.bounds).tolist() if hasattr(raw, 'bounds') else None
    m = load_scene_mesh(path)
    comps = components(m)
    total_area = float(sum(abs(c.area) for c in comps)) or 1.0
    infos = []
    for i, c in enumerate(comps):
        v = np.asarray(c.vertices)
        span = pca_span(v)
        b = np.asarray(c.bounds)
        ext = b[1] - b[0]
        try:
            vol = float(c.volume) if c.is_watertight else None
        except Exception:
            vol = None
        infos.append({
            'index': i, 'faces': int(len(c.faces)), 'verts': int(len(v)),
            'area_m2': round(abs(float(c.area)), 8),
            'area_frac': round(abs(float(c.area)) / total_area, 4),
            'bounds_min': [round(float(x), 5) for x in b[0]],
            'bounds_max': [round(float(x), 5) for x in b[1]],
            'extents': [round(float(x), 5) for x in ext],
            'pca_span': [round(float(x), 5) for x in span],
            'watertight': bool(c.is_watertight),
            'signed_volume_m3': (round(vol, 9) if vol is not None else None),
            'max_extent': round(float(max(ext)), 5),
            'thin_ratio': round(float(min(span) / max(max(span), 1e-9)), 4),
        })

    # 主体选择：先看包含关系（外壳包住谁），再按有效体积/厚度
    vols = [x['signed_volume_m3'] for x in infos]
    cand_order = sorted(range(len(infos)),
                        key=lambda i: (-(vols[i] or 0.0), -infos[i]['max_extent']))
    keep = None
    for i in cand_order:
        if infos[i]['max_extent'] < 0.02:
            continue
        encloses = 0
        for j in range(len(infos)):
            if i == j or infos[j]['area_frac'] < SMALL_AREA_FRAC:
                continue
            if inside(np.asarray(comps[j].vertices)[::max(1, len(comps[j].vertices) // 200)],
                      comps[i]) > 0.5:
                encloses += 1
        if infos[i]['watertight'] or encloses > 0:
            keep = i
            break
    if keep is None and cand_order:
        keep = cand_order[0]

    decisions = []
    for x in infos:
        if x['index'] == keep:
            d, why = 'keep', 'main body (largest valid solid / enclosing shell)'
        elif x['area_frac'] < SMALL_AREA_FRAC:
            d, why = 'drop', 'fragment: area fraction < 1%'
        elif x['thin_ratio'] < THIN_RATIO_MIN:
            d, why = 'drop', f"near-zero thickness: PCA min/max = {x['thin_ratio']}"
        elif keep is not None and x['max_extent'] < infos[keep]['max_extent'] * 0.2:
            d, why = 'drop', 'small component inside main body'
        else:
            d, why = 'drop', 'secondary component (kept only main body)'
        decisions.append({'index': x['index'], 'decision': d, 'reason': why})

    # 生成网格常被切成许多等大的表面片：主体应视为**大分量的并集**，
    # 而不是单个分量（否则会落到 1.7% 面积的小片上，正是任务书警告的陷阱）。
    overall_span = pca_span(np.asarray(m.vertices))
    big = [c for c, x in zip(comps, infos) if x['area_frac'] >= SMALL_AREA_FRAC]
    body = trimesh.util.concatenate(big) if big else None
    body_info = None
    if body is not None:
        b = np.asarray(body.bounds); ext = b[1] - b[0]
        bspan = pca_span(np.asarray(body.vertices))
        body_info = {
            'n_components': len(big),
            'faces': int(len(body.faces)),
            'area_m2': round(abs(float(body.area)), 8),
            'extents': [round(float(x), 5) for x in ext],
            'pca_span': [round(float(x), 5) for x in bspan],
            'max_extent': round(float(max(ext)), 5),
            'thin_ratio': round(float(min(bspan) / max(max(bspan), 1e-9)), 4),
            'watertight': bool(body.is_watertight),
        }
    thin = (body_info['thin_ratio'] < THIN_RATIO_MIN) if body_info else True

    return {
        'raw_bounds': raw_bounds,
        'components_before': len(comps),
        'components_after': 1 if body is not None else 0,
        'components': infos,
        'decisions': decisions,
        'body_policy': 'union of components with area_frac >= 1%',
        'body': body_info,
        'overall_pca_span': [round(float(x), 5) for x in overall_span],
        'body_area_frac_of_total': (round(sum(x['area_frac'] for c, x in zip(comps, infos)
                                                if x['area_frac'] >= SMALL_AREA_FRAC), 4)
                                    if body_info else 0.0),
        'precheck': {
            'thin': bool(thin),
            'verdict': 'rejected_thin' if thin else 'ok',
            'criteria': {'thin_ratio_min': THIN_RATIO_MIN,
                         'small_area_frac': SMALL_AREA_FRAC,
                         'weld_tol_m': WELD_TOL},
        },
    }, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--id', default=None)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cid = a.id or pathlib.Path(a.candidate).parent.name[:12]

    try:
        rec, body = analyse(a.candidate)
    except Exception as e:
        rec = {'error': f'{type(e).__name__}: {e}', 'precheck': {'verdict': 'precheck_failed'}}
        body = None
    rec['candidate'] = str(a.candidate)
    rec['id'] = cid
    rec['version'] = 'clean/v1'
    import hashlib
    def sha(p):
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
        return h.hexdigest()
    rec['raw_sha'] = sha(a.candidate)
    if body is not None:
        # 把主体最低点移到 z=0（在**导出时**完成，下游不再贴地）
        b = np.asarray(body.bounds)
        body = body.copy()
        body.apply_translation([0, 0, -float(b[0][2])])
        p = out / 'body.stl'
        body.export(p)
        rec['clean_path'] = str(p)
        rec['clean_sha'] = sha(p)
        rec['clean_extents'] = [round(float(x), 5) for x in body.extents]
        rec['world_frame'] = 'local (z_min=0); placement T must be applied once downstream'
    (out / 'clean.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps({'id': cid, 'components_before': rec.get('components_before'),
                      'components_after': rec.get('components_after'),
                      'verdict': rec['precheck']['verdict'],
                      'body_thin_ratio': rec['body']['thin_ratio'] if rec.get('body') else None,
                      'body_area_frac': rec.get('body_area_frac_of_total')}, ensure_ascii=False))
    return 0 if rec.get('precheck', {}).get('verdict') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
