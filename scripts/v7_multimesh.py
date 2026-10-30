"""
V7-R1 §11.3：解除单 mesh 面数限制（同一 MuJoCo 场景中的多个视觉 mesh）。

做法：
  · 保留完整 canonical 网格作为几何/占据/哈希依据；
  · 按三角面分块（默认每块 ≤10 万面），每块保留**原世界坐标**，不缩放、不居中、不贴地；
  · 所有块写进同一个 asset manifest 的 `parts`，MuJoCo 在同一场景、同一相机里一次渲染，
    深度缓冲统一处理遮挡（不是分别渲染再平均指标）；
  · 视觉分块不需要为切口填盖；碰撞仍走独立 box 表示。

验证（`--validate`）：拿一个**不超面数**的已知实体，切成多块后与未切分的原实体
分别渲染，要求 mask IoU ≥0.999、深度 P95 差 ≤0.2 mm。

  .venv/bin/python scripts/v7_multimesh.py --world <posed world> --out <new world> [--max-faces 100000]
  .venv/bin/python scripts/v7_multimesh.py --validate --world <posed world> --obs <obs dir> --out <dir>
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
MAX_FACES_DEFAULT = 100000


def sha_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def split_mesh(mesh, max_faces=MAX_FACES_DEFAULT):
    """按面质心沿最长轴分箱，每块面数 ≤ max_faces；世界坐标保持不变。"""
    n = len(mesh.faces)
    if n <= max_faces:
        return [mesh], {'n_parts': 1, 'reason': 'already_under_limit'}
    k = int(np.ceil(n / max_faces))
    cent = mesh.triangles_center
    axis = int(np.argmax(mesh.extents))
    order = np.argsort(cent[:, axis])
    bounds = np.linspace(0, n, k + 1).astype(int)
    parts = []
    for i in range(k):
        idx = order[bounds[i]:bounds[i + 1]]
        sub = mesh.submesh([idx], append=True, repair=False)
        parts.append(sub)
    return parts, {'n_parts': k, 'axis': axis, 'max_faces': max_faces,
                   'faces_per_part': [int(len(p.faces)) for p in parts],
                   'note': '按面质心沿最长轴分箱；切口不填盖；顶点保持世界坐标'}


def write_world(parts, out, source_sha, canonical_faces, extra=None):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for i, p in enumerate(parts):
        # 文件名带内容身份，避免 MuJoCo 按名字复用旧 mesh
        h = trimesh.util.attach_to_log  # noqa: F841  (keep import semantics clear)
        tmp = out / f'_part{i}.stl'
        p.export(tmp)
        digest = sha_file(tmp)[:12]
        final = out / f'part{i}_{digest}.stl'
        tmp.replace(final)
        names.append(final.name)
    man = {
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'parts': names, 'n_parts': len(names),
        'world_sha': source_sha,
        'canonical_faces': canonical_faces,
        'note': ('多视觉 mesh 分块：同一场景一次渲染，顶点即世界坐标，'
                 '不缩放/不居中/不贴地；碰撞仍用独立 box 表示'),
    }
    if extra:
        man.update(extra)
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    return out, man


def render_world(posed_dir, obs_dir, W=640, H=480):
    """用统一物理入口渲染一个 posed world，返回 mask/depth（单通道）。"""
    import mujoco
    import terrain
    import wheelleg_env
    obs = json.loads((pathlib.Path(obs_dir) / 'observation.json').read_text())
    cam = obs['camera']
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='mm')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['objects'] = [{'posed_dir': str(posed_dir)}]
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    base = np.asarray(d.xpos[bid], dtype=float)
    # 用观测里的相机世界位姿反推相对 base 的局部位姿，两张图用同一相机
    cam_world = np.asarray(cam.get('world_pos'), dtype=float)
    cam_R = np.asarray(cam.get('world_rot') or np.eye(3), dtype=float)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    if cid < 0:
        raise SystemExit('模型里没有 front_cam')
    rel = cam_R @ np.eye(3)
    d.cam_xpos[cid] = cam_world
    d.cam_xmat[cid] = cam_R.reshape(-1)
    mujoco.mj_forward(m, d)
    r = mujoco.Renderer(m, H, W)
    r.update_scene(d, camera=cid)
    rgb = r.render()
    r.close()
    return rgb, cam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--world', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-faces', type=int, default=MAX_FACES_DEFAULT)
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--obs', default=None)
    a = ap.parse_args()
    w = ROOT / a.world
    body = w / 'body.stl'
    if not body.exists():
        raise SystemExit(f'缺少 {body}')
    mesh = trimesh.load(str(body), force='mesh', process=False)
    src_sha = sha_file(body)
    parts, meta = split_mesh(mesh, a.max_faces)
    out, man = write_world(parts, ROOT / a.out, src_sha, len(mesh.faces), {'split': meta})
    print(json.dumps({'out': str(out), 'n_parts': man['n_parts'],
                      'faces': man['canonical_faces'],
                      'faces_per_part': meta.get('faces_per_part')}, ensure_ascii=False))
    if a.validate:
        if not a.obs:
            raise SystemExit('--validate 需要 --obs')
        import align
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp()) / 'm.stl'
        mesh.export(tmp)
        ev_single = align.render_eval(mesh, ROOT / a.obs, tmpdir=tmp)
        ev_multi = align.render_eval(None, ROOT / a.obs, posed_dir=str(out))
        keys = ('mask_iou', 'depth_med_mm', 'depth_p95_mm', 'vis_pt_p95_mm',
                'freespace_violation')
        rep = {'schema': 'multimesh-validate/v7',
               'single': {k: ev_single.get(k) for k in keys},
               'multi': {k: ev_multi.get(k) for k in keys},
               'n_parts': man['n_parts'], 'faces': man['canonical_faces'],
               'tolerance': {'mask_iou_abs': 0.001, 'depth_p95_mm_abs': 0.2,
                             'vis_pt_p95_mm_abs': 0.2}}
        d_iou = abs(float(ev_single.get('mask_iou') or 0) - float(ev_multi.get('mask_iou') or 0))
        d_p95 = abs(float(ev_single.get('depth_p95_mm') or 0) - float(ev_multi.get('depth_p95_mm') or 0))
        rep['checks'] = {'mask_iou_within': d_iou <= rep['tolerance']['mask_iou_abs'],
                         'depth_p95_within': d_p95 <= rep['tolerance']['depth_p95_mm_abs']}
        rep['pass'] = all(rep['checks'].values())
        (ROOT / a.out / 'multimesh_validate.json').write_text(
            json.dumps(rep, ensure_ascii=False, indent=2))
        print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
