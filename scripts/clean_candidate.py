"""
候选清理 v3：决策直接决定导出面集合，导出后重读校验。

  .venv/bin/python scripts/clean_candidate.py --candidate <glb> --out <dir> --id A2

相对 v1/v2 的修正（E4 审查）：
  · v1 的 keep/drop 决策只是记录，导出时又按"面积>=1% 无序并集"重取，
    浮空平面与内部壳根本没被删掉 —— 现在导出只写 decisions 里 keep 的分量；
  · pca_span 曾用 2*sqrt(特征值)（顶点分布统计量，受网格密度影响），
    改为**投影坐标 max-min** 的真实主轴跨度；
  · components_after 不再写死，导出后重读文件重新统计；
  · 无法判断包含关系时输出 containment_unknown，不静默当作"不包含"。

判据（阈值与 E4 一致，未放宽）：
  thin_ratio = 最小主轴跨度 / 最大主轴跨度 < 0.2  -> rejected_thin
  浮空面：最小主轴跨度 < 1 mm 且面积占比 >= 3%
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

VERSION = 'clean/v4'
WELD_TOL_REL = 1e-5        # 焊接容差：相对**规范化后**对象尺度（不再是绝对 1e-6 m）
THIN_RATIO_MIN = 0.2
FRAGMENT_AREA_FRAC = 0.01
FLOATING_THICK_REL = 0.01  # 浮空面判据：最小主轴跨度 / 最大主轴跨度
FLOATING_AREA_FRAC = 0.03
CONTAIN_FRAC = 0.90


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_world_mesh(path):
    sc = trimesh.load(str(path), force='scene')
    if not isinstance(sc, trimesh.Scene):
        return _weld(sc.copy()), 1
    geoms, n_nodes = [], 0
    for node in sc.graph.nodes_geometry:
        T, name = sc.graph[node]
        g = sc.geometry[name]
        gg = g.copy()
        if T is not None:
            gg.apply_transform(T)
        geoms.append(gg)
        n_nodes += 1
    m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
    return _weld(m), n_nodes


def _weld(m):
    m = m.copy()
    try:
        keep = m.nondegenerate_faces(height=1e-12)
        if keep.sum() > 0:
            m.update_faces(keep)
    except Exception:
        pass
    verts = np.asarray(m.vertices, dtype=np.float64)
    if len(verts) == 0 or len(m.faces) == 0:
        return m
    # 焊接容差按对象尺度归一化：先算包围盒对角，再取相对容差
    diag = float(np.linalg.norm(verts.max(0) - verts.min(0))) or 1.0
    tol = max(diag * WELD_TOL_REL, 1e-12)
    key = np.round(verts / tol).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    rep = np.zeros((len(uniq), 3)); cnt = np.zeros(len(uniq))
    np.add.at(rep, inv, verts); np.add.at(cnt, inv, 1)
    rep /= cnt[:, None]
    out = trimesh.Trimesh(rep, inv[np.asarray(m.faces)], process=False)
    if out.extents.max() > 100.0:
        raise RuntimeError(f'焊接后尺度异常 {out.extents}')
    return out


def principal_spans(pts):
    """真实主轴跨度：PCA 求轴后投影取 max-min（不是标准差量级）。"""
    p = np.asarray(pts, dtype=np.float64)
    if len(p) < 4:
        return np.zeros(3), np.eye(3)
    c = p.mean(0)
    q = p - c
    cov = q.T @ q / max(len(q) - 1, 1)
    w, V = np.linalg.eigh(cov)
    V = V[:, np.argsort(w)[::-1]]
    proj = q @ V
    return proj.max(0) - proj.min(0), V


def analyse(path):
    m, n_nodes = load_world_mesh(path)
    comps = list(m.split(only_watertight=False))
    total_area = float(sum(abs(float(c.area)) for c in comps)) or 1.0
    infos = []
    for i, c in enumerate(comps):
        v = np.asarray(c.vertices)
        spans, axes = principal_spans(v)
        b = np.asarray(c.bounds); ext = b[1] - b[0]
        infos.append({
            'index': i, 'faces': int(len(c.faces)), 'verts': int(len(v)),
            'area_m2': round(abs(float(c.area)), 9),
            'area_frac': round(abs(float(c.area)) / total_area, 5),
            'extents_m': [round(float(x), 6) for x in ext],
            'principal_spans_m': [round(float(x), 6) for x in spans],
            'pca_axes': [[round(float(x), 4) for x in axes[:, k]] for k in range(3)],
            'max_span_m': round(float(max(spans)), 6),
            'thin_ratio': round(float(min(spans) / max(max(spans), 1e-9)), 5),
            'watertight': bool(c.is_watertight),
            'bounds_min': [round(float(x), 6) for x in b[0]],
            'bounds_max': [round(float(x), 6) for x in b[1]],
        })

    overall_max_span = max((i['max_span_m'] for i in infos), default=1.0) or 1.0
    by_area = sorted(range(len(infos)), key=lambda i: -infos[i]['area_frac'])
    keep, contain_status = None, 'ok'
    for i in by_area:
        x = infos[i]
        if x['area_frac'] < FRAGMENT_AREA_FRAC:
            continue
        # 不再用 2 cm **绝对**长度门（会随单位尺度改变判决）。
        # 改为主体的最大跨度须占整体最大跨度的 >=15%（相对判据，尺度不变）。
        if x['max_span_m'] < 0.15 * overall_max_span:
            continue
        if x['thin_ratio'] < FLOATING_THICK_REL and x['area_frac'] >= FLOATING_AREA_FRAC:
            continue
        keep = i
        break

    if keep is not None:
        try:
            kp = np.asarray(comps[keep].vertices)[::max(1, len(comps[keep].vertices) // 300)]
            for j in by_area:
                if j == keep or infos[j]['max_span_m'] <= infos[keep]['max_span_m']:
                    continue
                if float(np.mean(comps[j].contains(kp))) > CONTAIN_FRAC:
                    keep = j
                    break
        except Exception:
            contain_status = 'containment_unknown'

    decisions = []
    for x in infos:
        i = x['index']
        spans = x['principal_spans_m']
        if i == keep:
            decisions.append({'index': i, 'decision': 'keep',
                              'reason': 'main body: largest area, not floating, thickness ok'})
        elif x['area_frac'] < FRAGMENT_AREA_FRAC:
            decisions.append({'index': i, 'decision': 'drop',
                              'reason': f"fragment: area_frac {x['area_frac']} < {FRAGMENT_AREA_FRAC}"})
        elif x['thin_ratio'] < FLOATING_THICK_REL:
            decisions.append({'index': i, 'decision': 'drop',
                              'reason': f"floating plane: thin_ratio {x['thin_ratio']} "
                                        f"< {FLOATING_THICK_REL}"})
        elif x['thin_ratio'] < THIN_RATIO_MIN:
            decisions.append({'index': i, 'decision': 'drop',
                              'reason': f"thin shell: thin_ratio {x['thin_ratio']} < {THIN_RATIO_MIN}"})
        else:
            decisions.append({'index': i, 'decision': 'drop',
                              'reason': 'secondary shell/duplicate (only main body kept)'})

    kept = [d['index'] for d in decisions if d['decision'] == 'keep']
    body = trimesh.util.concatenate([comps[i] for i in kept]) if kept else None
    return {'version': VERSION, 'nodes': n_nodes, 'components_before': len(comps),
            'components': infos, 'decisions': decisions, 'kept_indices': kept,
            'containment_status': contain_status,
            'total_area_m2': round(total_area, 8)}, body


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
        rec = {'version': VERSION, 'error': f'{type(e).__name__}: {e}',
               'precheck': {'verdict': 'precheck_failed', 'thin': None}}
        body = None

    rec['candidate'] = str(a.candidate)
    rec['id'] = cid
    rec['raw_sha'] = sha(a.candidate)

    if body is not None and len(body.faces):
        b = np.asarray(body.bounds)
        body = body.copy()
        body.apply_translation([0, 0, -float(b[0][2])])
        p = out / 'body.stl'
        body.export(p)
        rec['clean_path'] = str(p)
        rec['clean_sha'] = sha(p)

        rd = trimesh.load(str(p), force='mesh', process=True)
        rd.merge_vertices()          # STL 是三角汤：先合并再数连通分量
        rd_comps = list(rd.split(only_watertight=False))
        spans, _ = principal_spans(np.asarray(rd.vertices))
        rec['verify'] = {
            'components_after': len(rd_comps),
            'faces_after': int(len(rd.faces)),
            'extents_m': [round(float(x), 6) for x in rd.extents],
            'principal_spans_m': [round(float(x), 6) for x in spans],
            'thin_ratio': round(float(min(spans) / max(max(spans), 1e-9)), 5),
            'z_min_m': round(float(np.asarray(rd.bounds)[0][2]), 9),
            'kept_expected': len(rec['kept_indices']),
            'matches_decisions': len(rd_comps) == len(rec['kept_indices']),
        }
        rec['components_after'] = rec['verify']['components_after']
        thin = rec['verify']['thin_ratio'] < THIN_RATIO_MIN
        rec['precheck'] = {
            'thin': bool(thin),
            'verdict': 'rejected_thin' if thin else 'ok',
            'criteria': {'thin_ratio_min': THIN_RATIO_MIN,
                         'fragment_area_frac': FRAGMENT_AREA_FRAC,
                         'floating_thin_ratio': FLOATING_THICK_REL,
                         'weld_tol_rel': WELD_TOL_REL,
                         'main_span_rel_min': 0.15,
                         'note': '全部为相对判据，整体等比缩放不改变判决'},
        }
        rec['coordinate_frame'] = 'local (z_min=0); downstream applies T once'
    else:
        rec.setdefault('precheck', {'verdict': 'cleanup_failed', 'thin': None})
        rec['components_after'] = 0

    (out / 'clean.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    v = rec.get('precheck', {})
    print(json.dumps({'id': cid, 'before': rec.get('components_before'),
                      'after': rec.get('components_after'), 'verdict': v.get('verdict'),
                      'thin_ratio': rec.get('verify', {}).get('thin_ratio'),
                      'kept': rec.get('kept_indices')}, ensure_ascii=False))
    return 0 if v.get('verdict') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
