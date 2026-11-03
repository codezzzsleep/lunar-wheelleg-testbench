"""V0 单候选定位：GLB 节点变换 → 配准 → STL 重载 → 占据，逐段对比。

  python scripts/v3_v0_probe.py --state runs/v3/states/<sid> --candidate A1

不做任何"体素器没问题"的推断：真值网格与候选网格来源不同，真值对只能验收入口，
不能证明候选路径正确。这里把每段的几何量并列，定位差异发生在哪一段。
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
    return json.loads(p.read_text()) if p.is_file() else d


def stats(mesh):
    import trimesh
    comps = mesh.split(only_watertight=False)
    return {'n_vertices': int(len(mesh.vertices)), 'n_faces': int(len(mesh.faces)),
            'extents': [round(float(x), 6) for x in mesh.extents],
            'aabb_volume': round(float(np.prod(mesh.extents)), 6),
            'area': round(float(mesh.area), 6),
            'signed_volume': round(float(abs(mesh.volume)), 6) if len(mesh.faces) else None,
            'is_watertight': bool(mesh.is_watertight),
            'n_components': int(len(comps))}


def scene_nodes(path):
    import trimesh
    sc = trimesh.load(path, force='scene', process=False)
    nodes = []
    for name, g in sc.geometry.items():
        T, R = np.eye(4), None
        try:
            T = sc.graph.get(name)[0]
        except Exception:  # noqa: BLE001
            pass
        nodes.append({'name': str(name), 'n_faces': int(len(g.faces)),
                      'extents': [round(float(x), 6) for x in g.extents],
                      'node_matrix': [[round(float(v), 6) for v in row] for row in T]})
    return sc, nodes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--candidate', default='A1')
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    sd = ROOT / a.state
    cid = a.candidate
    out = sd / 'candidates' / cid
    cand = jl(out / 'candidate.json', {}) or {}
    ident = cand.get('identity')
    if isinstance(ident, dict):
        ident = ident.get('identity') or ident.get('id')
    cache = sd.parent.parent / 'generation' / 'cache' / str(ident) / 'model.glb'
    rep = {'schema': 'v3-v0-probe/v1', 'state_id': sd.name, 'candidate': cid,
           'task_id': cand.get('task_id'), 'identity': ident,
           'raw_sha256': cand.get('raw_sha'),
           'parent_sha256_in_candidate': cand.get('parent_sha'),
           'registration_matrix': cand.get('registration_matrix'),
           'registration_diagnostics': cand.get('registration_diagnostics')}
    import trimesh
    if cache.is_file():
        rep['raw_glb'] = {'path': str(cache.relative_to(ROOT)),
                          'sha256': FZ.sha256_file(cache),
                          'sha_matches_candidate_raw': (cand.get('raw_sha') ==
                                                        FZ.sha256_file(cache))}
        sc, nodes = scene_nodes(cache)
        rep['raw_glb']['n_nodes'] = len(nodes)
        rep['raw_glb']['nodes'] = nodes[:8]
        m_scene = sc.to_geometry() if hasattr(sc, 'to_geometry') else sc.dump(concatenate=True)
        rep['raw_glb']['as_scene'] = stats(m_scene)
        m_force = trimesh.load(cache, force='mesh', process=False)
        rep['raw_glb']['as_force_mesh'] = stats(m_force)
        rep['raw_glb']['scene_vs_force_extent_ratio'] = [
            round(float(b) / float(x), 6) if x else None
            for x, b in zip(m_force.extents, m_scene.extents)]
    else:
        rep['raw_glb'] = {'status': 'missing', 'path': str(cache)}
    pw = out / 'parent_world' / 'body.stl'
    if pw.is_file():
        m_pw = trimesh.load(pw, force='mesh', process=False)
        rep['parent_world'] = {'sha256': FZ.sha256_file(pw), **stats(m_pw)}
        if 'as_force_mesh' in rep['raw_glb']:
            fr = rep['raw_glb']['as_force_mesh']
            rep['parent_world']['vs_raw_extent_ratio'] = [
                round(float(b) / float(x), 6) for x, b in zip(fr['extents'],
                                                              rep['parent_world']['extents'])]
            rep['parent_world']['vs_raw_area_ratio'] = round(
                rep['parent_world']['area'] / max(1e-9, fr['area']), 6)
            rep['parent_world']['vs_raw_volume_ratio'] = (
                round(rep['parent_world']['signed_volume'] / fr['signed_volume'], 6)
                if fr.get('signed_volume') else None)
        art = FZ.load_v_artifact(sd / 'fusion')
        g = art['grid']
        occ_pw, info = FZ.voxelize_columns(m_pw, g)
        rep['occupancy_parent_world'] = {
            'n_voxels': int(occ_pw.sum()), 'sha256': FZ.arr_sha(occ_pw),
            'volume_m3': round(float(occ_pw.sum()) * float(g['pitch']) ** 3, 6),
            'pitch_m': float(g['pitch']), 'dims': [int(x) for x in g['dims']]}
        if 'as_force_mesh' in rep['raw_glb']:
            try:
                occ_raw, _ = FZ.voxelize_columns(m_force, g)
                rep['occupancy_raw_unregistered'] = {'n_voxels': int(occ_raw.sum()),
                                                     'note': '未配准，仅用于对照'}
            except Exception as e:  # noqa: BLE001
                rep['occupancy_raw_unregistered'] = {'error': f'{type(e).__name__}: {e}'[:160]}
    else:
        rep['parent_world'] = {'status': 'missing'}
    # 配准矩阵的尺度（det 的立方根；1.0 表示纯刚体）
    M = rep.get('registration_matrix')
    if M:
        A = np.asarray(M, float)
        if A.shape == (4, 4):
            rep['registration_scale_from_matrix'] = round(float(np.cbrt(np.linalg.det(A[:3, :3]))), 6)
    p = out / 'v0_probe.json'
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'out': str(p.relative_to(ROOT)),
                      'raw': {k: rep['raw_glb'].get(k) for k in
                              ('status', 'n_nodes', 'sha_matches_candidate_raw')},
                      'raw_force': rep['raw_glb'].get('as_force_mesh'),
                      'raw_scene': rep['raw_glb'].get('as_scene'),
                      'parent': {k: rep.get('parent_world', {}).get(k) for k in
                                 ('n_faces', 'extents', 'signed_volume', 'area')},
                      'occ_parent': rep.get('occupancy_parent_world', {}).get('n_voxels'),
                      'det_scale': rep.get('registration_scale_from_matrix')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
