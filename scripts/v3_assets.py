"""v3 资产阶段：CC0 真实扫描岩石 -> 可上考场的岩石资产（保留 UV/贴图与来源）。

对来源池里每一块岩石：
  1. 取 glTF 的 LOD0（面数最多的那个节点，Poly Haven 同一文件里带 LOD0..LOD3）；
  2. glTF 的 Y-up -> MuJoCo 的 Z-up；保留摄影测量扫描时的自然落地朝向，不另选姿态；
  3. 等比缩放到目标高度 H（同一块石头的三档 H/r 只差一个正的等比因子）；
  4. 贴地、XY 居中；导出
       body.stl   几何（碰撞/占据用）
       body_vis.obj + texture.png  视觉（真实 UV + 真实 diffuse 贴图）
       meta.json  来源、许可、原始尺寸、缩放因子、哈希
输出：assets/v3/rocks/<rock_id>/h<idx>/...

  /opt/lunar/bin/python scripts/v3_assets.py --sources plans/v3_sources.json \
      --targets 0.6,1.0,1.4 --wheel-radius 0.086
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
R_ZUP = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])   # glTF Y-up -> Z-up


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_lod0(gltf_path):
    """返回 (mesh, texture_image)。取面数最多的节点（Poly Haven 的 LOD0）。"""
    scene = trimesh.load(gltf_path, force='scene', process=False)
    if not isinstance(scene, trimesh.Scene):
        raise SystemExit(f'不是 scene：{gltf_path}')
    best, best_faces = None, -1
    for name, g in scene.geometry.items():
        if len(g.faces) > best_faces:
            best, best_faces = g, len(g.faces)
    if best is None or best_faces <= 0:
        raise SystemExit(f'没有可用的三角面：{gltf_path}')
    mat = getattr(best.visual, 'material', None)
    tex = getattr(mat, 'baseColorTexture', None) if mat is not None else None
    if tex is None:
        tex = getattr(mat, 'image', None) if mat is not None else None
    return best.copy(), tex


def to_zup(mesh):
    m = mesh.copy()
    m.vertices = np.asarray(m.vertices, dtype=np.float64) @ R_ZUP.T
    return m


def normalize(mesh, target_h, ground_gap=0.0):
    """等比缩放到目标高度；XY 居中；最低点贴地（+ground_gap）。"""
    m = mesh.copy()
    lo, hi = m.bounds
    h = float(hi[2] - lo[2])
    if h <= 1e-9:
        raise SystemExit('网格高度为 0')
    s = float(target_h) / h
    m.apply_scale(s)
    lo, hi = m.bounds
    c = (lo + hi) / 2.0
    m.apply_translation([-c[0], -c[1], -lo[2] + float(ground_gap)])
    return m, s


def write_obj_uv(mesh, obj_path, mtl_name='rock'):
    """写带 vt/vn 的 OBJ：MuJoCo 用 mesh 的 UV 采样 XML 里绑定的 2D 贴图。"""
    V = np.asarray(mesh.vertices, dtype=np.float64)
    F = np.asarray(mesh.faces, dtype=np.int64)
    uv = getattr(mesh.visual, 'uv', None)
    has_uv = uv is not None and len(uv) == len(V)
    if has_uv:
        uv = np.asarray(uv, dtype=np.float64)
    N = np.asarray(mesh.vertex_normals, dtype=np.float64)
    lines = [f'# v3 real-scan visual mesh (uv={has_uv})']
    for v in V:
        lines.append(f'v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}')
    if has_uv:
        for t in uv:
            lines.append(f'vt {t[0]:.6f} {t[1]:.6f}')
    for n in N:
        lines.append(f'vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}')
    for f in F:
        a, b, c = f + 1
        if has_uv:
            lines.append(f'f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}')
        else:
            lines.append(f'f {a}//{a} {b}//{b} {c}//{c}')
    obj_path.write_text('\n'.join(lines) + '\n')
    return has_uv


def process_rock(rock, src_root, out_root, ratios, wheel_r):
    """单块岩石：LOD0 -> 三个高度档。返回处理记录。"""
    rec = {'schema': 'v3-rock-asset/v1', 'rock_id': rock['asset_id']}
    prov = json.loads((src_root / rock['asset_id'] / 'provenance.json').read_text())
    rec.update({'source_url': prov['source_url'], 'license': prov['license'],
                'license_url': prov['license_url'], 'authors': prov['authors'],
                'provider': prov['provider'], 'source_gltf': prov['gltf_main'],
                'source_gltf_sha256': (prov['files'].get(prov['gltf_main']) or {}).get('sha256'),
                'dimensions_mm': prov['dimensions_mm']})
    gltf = src_root / rock['asset_id'] / prov['gltf_main']
    mesh, tex = load_lod0(gltf)
    rec['n_faces_lod0'] = int(len(mesh.faces))
    rec['n_vertices_lod0'] = int(len(mesh.vertices))
    rec['has_uv'] = bool(getattr(mesh.visual, 'uv', None) is not None)
    rec['source_watertight'] = bool(mesh.is_watertight)
    m = to_zup(mesh)
    native_h = float(m.bounds[1][2] - m.bounds[0][2])
    rec['native_height_m'] = round(native_h, 6)
    rec['native_extents_m'] = [round(float(x), 6) for x in m.extents]
    rec['levels'] = []
    rock_dir = out_root / rock['asset_id']
    tex_path = rock_dir / 'texture.png'
    rock_dir.mkdir(parents=True, exist_ok=True)
    if tex is not None:
        tex.convert('RGB').save(tex_path)
        rec['texture'] = str(tex_path.relative_to(ROOT))
        rec['texture_sha256'] = sha256(tex_path)
    else:
        rec['texture'] = None
    for idx, ratio in enumerate(ratios):
        target_h = float(ratio) * float(wheel_r)
        level, scale = normalize(m, target_h)
        d = rock_dir / f'h{idx}'
        d.mkdir(parents=True, exist_ok=True)
        stl = d / 'body.stl'
        level.export(stl)
        obj = d / 'body_vis.obj'
        uv_ok = write_obj_uv(level, obj)
        lo, hi = level.bounds
        meta = {
            'schema': 'v3-rock-level/v1', 'rock_id': rock['asset_id'], 'level': idx,
            'hr_ratio': float(ratio), 'wheel_radius_m': float(wheel_r),
            'target_height_m': round(target_h, 6),
            'scale_from_native': round(float(scale), 9),
            'height_m': round(float(hi[2] - lo[2]), 6),
            'extents_m': [round(float(x), 6) for x in level.extents],
            'volume_m3': (round(float(abs(level.volume)), 9) if level.is_watertight else None),
            'watertight': bool(level.is_watertight),
            'faces': int(len(level.faces)),
            'body_stl': str(stl.relative_to(ROOT)), 'body_stl_sha256': sha256(stl),
            'vis_obj': str(obj.relative_to(ROOT)),
            'vis_obj_sha256': sha256(obj), 'obj_has_uv': bool(uv_ok),
            'texture': rec.get('texture'), 'texture_sha256': rec.get('texture_sha256'),
            'coordinate_frame': 'z_up_grounded_centered',
            'note': '等比缩放；未改朝向；贴地 z=0；XY 居中',
        }
        (d / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        rec['levels'].append(meta)
    (rock_dir / 'rock.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sources', default='plans/v3_sources.json')
    ap.add_argument('--src', default='assets/raw/ph')
    ap.add_argument('--out', default='assets/v3/rocks')
    ap.add_argument('--targets', default='0.6,1.0,1.4', help='H/r 三档')
    ap.add_argument('--wheel-radius', type=float, default=0.086)
    a = ap.parse_args()
    ratios = [float(x) for x in a.targets.split(',') if x.strip()]
    sources = json.loads((ROOT / a.sources).read_text())
    src_root = ROOT / a.src
    out_root = ROOT / a.out
    out_root.mkdir(parents=True, exist_ok=True)
    index = {'schema': 'v3-rock-index/v1', 'sources': a.sources,
             'wheel_radius_m': a.wheel_radius, 'ratios': ratios, 'rocks': []}
    ok = 0
    for rock in sources['pool']:
        try:
            rec = process_rock(rock, src_root, out_root, ratios, a.wheel_radius)
            index['rocks'].append(rec)
            ok += 1
            print(json.dumps({'rock': rec['rock_id'], 'native_h': rec['native_height_m'],
                              'faces': rec['n_faces_lod0'], 'levels': len(rec['levels'])},
                             ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({'rock': rock['asset_id'], 'error': f'{type(e).__name__}: {e}'},
                             ensure_ascii=False), flush=True)
            index['rocks'].append({'rock_id': rock['asset_id'],
                                   'error': f'{type(e).__name__}: {e}'})
    index['n_ok'] = ok
    (out_root / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2))
    print(json.dumps({'n_ok': ok, 'n_pool': len(sources['pool'])}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
