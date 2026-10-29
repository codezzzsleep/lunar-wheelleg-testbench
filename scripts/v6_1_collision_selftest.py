"""
V6.1 工作包 C1：碰撞保真评价器的已知答案自检。

对三个已知实体（闭合立方体、带凹槽块、带可通行缝隙块）分别测：
  · 源 vs 自身（参考正确）；
  · 源 vs 正确分块（box 并集）；
  · 源 vs 故意填平凹槽的凸包；
  · 源 vs 错位碰撞体。
要求：正确表示通过，填凹/错位被检出。全部走正式度量函数。

  .venv/bin/python scripts/v6_1_collision_selftest.py --out runs/.../collision/selftest
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import collision_box_union as BU
import collision_occupancy_metrics as CM

ROOT = pathlib.Path(__file__).resolve().parent.parent


def cube(size=(0.20, 0.20, 0.20)):
    m = trimesh.creation.box(extents=size)
    m.apply_translation([0, 0, size[2] / 2])
    return m


def grooved():
    """上方开一条 40 mm 宽、深 60 mm 的槽（沿 y 贯通）。"""
    base = cube((0.20, 0.20, 0.20))
    cut = trimesh.creation.box(extents=(0.04, 0.24, 0.06))
    cut.apply_translation([0, 0, 0.20 - 0.03])   # 槽从 z=0.14 切到顶面 0.20
    return BU_diff(base, cut)


def channel():
    """沿 x 贯通、40 mm 高、60 mm 宽的通道（可通行缝隙）。"""
    base = cube((0.20, 0.20, 0.20))
    cut = trimesh.creation.box(extents=(0.24, 0.06, 0.04))
    cut.apply_translation([0, 0, 0.05])
    return BU_diff(base, cut)


def BU_diff(a, b):
    import manifold3d as m3
    A = m3.Manifold(m3.Mesh(np.asarray(a.vertices, dtype=np.float32),
                            np.asarray(a.faces, dtype=np.uint32)))
    B = m3.Manifold(m3.Mesh(np.asarray(b.vertices, dtype=np.float32),
                            np.asarray(b.faces, dtype=np.uint32)))
    mm = (A - B).to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3],
                           np.asarray(mm.tri_verts), process=True)


def eval_pair(src, rep_dir, pitch=0.004, label=''):
    """直接复用正式度量（与 CLI 同一函数路径）。"""
    import subprocess
    out = rep_dir.parent / f'{rep_dir.name}_metrics.json'
    cmd = [sys.executable, str(ROOT / 'scripts/collision_occupancy_metrics.py'),
           '--mesh', str(src), '--collision', str(rep_dir), '--out', str(out),
           '--label', label, '--eval-pitch', str(pitch), '--samples', '800']
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f'metrics 失败 {label}: {r.stderr[-400:]}')
    return json.loads(out.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/unseen/delivery_v6_1/v6_1_20261029/collision/selftest')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, fn in (('cube', cube), ('groove', grooved), ('channel', channel)):
        d = out / name; d.mkdir(parents=True, exist_ok=True)
        src = d / 'source.stl'
        m = fn(); m.export(src)
        # 1) 自身
        self_dir = d / 'self'; self_dir.mkdir(exist_ok=True)
        m.export(self_dir / 'body.stl')
        (self_dir / 'manifest.json').write_text(json.dumps(
            {'parts': ['body.stl'], 'coordinate_frame': 'world',
             'world_sha': CM.sha_file(self_dir / 'body.stl')}))
        # 2) 正确分块（box 并集）
        box_dir = d / 'box'
        BU.main.__globals__  # noqa
        import subprocess
        subprocess.run([sys.executable, str(ROOT / 'scripts/collision_box_union.py'),
                        '--mesh', str(src), '--out', str(box_dir),
                        '--pitch', '0.004', '--hypothesis-id', f'{name}_box'],
                       check=True, capture_output=True, text=True)
        # 3) 填平凹槽的凸包
        import manifold3d as _m3
        _h = _m3.Manifold.hull_points(np.asarray(m.vertices, dtype=np.float32)).to_mesh()
        hull = trimesh.Trimesh(np.asarray(_h.vert_properties)[:, :3],
                               np.asarray(_h.tri_verts), process=True)
        hull_dir = d / 'hull'; hull_dir.mkdir(exist_ok=True)
        hull.export(hull_dir / 'body.stl')
        (hull_dir / 'manifest.json').write_text(json.dumps(
            {'parts': ['body.stl'], 'coordinate_frame': 'world',
             'world_sha': CM.sha_file(hull_dir / 'body.stl')}))
        # 4) 错位碰撞体
        off = m.copy(); off.apply_translation([0.012, 0.0, 0.0])
        off_dir = d / 'offset'; off_dir.mkdir(exist_ok=True)
        off.export(off_dir / 'body.stl')
        (off_dir / 'manifest.json').write_text(json.dumps(
            {'parts': ['body.stl'], 'coordinate_frame': 'world',
             'world_sha': CM.sha_file(off_dir / 'body.stl')}))
        got = {}
        for tag, rep in (('self', self_dir), ('box', box_dir), ('hull', hull_dir),
                         ('offset', off_dir)):
            got[tag] = eval_pair(src, rep, 0.004, f'{name}_{tag}')
        ok_self = got['self']['verdict'] == 'PASS'
        ok_box = got['box']['verdict'] == 'PASS'
        det_hull = (got['hull']['verdict'] != 'PASS') if name != 'cube' else True
        det_off = got['offset']['verdict'] != 'PASS'
        rows.append({'case': name, 'self': got['self'], 'box': got['box'],
                     'hull': got['hull'], 'offset': got['offset'],
                     'checks': {'self_pass': ok_self, 'box_pass': ok_box,
                                'hull_detected': det_hull, 'offset_detected': det_off},
                     'note': ('cube: hull == self, so hull-detection is N/A' if name == 'cube' else ''),
                     'status': ('PASS' if all((ok_self, ok_box, det_hull, det_off)) else 'FAIL')})
        print(name, rows[-1]['status'], 'self', got['self']['verdict'],
              'box', got['box']['verdict'], 'hull', got['hull']['verdict'],
              'offset', got['offset']['verdict'])
    rep = {'schema': 'collision-selftest/v6_1', 'rows': rows,
           'n': len(rows), 'n_pass': sum(1 for r in rows if r['status'] == 'PASS')}
    (out / 'selftest.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'n_pass': rep['n_pass'], 'n': rep['n']}, ensure_ascii=False))
    return 0 if rep['n_pass'] == rep['n'] else 1


if __name__ == '__main__':
    sys.exit(main())
