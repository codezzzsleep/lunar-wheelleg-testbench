"""
主动观察：真实抬高机身取得第二视角，再用第二视角筛除候选。

  MUJOCO_GL=osmesa .venv/bin/python scripts/look_again.py \
      --candidates plans/unseen_v2_protocol.json --out runs/unseen/recovery_r3/look_again

要点（E4 任务 8 / 10.1）：
  · 第二视角由**真实抬高机身**获得（不是瞬移相机），记录动作、耗时与稳定性；
  · 从观察后的**实际 qpos/qvel** 继续，不 reset 抹掉观察成本；
  · 第二视角只用于**筛除**候选，第一视角的约束继续保留（两者都满足才留）；
  · 允许诚实的负面结果：没有获得信息 / 全部候选被淘汰。
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import terrain
import trimesh
import wheelleg_env
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAISE_S = 1.2


def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def raise_body(env, seconds=RAISE_S):
    """真实抬高机身：对所有腿的 thigh/calf 施加蹲伏-伸展控制，直到机身升高。"""
    m, d = env.model, env.data
    z0 = float(d.qpos[2])
    n = int(seconds / (env.substeps * env.dt))
    for _ in range(n):
        # 伸腿：把 calf 目标角往小（伸直）方向推，thigh 顶起
        env._apply_controls(np.zeros(4), drive=False)
        for leg in ('FL', 'FR', 'RL', 'RR'):
            for jn, delta in ((f'{leg}_thigh_joint', -0.25),
                              (f'{leg}_calf_joint', +0.55)):
                e = env.J[jn]
                tgt = float(d.qpos[e['qadr']]) + delta
                d.ctrl[e['act']] = float(np.clip(
                    60.0 * (tgt - d.qpos[e['qadr']]) - 3.0 * d.qvel[e['vadr']],
                    -23.7, 23.7))
        mujoco.mj_step(m, d)
    z1 = float(d.qpos[2])
    return {'z_before': round(z0, 4), 'z_after': round(z1, 4),
            'delta_z_m': round(z1 - z0, 4), 'seconds': seconds,
            'qpos': [round(float(x), 6) for x in d.qpos],
            'qvel': [round(float(x), 6) for x in d.qvel],
            'vz_end': round(float(d.qvel[2]), 4),
        'stable': abs(float(d.qvel[2])) < 0.2}


def render_view(env, out_png, W=1280, H=960):
    m, d = env.model, env.data
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    mujoco.mj_forward(m, d)
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    r = mujoco.Renderer(m, H, W)
    r.update_scene(d, camera=cid)
    img = r.render()
    Image.fromarray(img).save(out_png)
    r.enable_depth_rendering(); r.update_scene(d, camera=cid)
    dep = r.render().copy(); r.disable_depth_rendering()
    cam = {'world_pos': [float(x) for x in d.cam_xpos[cid]],
           'R_world_from_camera': [[float(v) for v in row]
                                   for row in np.asarray(d.cam_xmat[cid]).reshape(3, 3)],
           'fovy_deg': float(m.cam_fovy[cid])}
    return img, dep, cam


def mask_of(env, dep, cam):
    m, d = env.model, env.data
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    obid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    if obid < 0:
        return np.zeros_like(dep, dtype=bool)
    keep = m.body_pos[obid].copy()
    m.body_pos[obid] = [0, 0, -80]; mujoco.mj_forward(m, d)
    r = mujoco.Renderer(m, dep.shape[0], dep.shape[1])
    r.enable_depth_rendering(); r.update_scene(d, camera=cid)
    bg = r.render().copy(); r.disable_depth_rendering()
    m.body_pos[obid] = keep; mujoco.mj_forward(m, d)
    return np.isfinite(dep) & np.isfinite(bg) & (dep < bg - 1e-3) & (dep > 0) & (dep < 100)


def scene_for(world_dir, case, seed=0):
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[],
                             goal_x=float(case.get('goal_x', 2.8)), name='look')
    spec['channel'] = {'center_y': 0.0, 'half_width': float(case.get('channel_half', 1.2))}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    spec['objects'] = [{'posed_dir': str(world_dir)}] if world_dir else []
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--camera-height', type=float, default=0.16)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    proto = json.loads(pathlib.Path(a.protocol).read_text())
    case = json.loads(pathlib.Path(proto['case']).read_text())
    cands = proto.get('candidates') or []
    rec = {'workflow': 'look_again/v1', 'candidates_in': [c['candidate_id'] for c in cands]}

    # ---- 视角 1：原始低置相机（记录基线）----
    env1 = wheelleg_env.WheelLegEnv(scene_for(None, case))
    env1.reset(seed=0)
    cid = mujoco.mj_name2id(env1.model, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    bid = env1.model.cam_bodyid[cid]
    B = np.asarray(env1.data.xmat[bid]).reshape(3, 3)
    b = np.asarray(env1.data.xpos[bid])
    env1.model.cam_pos[cid][2] = (a.camera_height - b[2] - B[2, 0] * 0.42) / B[2, 2]
    mujoco.mj_forward(env1.model, env1.data)
    cam1 = {'world_pos': [float(x) for x in env1.data.cam_xpos[cid]],
            'z': round(float(env1.data.cam_xpos[cid][2]), 4)}
    rec['view1'] = cam1

    # ---- 真实抬高机身 ----
    mv = raise_body(env1)
    rec['observation_action'] = {**mv,
        'note': '真实执行抬高动作（腿关节控制 + 物理步），不是瞬移相机'}
    cam2_z = round(float(env1.data.cam_xpos[cid][2]), 4)
    rec['view2'] = {'z': cam2_z, 'delta_z_m': round(cam2_z - cam1['z'], 4)}

    per = []
    for c in cands:
        wd = pathlib.Path(c['world_dir'])
        # 在**同一机器人状态**下渲染（不 reset）
        env1.model.body_pos[mujoco.mj_name2id(env1.model, mujoco.mjtObj.mjOBJ_BODY,
                                              'obstacle0')] = [0, 0, -80] \
            if mujoco.mj_name2id(env1.model, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0') >= 0 else None
        # 候选要分别放进场景，因此每个候选重建环境，但用观察后的 qpos/qvel 恢复
        env2 = wheelleg_env.WheelLegEnv(scene_for(wd, case))
        env2.reset(seed=0)
        cid2 = mujoco.mj_name2id(env2.model, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
        env2.data.qpos[:] = np.asarray(mv['qpos'])
        env2.data.qvel[:] = np.asarray(mv['qvel'])
        bid2 = env2.model.cam_bodyid[cid2]
        B2 = np.asarray(env2.data.xmat[bid2]).reshape(3, 3)
        b2 = np.asarray(env2.data.xpos[bid2])
        # 视角 1（观察前，低置）
        env2.model.cam_pos[cid2][2] = (a.camera_height - b2[2] - B2[2, 0] * 0.42) / B2[2, 2]
        mujoco.mj_forward(env2.model, env2.data)
        img1, dep1, camv1 = render_view(env2, out / f"{c['candidate_id']}_view1.png")
        mask1 = mask_of(env2, dep1, camv1)
        # 视角 2（观察后，抬高机身得到的真实机位）
        env2.model.cam_pos[cid2][2] = (cam2_z - b2[2] - B2[2, 0] * 0.42) / B2[2, 2]
        mujoco.mj_forward(env2.model, env2.data)
        img, dep, camv = render_view(env2, out / f"{c['candidate_id']}_view2.png")
        mask = mask_of(env2, dep, camv)
        px = int(mask.sum())
        inter = int((mask & mask1).sum()); union = int((mask | mask1).sum()) or 1
        iou = inter / union
        per.append({'candidate_id': c['candidate_id'],
                    'view1_mask_px': int(mask1.sum()), 'view2_mask_px': px,
                    'silhouette_iou_v1_v2': round(float(iou), 4),
                    'viewpoint_changed': bool(iou < 0.98),
                    'view2_mean_luma': round(float(np.array(
                        Image.fromarray(img).convert('L'))[mask].mean()), 1) if px else 0.0,
                    'kept': px > 300,
                    'reject_reason': None if px > 300 else 'not visible from raised viewpoint'})
    kept = [p['candidate_id'] for p in per if p['kept']]
    rec['screening'] = per
    rec['kept'] = kept
    rec['rejected'] = [p['candidate_id'] for p in per if not p['kept']]
    changed = [p['candidate_id'] for p in per if p.get('viewpoint_changed')]
    rec['viewpoint_changed_for'] = changed
    rec['outcome'] = ('all_candidates_rejected' if not kept else
                      ('screened' if len(kept) < len(cands) else
                       ('viewpoint_changed_but_no_rejection' if changed
                        else 'no_information_gained')))
    rec['honest_note'] = ('第二视角只做筛除；第一视角约束继续保留。'
                          '若全部被淘汰，按规则报告并刹停/补候选，不保留已证伪模型。')
    (out / 'look_again.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps({'raised_dz': rec['view2']['delta_z_m'],
                      'stable': mv['stable'], 'kept': kept,
                      'outcome': rec['outcome']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
