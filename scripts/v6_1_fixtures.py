"""
V6.1 已知答案 fixture（工作包 B：F0–F5）。

全部 fixture 都标 FIXTURE，不进入真实 Lux3D 方法池，也不计收益。

F0 同形父候选：观测来自该实体本身，父候选 = 该实体。
F1 可见面扰动：父候选可见面外推 8 mm，隐藏部分不动；融合应把可见面拉回并保留隐藏。
F2 同可见面不同隐藏：两个父候选共享正面，背面一个凹、一个平；融合应保留差异。
F3 尺度/坐标往返：raw 按 0.1/1/10 缩放后经逆变换回到同一 world 实体。
F4 坏输入：缺文件/维度不符/坏相机，正式入口必须非零退出。
F5 真值隔离：两个不同隐藏真值下，融合输出身份不变。

用法：
  MUJOCO_GL=osmesa .venv/bin/python scripts/v6_1_fixtures.py --out runs/.../fixtures
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fuse_observed as FZ

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_TAG = 'FIXTURE: not Lux3D; not model benefit'


def sha_file(p):
    return FZ.sha_file(p)


def ellipsoid(r=(0.11, 0.075, 0.14), sub=3):
    m = trimesh.creation.icosphere(subdivisions=sub, radius=1.0)
    m.apply_scale(r)
    m.apply_translation([0, 0, -float(m.bounds[0][2])])
    return m


def boolean_diff(a, b):
    import manifold3d as m3
    A = m3.Manifold(m3.Mesh(np.asarray(a.vertices, dtype=np.float32),
                            np.asarray(a.faces, dtype=np.uint32)))
    B = m3.Manifold(m3.Mesh(np.asarray(b.vertices, dtype=np.float32),
                            np.asarray(b.faces, dtype=np.uint32)))
    out = A - B
    mm = out.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3],
                           np.asarray(mm.tri_verts), process=True)


def write_world(mesh, d, name='body'):
    d = pathlib.Path(d); d.mkdir(parents=True, exist_ok=True)
    body = d / f'{name}.stl'
    m = mesh.copy()
    m.apply_translation([0, 0, -float(m.bounds[0][2])])
    m.export(body)
    (d / 'manifest.json').write_text(json.dumps(
        {'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
         'parts': [f'{name}.stl'], 'world_sha': sha_file(body),
         'source_kind': 'fixture', 'note': FIXTURE_TAG}, indent=2))
    return d, body


def write_case(mesh_path, case_id, out, obstacle_x=1.8, H=None):
    m = trimesh.load(str(mesh_path), force='mesh')
    b = m.bounds
    case = {'case_id': case_id, 'seed': 0, 'mesh': str(mesh_path),
            'H': float(H if H is not None else (b[1][2] - b[0][2])),
            'W': float(b[1][1] - b[0][1]), 'D': float(b[1][0] - b[0][0]),
            'goal_x': 2.6, 'channel_half': 1.2, 'obstacle_x': obstacle_x,
            'fixture': True, 'note': FIXTURE_TAG}
    p = pathlib.Path(out) / f'{case_id}.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(case, ensure_ascii=False, indent=2))
    return p


def observe(case_path, obs_dir):
    obs_dir = pathlib.Path(obs_dir)
    if (obs_dir / 'observation.json').exists():
        return obs_dir
    cmd = [sys.executable, str(ROOT / 'scripts/observe.py'),
           '--case', str(case_path), '--out', str(obs_dir),
           '--cam-height', '0.32']
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f'observe 失败：{r.stderr[-600:]}')
    return obs_dir


def fuse_one(obs, parent_world, pid, out, cfg_path, pitch=None):
    out = pathlib.Path(out)
    cmd = [sys.executable, str(ROOT / 'scripts/fuse_observed.py'),
           '--observation', str(obs), '--parent-world', str(parent_world),
           '--parent-id', pid, '--method', 'H5_F', '--out', str(out),
           '--config', str(cfg_path)]
    if pitch:
        cmd += ['--pitch', str(pitch)]
    env = {'LD_LIBRARY_PATH': '/tmp/sysroot/usr/lib/x86_64-linux-gnu:/tmp/sysroot/lib/x86_64-linux-gnu',
           'MUJOCO_GL': 'osmesa', 'PATH': '/usr/local/bin:/usr/bin:/bin'}
    import os
    e = dict(os.environ); e.update(env)
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=e)
    if r.returncode != 0:
        raise SystemExit(f'fuse 失败 {pid}: {r.stderr[-800:]}')
    return json.loads((out / 'manifest.json').read_text())


def occ_of(mesh, pitch, ref=None):
    grid = fuse_grid(mesh, ref, pitch)
    return FZ.parent_solid(mesh, grid, 1)[0], grid


def fuse_grid(mesh, ref, pitch, margin=3):
    if ref is not None:
        lo = np.minimum(mesh.bounds[0], ref.bounds[0]) - margin * pitch
        hi = np.maximum(mesh.bounds[1], ref.bounds[1]) + margin * pitch
        lo[2] = 0.0
        dims = np.ceil((hi - lo) / pitch).astype(int)
        xs = lo[0] + (np.arange(dims[0]) + 0.5) * pitch
        ys = lo[1] + (np.arange(dims[1]) + 0.5) * pitch
        zs = lo[2] + (np.arange(dims[2]) + 0.5) * pitch
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
        return {'origin': lo, 'pitch': float(pitch), 'dims': dims,
                'xs': xs, 'ys': ys, 'zs': zs, 'X': X, 'Y': Y, 'Z': Z}
    return FZ.make_grid(mesh, np.asarray(mesh.vertices), pitch, margin)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/unseen/delivery_v6_1/v6_1_20261029/fixtures')
    ap.add_argument('--config', default='configs/unseen_v6_1_fusion.json')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / a.config).read_text())
    pitch = float(cfg['pitch_m'])
    results = {'schema': 'fixtures/v6_1', 'tag': FIXTURE_TAG,
               'config': a.config, 'pitch_m': pitch, 'rows': []}

    # ---------------- F0：同形父候选 ----------------
    f0 = out / 'F0'
    base = ellipsoid()
    truth_world, truth_body = write_world(base, f0 / 'truth')
    case = write_case(truth_body, 'F0_truth', f0 / 'cases', obstacle_x=1.8)
    obs = observe(case, f0 / 'observation')
    fus = fuse_one(obs, truth_world, 'F0_parent', f0 / 'fusion', a.config)
    occ_t, grid = occ_of(base, pitch)
    occ_f, _ = occ_of(trimesh.load(f0 / 'fusion/body.stl', force='mesh'), pitch, base)
    inter = int((occ_t & occ_f).sum()); union = int((occ_t | occ_f).sum())
    results['rows'].append({
        'id': 'F0', 'status': 'PASS' if fus['strict']['pass'] and inter / union >= 0.9 else 'FAIL',
        'what': 'observation from the same closed mesh; parent = that mesh',
        'visible': fus['metrics'], 'strict': fus['strict'],
        'occupancy_iou_vs_truth': round(inter / union, 4),
        'hidden_kept_ratio': fus['retention'].get('kept_ratio'),
        'watertight': fus['watertight'],
        'paths': {'observation': str(obs), 'fusion': str(f0 / 'fusion'),
                  'manifest': str(f0 / 'fusion/manifest.json')},
        'note': FIXTURE_TAG})

    # ---------------- F1：可见面扰动，隐藏保持 ----------------
    f1 = out / 'F1'
    m = base.copy()
    v = np.asarray(m.vertices).copy()
    x_front = float(v[:, 0].min())
    cut = x_front + 0.035
    near = v[:, 0] < cut
    v[near, 0] -= 0.008            # 可见面向相机方向外推 8 mm
    m.vertices = v
    parent_w, parent_b = write_world(m, f1 / 'parent_visible_shift')
    obs1 = observe(case, f1 / 'observation')     # 用 F0 的同一观测
    fus1 = fuse_one(obs1, parent_w, 'F1_parent', f1 / 'fusion', a.config)
    # 隐藏核心：x > 物体中位面（远离可见面与测量带）
    occ_p, grid1 = occ_of(m, pitch)
    occ_t1, _ = occ_of(base, pitch, base)
    occ_f1, _ = occ_of(trimesh.load(f1 / 'fusion/body.stl', force='mesh'), pitch, base)
    xmid = float(np.median(base.bounds[:, 0]))
    hid = grid1['X'] > xmid
    hid_core = occ_t1 & hid
    kept = hid_core & occ_f1
    results['rows'].append({
        'id': 'F1', 'status': ('PASS' if fus1['strict']['pass']
                               and kept.sum() / max(hid_core.sum(), 1) >= 0.95 else 'FAIL'),
        'what': 'visible surface pushed 8 mm toward camera; hidden part unchanged',
        'visible': fus1['metrics'], 'strict': fus1['strict'],
        'parent_front_x': round(float(x_front - 0.008), 5),
        'observed_front_x': round(float(np.load(obs1 / 'visible_points.npy')[:, 0].min()), 5),
        'hidden_core_voxels': int(hid_core.sum()),
        'hidden_core_kept': int(kept.sum()),
        'hidden_core_kept_ratio': round(float(kept.sum() / max(hid_core.sum(), 1)), 4),
        'paths': {'fusion': str(f1 / 'fusion')}, 'note': FIXTURE_TAG})

    # ---------------- F2：同可见面，不同隐藏 ----------------
    f2 = out / 'F2'
    notch = trimesh.creation.icosphere(subdivisions=2, radius=0.045)
    notch.apply_translation([float(base.bounds[1][0]) - 0.02, 0.0, 0.09])
    back_cut = boolean_diff(base, notch)
    write_world(back_cut, f2 / 'parent_back_notch')
    fusA = fuse_one(obs1, truth_world, 'F2_flat_back', f2 / 'fusion_flat', a.config)
    fusB = fuse_one(obs1, f2 / 'parent_back_notch', 'F2_notch_back', f2 / 'fusion_notch',
                    a.config)
    va = float(fusA['volume_m3'] or 0.0); vb = float(fusB['volume_m3'] or 0.0)
    results['rows'].append({
        'id': 'F2', 'status': ('PASS' if (fusA['strict']['pass'] and fusB['strict']['pass']
                                          and abs(va - vb) > 1e-5) else 'FAIL'),
        'what': 'same visible surface; two different hidden structures (flat back vs notch)',
        'visible_A': fusA['metrics'], 'visible_B': fusB['metrics'],
        'volume_A_m3': va, 'volume_B_m3': vb,
        'hidden_volume_difference_m3': round(abs(va - vb), 9),
        'retention_A': fusA['retention'], 'retention_B': fusB['retention'],
        'paths': {'A': str(f2 / 'fusion_flat'), 'B': str(f2 / 'fusion_notch')},
        'note': FIXTURE_TAG})

    # ---------------- F3：尺度与坐标往返 ----------------
    f3 = out / 'F3'
    rows3 = []
    for s in (0.1, 1.0, 10.0):
        raw = base.copy()
        raw.apply_scale(s)
        # 正确的“单位/配准”变换：缩回原尺度并贴地（不是只缩物体）
        world = raw.copy()
        world.apply_scale(1.0 / s)
        d, _ = write_world(world, f3 / f'parent_s{s:g}')
        rows3.append({'scale': s, 'world_body_sha': sha_file(d / 'body.stl')})
    uniq = {r['world_body_sha'] for r in rows3}
    results['rows'].append({
        'id': 'F3', 'status': 'PASS' if len(uniq) == 1 else 'FAIL',
        'what': 'raw scaled by 0.1/1/10 then inverse transform; world entity must match',
        'rows': rows3, 'n_unique_world_sha': len(uniq), 'note': FIXTURE_TAG})

    # ---------------- F4：坏输入 ----------------
    f4 = out / 'F4'
    bad = f4 / 'bad_obs'; bad.mkdir(parents=True, exist_ok=True)
    shutil.copy(obs / 'observation.json', bad / 'observation.json')
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/fuse_observed.py'),
                        '--observation', str(bad), '--parent-world', str(truth_world),
                        '--parent-id', 'BAD', '--method', 'H5_F',
                        '--out', str(f4 / 'out_bad'), '--config', str(ROOT / a.config)],
                       capture_output=True, text=True, cwd=str(ROOT))
    (f4 / 'reject.log').write_text(r.stdout + r.stderr)
    bad2 = f4 / 'bad_depth'; bad2.mkdir(parents=True, exist_ok=True)
    for f in ('observation.json', 'mask.png', 'visible_points.npy'):
        shutil.copy(obs / f, bad2 / f)
    np.save(bad2 / 'depth.npy', np.full((960, 1280), np.nan, dtype=np.float32))
    r2 = subprocess.run([sys.executable, str(ROOT / 'scripts/fuse_observed.py'),
                         '--observation', str(bad2), '--parent-world', str(truth_world),
                         '--parent-id', 'BAD2', '--method', 'H5_F',
                         '--out', str(f4 / 'out_bad2'), '--config', str(ROOT / a.config)],
                        capture_output=True, text=True, cwd=str(ROOT))
    (f4 / 'reject_nan_depth.log').write_text(r2.stdout + r2.stderr)
    results['rows'].append({
        'id': 'F4', 'status': ('PASS' if r.returncode != 0 and r2.returncode != 0 else 'FAIL'),
        'what': 'missing visible points and all-invalid depth must be rejected',
        'missing_files_exit': r.returncode,
        'missing_files_reason': (r.stderr.strip().splitlines() or [''])[-1][:200],
        'nan_depth_exit': r2.returncode,
        'nan_depth_reason': (r2.stderr.strip().splitlines() or [''])[-1][:200],
        'logs': [str(f4 / 'reject.log'), str(f4 / 'reject_nan_depth.log')],
        'note': FIXTURE_TAG})

    # ---------------- F5：真值隔离 ----------------
    f5 = out / 'F5'
    # 同一观测、同一父候选；两个“隐藏真值”只影响执行端，不影响融合身份
    t2 = boolean_diff(base, notch)
    write_world(t2, f5 / 'truth_alt')
    fus5a = fuse_one(obs1, truth_world, 'F5_truth_A', f5 / 'fusion_tA', a.config)
    fus5b = fuse_one(obs1, truth_world, 'F5_truth_B', f5 / 'fusion_tB', a.config)
    same = (fus5a['world_sha'] == fus5b['world_sha']
            and fus5a['inputs']['effective_config_sha'] == fus5b['inputs']['effective_config_sha'])
    results['rows'].append({
        'id': 'F5', 'status': 'PASS' if same else 'FAIL',
        'what': 'fusion identity must not depend on hidden truth',
        'fusion_world_sha_A': fus5a['world_sha'], 'fusion_world_sha_B': fus5b['world_sha'],
        'config_sha_A': fus5a['inputs']['effective_config_sha'],
        'config_sha_B': fus5b['inputs']['effective_config_sha'],
        'truth_objects_differ': sha_file(f5 / 'truth_alt/body.stl') != sha_file(truth_body),
        'note': FIXTURE_TAG})

    (out / 'fixtures.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    for r in results['rows']:
        print(r['id'], r['status'], '|', r.get('what'))
    bad_n = [r['id'] for r in results['rows'] if r['status'] != 'PASS']
    print(json.dumps({'n': len(results['rows']), 'fail': bad_n}, ensure_ascii=False))
    return 0 if not bad_n else 1


if __name__ == '__main__':
    sys.exit(main())
