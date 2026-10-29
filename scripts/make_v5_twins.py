"""
V5 P2 双胞胎案例：同正面、不同背面，生成 case + observation。

  MUJOCO_GL=osmesa .venv/bin/python scripts/make_v5_twins.py \
      --out runs/unseen/delivery_v5/v5_20261029/cases/twins

  · 正面只依赖 (H,W,D,seed)，与背面无关；背面 drop/ramp_s/ramp_l/ledge/cleft；
  · 每个 case 保存 mesh、case JSON、observation 包、registry 条目；
  · 只做免费真值/观测，不触发生成 API。
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import twins

ROOT = pathlib.Path(__file__).resolve().parent.parent

FRONTS = {
    'narrow': {'H': 0.3342, 'W': 0.1600, 'D': 0.3111, 'seed': 6606},
    'wide':   {'H': 0.2000, 'W': 0.2400, 'D': 0.2500, 'seed': 7707},
}


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--backs', default='drop,ramp_s,ramp_l,ledge,cleft')
    ap.add_argument('--fronts', default='narrow,wide')
    ap.add_argument('--obstacle-x', type=float, default=1.8)
    ap.add_argument('--goal-x', type=float, default=2.6)
    a = ap.parse_args()

    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    mdir = out / 'mesh'; mdir.mkdir(exist_ok=True)
    cdir = ROOT / 'cases/unseen_v1'; cdir.mkdir(parents=True, exist_ok=True)
    odir = out / 'observations'; odir.mkdir(exist_ok=True)
    rows = []
    for fname in a.fronts.split(','):
        f = FRONTS[fname]
        for kind in a.backs.split(','):
            cid = f'v5twin_{fname}_{kind}'
            m, Lb = twins.twin_solid(kind, f['H'], f['W'], f['D'], seed=f['seed'])
            nm = twins.non_manifold_edges(m)
            mp = mdir / f'{cid}.stl'; m.export(mp)
            b = np.asarray(m.bounds); ext = b[1] - b[0]
            case = {
                'case_id': cid, 'seed': f['seed'],
                'mesh': str(mp), 'H': float(ext[2]), 'W': float(ext[1]),
                'D': float(ext[0]), 'goal_x': a.goal_x, 'channel_half': 1.2,
                'obstacle_x': float(a.obstacle_x), 'yaw_deg': 0.0,
                'source': 'twins.twin_solid', 'front': fname, 'back': kind,
                'front_params': f, 'L_back': round(float(Lb), 4),
                'watertight': bool(m.is_watertight),
                'non_manifold_edges': int(nm),
                'note': '同正面不同背面的程序化双胞胎；开发诊断用，不是 Lux3D 产物'}
            cp = cdir / f'{cid}.json'
            cp.write_text(json.dumps(case, ensure_ascii=False, indent=2) + '\n')
            obs = odir / cid
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/observe.py'),
                                '--case', str(cp), '--out', str(obs),
                                '--observation-id', cid],
                               capture_output=True, text=True, cwd=str(ROOT))
            if r.returncode != 0:
                raise SystemExit(f'observe {cid} 失败: {r.stderr[-400:]}')
            om = json.loads((obs / 'observation_manifest.json').read_text())
            rows.append({'case_id': cid, 'front': fname, 'back': kind,
                         'case': str(cp.relative_to(ROOT)), 'mesh': str(mp),
                         'mesh_sha256': sha(mp), 'observation_dir': str(obs),
                         'observation_id': cid, 'observation_sha': om['observation_sha'],
                         'visible': json.loads((obs / 'observation.json').read_text())['visible'],
                         'watertight': bool(m.is_watertight),
                         'non_manifold_edges': int(nm),
                         'L_back': round(float(Lb), 4),
                         'extents': [round(float(x), 6) for x in ext]})
            print(cid, 'w=', round(float(ext[1]), 4), 'watertight=', m.is_watertight,
                  'nm=', nm)
    (out / 'twins_registry.json').write_text(json.dumps({
        'schema': 'v5-twins/v1', 'rows': rows,
        'note': ('正面相同、背面不同；同一 front 的不同 back 不当作独立石头，'
                 '但完整几何不同，可用于检验隐藏背面是否改变动作后果')},
        ensure_ascii=False, indent=2))
    print('rows', len(rows), '->', out / 'twins_registry.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
