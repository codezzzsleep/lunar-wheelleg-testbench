"""
V5 方向观测包 + 独立真值实例（P0.2）。

  MUJOCO_GL=osmesa .venv/bin/python scripts/make_v5_direction.py \
      --case cases/unseen_v1/R01.json --azimuth 25 \
      --out-dir runs/unseen/delivery_v5/v5_20261029/observations/R01_az25 \
      --observation-id R01_az25 \
      --upload-pkg runs/unseen/recovery_r3/contrast_pkg/az25 \
      --truth-case-out cases/unseen_v1/R01_az25_truth.json

做三件事：
  1. 调 observe.py 生成该方向的 RGB/深度/掩码/可见点云/相机/出生状态；
  2. 把同一偏航的真值网格写成 **world frame** STL（不再二次旋转/平移），
     并生成对应的 truth case（mesh 为 world 资产，obstacle_x=0）；
  3. 记录 upload 包与观测包的相机/取景对应关系，写 direction.json。
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--azimuth', type=float, required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--observation-id', required=True)
    ap.add_argument('--upload-pkg', default=None)
    ap.add_argument('--truth-case-out', required=True)
    ap.add_argument('--cam-height', type=float, default=0.32)
    a = ap.parse_args()

    case = json.loads(pathlib.Path(a.case).read_text())
    out = pathlib.Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---- 1. 观测包（observe.py 唯一渲染口径） ----
    cmd = [sys.executable, str(ROOT / 'scripts/observe.py'),
           '--case', str(ROOT / a.case), '--out', str(out),
           '--azimuth', str(a.azimuth), '--observation-id', a.observation_id,
           '--cam-height', str(a.cam_height)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f'observe 失败：{r.stderr[-500:]}')
    obs_man = json.loads((out / 'observation_manifest.json').read_text())
    obs = json.loads((out / 'observation.json').read_text())

    # ---- 2. 同偏航真值 -> world frame STL ----
    mesh = trimesh.load(str(ROOT / case['mesh']), force='mesh').copy()
    R = trimesh.transformations.rotation_matrix(
        np.deg2rad(a.azimuth), [0.0, 0.0, 1.0])
    mesh.apply_transform(R)
    mesh.apply_translation([float(case['obstacle_x']), 0.0, 0.0])
    zmin = float(np.asarray(mesh.bounds)[0][2])
    if abs(zmin) > 1e-12:
        mesh.apply_translation([0.0, 0.0, -zmin])
    tw = out / 'truth_world'
    tw.mkdir(parents=True, exist_ok=True)
    body = tw / 'body.stl'
    mesh.export(body)
    world_sha = sha(body)
    tm = {
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'source_kind': 'truth', 'parts': ['body.stl'],
        'world_sha': world_sha, 'case': case['case_id'],
        'source_mesh': case['mesh'], 'yaw_deg': float(a.azimuth),
        'obstacle_x': float(case['obstacle_x']),
        'note': ('V5 方向真值：已按 yaw 旋转并平移到 world frame；'
                 '下游必须 identity 放置，禁止再次旋转/平移/贴地'),
    }
    (tw / 'manifest.json').write_text(json.dumps(tm, ensure_ascii=False, indent=2))

    # world 资产的 bounds 用于 truth case 的 W/D/H（不改动几何）
    b = np.asarray(mesh.bounds)
    ext = b[1] - b[0]
    truth_case = {
        'case_id': f"{case['case_id']}_az{int(round(a.azimuth))}_truth",
        'seed': case.get('seed', 0),
        'mesh': str(body),
        'H': float(case['H']), 'W': round(float(ext[0]), 6), 'D': round(float(ext[1]), 6),
        'goal_x': float(case['goal_x']), 'channel_half': float(case.get('channel_half', 1.2)),
        'obstacle_x': 0.0,
        'yaw_deg': 0.0,
        'truth_world_sha': world_sha,
        'source_case': case['case_id'],
        'source_mesh': case['mesh'],
        'world_frame_mesh': True,
        'note': ('V5 方向真值实例：mesh 已经是 world frame，obstacle_x=0；'
                 '下游若再平移/旋转/贴地即为重复变换'),
    }
    tcp = ROOT / a.truth_case_out
    tcp.parent.mkdir(parents=True, exist_ok=True)
    tcp.write_text(json.dumps(truth_case, ensure_ascii=False, indent=2) + '\n')

    # ---- 3. upload 包与观测包的对应关系 ----
    upl = None
    if a.upload_pkg:
        up = ROOT / a.upload_pkg
        manp = up / 'upload_manifest.json'
        if manp.exists():
            um = json.loads(manp.read_text())
            cam0 = np.asarray(um['camera']['world_pos'], dtype=float)
            cam1 = np.asarray(obs['camera']['world_pos'], dtype=float)
            R0 = np.asarray(um['camera']['R_world_from_camera'], dtype=float)
            R1 = np.asarray(obs['camera']['R_world_from_camera'], dtype=float)
            upl = {
                'upload_pkg': a.upload_pkg,
                'upload_sha256': sha(up / 'upload_1024.png'),
                'upload_manifest_sha256': sha(manp),
                'camera_pos_diff_m': float(np.linalg.norm(cam0 - cam1)),
                'camera_rot_max_abs_diff': float(np.max(np.abs(R0 - R1))),
                'upload_longest_side_fraction': um.get('longest_side_fraction'),
                'upload_target_mean_luma': um.get('target_mean_luma'),
                'note': '上传图与观测包共用同一相机位姿与同一石头偏航；分辨率/裁剪不同，映射见各自 manifest',
            }
    direction = {
        'schema': 'direction-observation/v1',
        'observation_id': a.observation_id,
        'case': a.case, 'azimuth_deg': float(a.azimuth),
        'observation_dir': str(out),
        'observation_sha': obs_man['observation_sha'],
        'observation_manifest': str(out / 'observation_manifest.json'),
        'truth_world': str(tw), 'truth_world_sha': world_sha,
        'truth_case': a.truth_case_out,
        'upload': upl,
        'visible': obs['visible'],
        'camera': obs['camera'],
        'note': ('az25/az45 是“不同相对观察方向的生成诊断”，不是原始 R01 单视角的重复采样；'
                 '不把生成几何逆旋转回原 R01 当作纯单视角结果'),
    }
    (out / 'direction.json').write_text(json.dumps(direction, ensure_ascii=False, indent=2))
    print(json.dumps({'observation_id': a.observation_id,
                      'observation_sha': obs_man['observation_sha'][:16],
                      'truth_world_sha': world_sha[:16],
                      'camera_pos_diff_m': (upl or {}).get('camera_pos_diff_m'),
                      'visible': obs['visible']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
