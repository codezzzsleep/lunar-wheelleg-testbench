"""Stage008：对六个 GLB 应用节点变换后走已验配准入口，输出世界坐标父网格。"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_register  # noqa: E402


def asset_mesh(glb):
    sc = trimesh.load(str(glb), force='scene')
    parts = []
    for name, geom in sc.geometry.items():
        if not len(geom.faces):
            continue
        T, _ = sc.graph.get(name)
        g = geom.copy(); g.apply_transform(T)
        parts.append(g)
    return trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default='runs/v3/stage008/truth_v2')
    ap.add_argument('--out', default='runs/v3/stage008/registered')
    ap.add_argument('--only', default=None)
    ap.add_argument('--run-id', default=None)
    a = ap.parse_args()
    state = (ROOT / a.state).resolve(); out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    proto_path = ROOT / 'plans/v3_protocol.json'
    proto = json.loads(proto_path.read_text())
    run_id = a.run_id or time.strftime('reg-%Y%m%dT%H%M%S')
    res = {'schema': 'stage8-registration/v2', 'state': a.state, 'run_id': run_id,
           'code_commit': __import__('subprocess').check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
           'protocol_sha256': hashlib.sha256(proto_path.read_bytes()).hexdigest(),
           'script_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
           'observation_path': str(state / 'observation'),
           'observation_sha256': (json.loads((state / 'truth_manifest.json').read_text()).get('observation_sha256')
                                  if (state / 'truth_manifest.json').exists() else None),
           'generated_denominator': 6, 'diagnostic_assets': [], 'candidates': {}}
    for tf in sorted((ROOT / 'runs/v3/stage007/lux3d/generation').glob('task_*.json')):
        td = json.loads(tf.read_text()); tid = str(td['task_id'])
        if a.only and tid != a.only:
            continue
        glbs = sorted((tf.parent / f'task_{tid}').rglob('*.glb'),
                      key=lambda x: x.stat().st_size, reverse=True)
        if not glbs:
            res['candidates'][tid] = {'error': 'no glb'}; continue
        d = out / f'task_{tid}'; d.mkdir(parents=True, exist_ok=True)
        source_sha = v3_register.sha256_file(glbs[0])
        asset = asset_mesh(glbs[0]); asset.export(d / 'asset.stl')
        rec = v3_register.register(str(d / 'asset.stl'), str(state / 'observation'), proto, d)
        M = np.asarray(rec['M'], dtype=float)
        w = asset.copy(); w.apply_transform(M); w.export(d / 'world.stl')
        res['candidates'][tid] = {'M': M.tolist(), 'scale': float(rec['best']['diagnostics'].get('scale', 0)),
                                  'source_glb': str(glbs[0]), 'source_glb_sha256': source_sha,
                                  'asset_sha256': v3_register.sha256_file(d / 'asset.stl'),
                                  'world_sha256': v3_register.sha256_file(d / 'world.stl'),
                                  'diagnostics': rec['best']['diagnostics']}
        (out / 'registration.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print(json.dumps({'task': tid, 'scale': res['candidates'][tid]['scale'],
                          'diag': rec['best']['diagnostics']}, ensure_ascii=False)[:400])
    res['registration_evaluated_denominator'] = len(res['candidates'])
    res['manifest_sha256'] = hashlib.sha256(json.dumps(res, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    (out / 'registration.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
