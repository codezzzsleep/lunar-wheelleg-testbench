"""Stage008：应用 GLB 节点变换后，复用 v3_fuse 的 FULL= V|(P&U) / OBS=V。"""
import argparse
import json
import pathlib
import sys

import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_fuse  # noqa: E402
import stage7_candidates as S7  # noqa: E402


def load_glb_world(glb):
    sc = trimesh.load(str(glb), force='scene')
    parts = []
    for name, geom in sc.geometry.items():
        if not len(geom.faces):
            continue
        T, _ = sc.graph.get(name)           # 显式应用节点变换（不依赖 rtree）
        g = geom.copy(); g.apply_transform(T)
        parts.append(g)
    m = trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0].copy()
    return S7.orient(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default='runs/v3/stage008/state_layout2')
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--out', default='runs/v3/stage008/fusion')
    a = ap.parse_args()
    state = (ROOT / a.state).resolve(); out = (ROOT / a.out).resolve()
    proto = json.loads((ROOT / a.protocol).read_text())
    art = v3_fuse.write_v_artifact(state, proto)
    out.mkdir(parents=True, exist_ok=True)
    res = {'schema': 'stage8-fusion/v1', 'state': a.state, 'v_sha': art['v_sha'],
           'v_stats': art['stats'], 'parents': {}}
    ref = state / 'truth' / 'body_world.stl'
    m = trimesh.load(str(ref), force='mesh', process=False)
    man, stats = v3_fuse.fuse_parent(art, m, out / 'ref', {'id': 'reference_truth',
                                                           'mesh_sha256': v3_fuse.sha256_file(ref)},
                                     proto)
    res['parents']['reference'] = {'id': 'reference_truth', 'stats': stats,
                                   'full_sha': man['full_occ_sha'], 'obs_sha': man['obs_only_occ_sha']}
    for tf in sorted((ROOT / 'runs/v3/stage007/lux3d/generation').glob('task_*.json')):
        td = json.loads(tf.read_text()); tid = td['task_id']
        glbs = sorted((tf.parent / f'task_{tid}').rglob('*.glb'),
                      key=lambda x: x.stat().st_size, reverse=True)
        if not glbs:
            res['parents'][str(tid)] = {'error': 'no_glb'}; continue
        mesh = load_glb_world(glbs[0])
        mp = out / f'task_{tid}' / 'parent_world.stl'
        mp.parent.mkdir(parents=True, exist_ok=True); mesh.export(mp)
        man, stats = v3_fuse.fuse_parent(art, mesh, out / f'task_{tid}',
                                         {'id': f'lux_{tid}',
                                          'mesh_sha256': v3_fuse.sha256_file(mp)}, proto)
        res['parents'][str(tid)] = {'id': f'lux_{tid}', 'stats': stats,
                                    'full_sha': man['full_occ_sha'], 'obs_sha': man['obs_only_occ_sha'],
                                    'glb_sha': td.get('glb_sha')}
    (out / 'fusion_summary.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'v': art['v_sha'][:12], 'parents': {
        k: {kk: v[kk] for kk in ('full_sha', 'stats')} if 'stats' in v else v
        for k, v in res['parents'].items()}}, ensure_ascii=False)[:1200])
    return 0


if __name__ == '__main__':
    sys.exit(main())
