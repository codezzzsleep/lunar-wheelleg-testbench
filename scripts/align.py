"""
可见面配准：把候选网格对齐到观测，输出 T_world_from_asset。

  .venv/bin/python scripts/align.py --candidate <glb|stl> --obs runs/unseen/obs/planA \
      --out runs/unseen/align/<id>

约束（任务书 7.2）：
  · 只用可见点、轮廓、自由空间与公开相机位姿；
  · 初始搜索 yaw ±25°（11 档）、尺度 s0×[0.8,1.25]（5 档），**整体等比**；
  · 最终变换也要满足 yaw 与上方向约束，不能只约束初值再让自由 ICP 翻转；
  · 用同一相机重渲染计算 visible RMS、mask IoU、自由空间违例；
  · 返回矩阵方向固定为 T_world_from_asset（资产点 -> 世界）。

矩阵方向自检：把资产的一个已知点乘 T 后，应落在世界对应位置；
测试里会用一个已知平移/旋转的合成变换验证方向。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import trimesh
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEARCH_YAW_DEG = np.linspace(-25, 25, 11)
SEARCH_SCALE = np.array([0.8, 0.9, 1.0, 1.1, 1.25])
RMS_ABS = 0.005          # 5 mm
RMS_REL = 0.03           # 或 3% 高度


def load_mesh(path):
    sc = trimesh.load(str(path), force='scene')
    if isinstance(sc, trimesh.Scene):
        g = sc.to_geometry()
        if isinstance(g, trimesh.Scene):
            geoms = [x for x in g.geometry.values() if len(x.faces) > 0]
            m = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
        else:
            m = g
    else:
        m = sc
    m = m.copy()
    if m.vertices.shape[0] == 0:
        raise ValueError('空网格')
    return m


def T(scale, yaw_deg, tx, ty, tz):
    """T_world_from_asset：先整体等比缩放，再绕 z 轴 yaw，再平移。"""
    c, s = np.cos(np.deg2rad(yaw_deg)), np.sin(np.deg2rad(yaw_deg))
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    M = np.eye(4)
    M[:3, :3] = R * scale
    M[:3, 3] = [tx, ty, tz]
    return M


def apply_T(mesh, M):
    v = np.asarray(mesh.vertices)
    v2 = (M[:3, :3] @ v.T).T + M[:3, 3]
    return trimesh.Trimesh(v2, np.asarray(mesh.faces), process=False)


def render_eval(mesh_world, obs, W=320, H=240, tmpdir=None):
    """
    用与观测同一相机渲染候选，返回 mask IoU / 深度 RMS / 自由空间违例。
    候选以 mesh_file 形式放入场景（碰撞用凸包，这里只关心渲染轮廓与深度）。
    """
    obsd = json.loads((pathlib.Path(obs) / 'observation.json').read_text())
    fovy = obsd['camera']['fovy']
    cam_pos_body = obsd['camera']['pos_body']
    pitch = obsd['camera']['pitch_deg']

    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.8, name='align')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    # 必须走 posed 路径：mesh_file 会按 target_height_m 重新缩放，
    # 那会把已经算好的世界变换破坏掉。
    pd = pathlib.Path(tmpdir).parent / 'posed_tmp'
    pd.mkdir(parents=True, exist_ok=True)
    (pd / 'mesh.stl').write_bytes(pathlib.Path(tmpdir).read_bytes())
    (pd / 'manifest.json').write_text(json.dumps({'parts': ['mesh.stl']}))
    spec['objects'] = [{'posed_dir': str(pd), 'x': 0.0, 'y': 0.0,
                        'yaw_deg': 0.0, 'target_height_m': None}]
    spec['front_cam'] = {'pos': cam_pos_body, 'pitch_deg': pitch, 'fovy': fovy}
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    r = mujoco.Renderer(m, H, W)
    r.enable_depth_rendering()
    r.update_scene(d, camera=cid)
    dep = r.render()
    r.disable_depth_rendering()

    from PIL import Image as _I
    obs_mask = np.array(_I.open(pathlib.Path(obs) / 'mask.png').convert('L')
                        .resize((W, H))) > 127
    obs_dep = np.load(pathlib.Path(obs) / 'depth.npy')
    obs_dep = np.array(_I.fromarray(obs_dep.astype(np.float32), mode='F').resize((W, H)))

    cam_bid = 1
    obs_geoms = {g for g in range(m.ngeom)
                 if m.geom_bodyid[g] == mujoco.mj_name2id(
                     m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')}
    # 渲染深度里，候选占据的像素 = 深度小于"空场景背景深度"的像素
    cand_mask = np.zeros((H, W), bool)
    vd = None
    cam_pos = np.array(d.cam_xpos[cid]); cam_mat = np.array(d.cam_xmat[cid]).reshape(3, 3)
    K = obsd['intrinsics']
    # 用射线判定候选是否在该像素上（与观测链同一方法）
    for yy in range(0, H, 2):
        for xx in range(0, W, 2):
            pc = np.array([(xx * obsd['image']['W'] / W - K['cx']) / K['fx'],
                           -(yy * obsd['image']['H'] / H - K['cy']) / K['fy'], -1.0])
            gid = np.array([-1], dtype=np.int32)
            dist = mujoco.mj_ray(m, d, cam_pos, cam_mat @ pc, None, 1, -1, gid)
            if dist > 0 and int(gid[0]) in obs_geoms:
                cand_mask[yy, xx] = True
    cand_mask = np.repeat(np.repeat(cand_mask, 2, 0), 2, 1)[:H, :W]

    inter = (cand_mask & obs_mask).sum()
    union = (cand_mask | obs_mask).sum()
    iou = float(inter / union) if union else 0.0
    both = cand_mask & obs_mask
    if both.sum() >= 20:
        dd = np.abs(dep[both] - obs_dep[both])
        rms = float(np.sqrt(np.mean(dd ** 2)))
    else:
        rms = float('inf')
    # 自由空间违例：候选出现在观测认为空的地方，且比观测背景更近
    free = cand_mask & (~obs_mask)
    fsv = float(free.sum() / max(1, cand_mask.sum()))
    return {'iou': round(iou, 4), 'rms_m': round(rms, 5), 'freespace': round(fsv, 4),
            'cand_px': int(cand_mask.sum()), 'obs_px': int(obs_mask.sum())}


def align(candidate, obs, out, workdir):
    obsd = json.loads((pathlib.Path(obs) / 'observation.json').read_text())
    vis = obsd['visible']
    mesh = load_mesh(candidate)
    ext = mesh.extents
    # 由可见高度定初始尺度（只用量测到的 H_vis）
    s0 = float(vis['H_vis']) / max(float(ext[2]), 1e-6)
    # 可见面约束：把候选**最前点**（局部最小 x）对齐到观测到的 x_front，
    # 而不是把质心对齐——否则深一点的候选会整体前移，轮廓完全错位。
    cx = float(vis['x_front'])
    base_z = 0.0
    tmp = pathlib.Path(workdir) / 'cand_tmp.stl'
    tmp.parent.mkdir(parents=True, exist_ok=True)

    best = None
    for sc in SEARCH_SCALE:
        for yaw in SEARCH_YAW_DEG:
            # 让资产包围盒下沿贴地、质心大致落在障碍位置
            m2 = apply_T(mesh, T(s0 * sc, yaw, 0, 0, 0))
            b = m2.bounds
            M = T(s0 * sc, yaw, cx - b[0][0],
                  0.0 - (b[0][1] + b[1][1]) / 2, base_z - b[0][2])
            mw = apply_T(mesh, M)
            mw.export(tmp)
            ev = render_eval(mw, obs, tmpdir=tmp)
            score = (ev['iou'], -ev['rms_m'], -ev['freespace'])
            if best is None or score > best['score']:
                best = {'score': score, 'M': M, 'eval': ev,
                        'scale': float(s0 * sc), 'yaw': float(yaw)}
    ev = best['eval']
    thr = max(RMS_ABS, RMS_REL * float(vis['H_vis']))
    ok = (ev['iou'] >= 0.85 and ev['rms_m'] <= thr and ev['freespace'] <= 0.05)
    rec = {'candidate': str(candidate), 'observation': str(obs),
           'T_world_from_asset': best['M'].tolist(),
           'direction': 'asset -> world',
           'scale_uniform': best['scale'], 'yaw_deg': best['yaw'],
           'metrics': ev, 'rms_threshold_m': round(thr, 5),
           'iou_threshold': 0.85, 'freespace_threshold': 0.05,
           'pass': bool(ok),
           'source_kind': 'fixture' if 'fixture' in str(candidate) else 'generated'}
    out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps({k: rec[k] for k in ('scale_uniform', 'yaw_deg', 'metrics', 'pass')},
                     ensure_ascii=False))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--obs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workdir', default='/tmp/unseen_align')
    a = ap.parse_args()
    return align(a.candidate, a.obs, a.out, a.workdir)


if __name__ == '__main__':
    sys.exit(main())
