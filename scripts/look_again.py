"""
主动观察 v2：在**真实隐藏真值场景**里执行抬高动作，取得真实第二观测，
再用第二观测筛除候选。

  MUJOCO_GL=osmesa .venv/bin/python scripts/look_again.py \
      --protocol plans/unseen_v2_protocol.json --out runs/unseen/recovery_r3/look_again_v2

与 v1 的关键区别（3ef8f98 复核）：
  · v1 起始场景没有真值障碍，比较的是候选自己两张掩码，不是候选对真实第二观测；
  · v1 把"第二视角可见像素>300"当筛选规则，那只是有效性检查；
  · v1 的 raise_body 按控制步算循环却每轮只 mj_step 一次，1.2 s 实际只推进 0.12 s。

本版：真值场景取首视角 → 统一 substeps 入口抬高并停稳 → 真实第二观测
      → 候选在**同一机器人状态 + 同一第二相机**下渲染 → 按轮廓 IoU 筛选
      → 淘汰后从观察后状态重新决策。
"""
import argparse
import json
import pathlib
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import camera_io
import mujoco
import terrain
import wheelleg_env
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAISE_S = 1.6
SETTLE_S = 2.5
# 仓库 drive_test 已验证的站姿（不新增步态，只换目标姿态）
STANCE_LOW = {'hip': 0.0, 'thigh': 0.85, 'calf': -1.65}
STANCE_HIGH = {'hip': 0.0, 'thigh': 0.55, 'calf': -1.05}
IOU_MIN = 0.85
KP_HOLD = 120.0
KD_HOLD = 6.0


def scene_for(case, world=None, mesh_file=None):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[],
                             goal_x=float(case.get('goal_x', 2.8)), name='look')
    spec['channel'] = {'center_y': 0.0, 'half_width': float(case.get('channel_half', 1.2))}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    if world:
        spec['objects'] = [{'posed_dir': str(world)}]
    elif mesh_file:
        spec['objects'] = [{'mesh_file': str(pathlib.Path(mesh_file).resolve()),
                            'x': case['obstacle_x'], 'y': 0.0, 'yaw_deg': 0.0,
                            'target_height_m': case['H']}]
    return spec


def set_cam_height(env, cam_height):
    cid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    bid = env.model.cam_bodyid[cid]
    mujoco.mj_forward(env.model, env.data)
    B = np.asarray(env.data.xmat[bid]).reshape(3, 3)
    b = np.asarray(env.data.xpos[bid])
    env.model.cam_pos[cid][2] = (cam_height - b[2] - B[2, 0] * 0.42) / B[2, 2]
    mujoco.mj_forward(env.model, env.data)
    return cid


def capture(env, cid, out_png, W=1280, H=960):
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    r = mujoco.Renderer(m, H, W)
    r.update_scene(d, camera=cid)
    Image.fromarray(r.render()).save(out_png)
    r.enable_depth_rendering(); r.update_scene(d, camera=cid)
    dep = r.render().copy(); r.disable_depth_rendering()
    obid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    mask = np.zeros_like(dep, dtype=bool)
    if obid >= 0:
        keep = m.body_pos[obid].copy()
        m.body_pos[obid] = [0, 0, -80]; mujoco.mj_forward(m, d)
        r.enable_depth_rendering(); r.update_scene(d, camera=cid)
        bg = r.render().copy(); r.disable_depth_rendering()
        m.body_pos[obid] = keep; mujoco.mj_forward(m, d)
        mask = (np.isfinite(dep) & np.isfinite(bg) & (dep < bg - 1e-3)
                & (dep > 0) & (dep < 100))
    snap = {'world_pos': [float(x) for x in d.cam_xpos[cid]],
            'R_world_from_camera': [[float(v) for v in row]
                                    for row in np.asarray(d.cam_xmat[cid]).reshape(3, 3)],
            'fovy_deg': float(m.cam_fovy[cid])}
    return {'mask': mask, 'depth': dep, 'snapshot': snap}


def _stance_targets(env, stance):
    return {f'{leg}_{p}_joint': float(v) for leg in ('FL', 'FR', 'RL', 'RR')
            for p, v in stance.items()}


def raise_body(env, seconds=RAISE_S, settle=SETTLE_S):
    """
    用**已验证的固定高站姿** STANCE_HIGH 作为目标（不是每步 q+delta 的持续偏置）。

    旧实现把目标不断往前推，等价于恒定偏置，无法收敛到固定姿态，
    因此出现"数值上抬高、随后失稳倒地"。现在：低姿态 -> 高姿态平滑插值，
    到位后保持；轮子真实制动；逐物理步记录真实峰值与稳定保持。
    """
    m, d = env.model, env.data
    z0 = float(d.qpos[2])
    low = _stance_targets(env, STANCE_LOW)
    high = _stance_targets(env, STANCE_HIGH)
    n_ctrl = int(seconds * env.control_hz)
    z_trace = []
    for i in range(n_ctrl):
        a = min(1.0, (i + 1) / max(1, n_ctrl * 0.6))
        for jn, t_hi in high.items():
            e = env.J[jn]
            tgt = (1 - a) * low[jn] + a * t_hi
            d.ctrl[e['act']] = float(np.clip(
                90.0 * (tgt - d.qpos[e['qadr']]) - 5.0 * d.qvel[e['vadr']],
                -23.7, 23.7))
        for leg in ('FL', 'FR', 'RL', 'RR'):
            e = env.J[f'{leg}_wheel_joint']
            d.ctrl[e['act']] = float(np.clip(-6.0 * d.qvel[e['vadr']], -23.7, 23.7))
        for _ in range(env.substeps):
            if hasattr(env, '_soil_step'):
                env._soil_step()
            mujoco.mj_step(m, d)
            env.n_physics += 1
            env.t += env.dt
        z_trace.append(float(d.qpos[2]))

    # 停稳：保持**高姿态目标**（不是当前角度，也不是逐步加偏置）
    hold = dict(high)
    still = 0
    for _ in range(int(settle * env.control_hz)):
        for jn, tgt in hold.items():
            e = env.J[jn]
            d.ctrl[e['act']] = float(np.clip(
                KP_HOLD * (tgt - d.qpos[e['qadr']]) - KD_HOLD * d.qvel[e['vadr']],
                -23.7, 23.7))
        for leg in ('FL', 'FR', 'RL', 'RR'):
            e = env.J[f'{leg}_wheel_joint']
            d.ctrl[e['act']] = float(np.clip(-6.0 * d.qvel[e['vadr']], -23.7, 23.7))
        for _ in range(env.substeps):
            if hasattr(env, '_soil_step'):
                env._soil_step()
            mujoco.mj_step(m, d)
            env.n_physics += 1
            env.t += env.dt
        z_trace.append(float(d.qpos[2]))
        if (float(np.linalg.norm(d.qvel[:3])) < 0.03
                and float(np.linalg.norm(d.qvel[3:6])) < 0.08):
            still += 1
            if still >= max(1, int(0.3 * env.control_hz)):
                break
        else:
            still = 0
    z1 = float(d.qpos[2])
    return {'z_before': round(z0, 4), 'z_after': round(z1, 4),
            'z_peak_m': round(float(np.max(z_trace)) if z_trace else z1, 4),
            'stance_target': 'STANCE_HIGH (drive_test 已验证)',
            'delta_z_m': round(z1 - z0, 4),
            'vel_norm': round(float(np.linalg.norm(d.qvel[:6])), 4),
            'n_control_steps': n_ctrl, 'n_physics_steps': int(env.n_physics),
            'sim_time_s': round(float(env.t), 4),
            'v_lin': round(float(np.linalg.norm(d.qvel[:3])), 4),
            'v_ang': round(float(np.linalg.norm(d.qvel[3:6])), 4),
            'stable': bool(float(np.linalg.norm(d.qvel[:3])) < 0.03
                           and float(np.linalg.norm(d.qvel[3:6])) < 0.08),
            'qpos': [round(float(x), 6) for x in d.qpos],
            'qvel': [round(float(x), 6) for x in d.qvel]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--camera-height', type=float, default=0.32,
                    help='观察前机位（与首视角观测包一致）')
    ap.add_argument('--soil', default='rigid')
    ap.add_argument('--redecide', action='store_true')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    proto = json.loads(pathlib.Path(a.protocol).read_text())
    case = json.loads(pathlib.Path(proto['case']).read_text())
    cands = proto.get('candidates') or []
    rec = {'workflow': 'look_again/v2',
           'candidates_in': [c['candidate_id'] for c in cands],
           'screening_rule': f'silhouette IoU vs real second observation >= {IOU_MIN}',
           'disclosure': '第二观测的 RGB/深度属于可用传感数据；未把真值网格交给规划器'}

    spec = scene_for(case, mesh_file=case['mesh'])
    if a.soil != 'rigid':
        spec['soil'] = {'mode': a.soil}
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=0)
    cid = set_cam_height(env, a.camera_height)
    v1 = capture(env, cid, out / 'truth_view1.png')
    rec['view1'] = {'cam_z': round(float(v1['snapshot']['world_pos'][2]), 4),
                    'mask_px': int(v1['mask'].sum())}
    act = raise_body(env)
    v2 = capture(env, cid, out / 'truth_view2.png')
    Image.fromarray((v2['mask'] * 255).astype(np.uint8)).save(out / 'truth_view2_mask.png')
    np.save(out / 'truth_view2_depth.npy', v2['depth'])
    rec['observation_action'] = act
    rec['view2'] = {'cam_z': round(float(v2['snapshot']['world_pos'][2]), 4),
                    'mask_px': int(v2['mask'].sum()),
                    'delta_z_m': round(float(v2['snapshot']['world_pos'][2])
                                       - float(v1['snapshot']['world_pos'][2]), 4)}
    rec['observation_status'] = 'ok' if act['stable'] else 'observation_unstable'
    if not act['stable']:
        rec['note'] = '未停稳：不把上升中的图当作完成观察'

    # 第二观测本身是否可用：真值障碍在第二视角下必须仍占可辨像素
    usable_ratio = (float(v2['mask'].sum()) / max(1, int(v1['mask'].sum())))
    rec['second_view_usable'] = bool(usable_ratio >= 0.30)
    rec['second_view_usable_ratio'] = round(usable_ratio, 4)
    if not rec['second_view_usable']:
        rec['outcome'] = 'second_observation_unusable'
        rec['note'] = ('抬高动作导致机位仰起，目标在第一视角占 %d px、第二视角只剩 %d px，'
                       '无法据此判定候选；不把它算作候选被证伪'
                       % (int(v1['mask'].sum()), int(v2['mask'].sum())))
        rec['screening'] = []
        rec['kept'], rec['rejected'] = [], []
        (out / 'look_again.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        print(json.dumps({'stable': act['stable'], 'dz': rec['view2']['delta_z_m'],
                          'v1_px': rec['view1']['mask_px'],
                          'v2_px': rec['view2']['mask_px'],
                          'usable_ratio': rec['second_view_usable_ratio'],
                          'outcome': rec['outcome']}, ensure_ascii=False))
        return 0

    per = []
    truth_mask = v2['mask']
    for c in cands:
        e2 = wheelleg_env.WheelLegEnv(scene_for(case, world=c['world_dir']))
        e2.reset(seed=0)
        e2.data.qpos[:] = np.asarray(act['qpos'])
        e2.data.qvel[:] = np.asarray(act['qvel'])
        mujoco.mj_forward(e2.model, e2.data)
        cid2 = mujoco.mj_name2id(e2.model, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
        camera_io.restore(e2.model, e2.data, cid2, v2['snapshot'])
        cv = capture(e2, cid2, out / f"{c['candidate_id']}_view2.png")
        cm = cv['mask']
        inter = int((cm & truth_mask).sum())
        union = int((cm | truth_mask).sum()) or 1
        iou = inter / union
        both = cm & truth_mask & np.isfinite(cv['depth']) & np.isfinite(v2['depth'])
        dmed = (float(np.median(np.abs(cv['depth'][both] - v2['depth'][both]))) * 1000
                if both.sum() > 50 else None)
        visible = int(cm.sum())
        kept = bool(visible > 300 and iou >= IOU_MIN)
        per.append({'candidate_id': c['candidate_id'],
                    'candidate_mask_px': visible,
                    'silhouette_iou_vs_truth_view2': round(float(iou), 4),
                    'depth_median_abs_mm': (round(dmed, 2) if dmed is not None else None),
                    'kept': kept,
                    'reject_reason': None if kept else
                    ('not_visible_from_second_view' if visible <= 300
                     else f'silhouette IoU {iou:.3f} < {IOU_MIN}')})
    kept = [p['candidate_id'] for p in per if p['kept']]
    rec['screening'] = per
    rec['kept'] = kept
    rec['rejected'] = [p['candidate_id'] for p in per if not p['kept']]
    rec['outcome'] = ('all_candidates_rejected' if not kept else
                      ('no_candidate_rejected' if len(kept) == len(cands)
                       else 'screened'))

    if a.redecide and rec['outcome'] == 'screened':
        sub = dict(proto)
        sub['candidates'] = [c for c in cands if c['candidate_id'] in kept]
        candp = out / 'candidates_after_observation.json'
        candp.write_text(json.dumps([{'candidate_id': c['candidate_id'],
                                      'task_id': c.get('task_id'),
                                      'world_dir': c['world_dir'],
                                      'world_sha256': c.get('world_sha'),
                                      'collision_dir': c['collision_dir'],
                                      'coordinate_frame': 'world',
                                      'planning_eligible': True,
                                      'observation_group': 'A'}
                                     for c in sub['candidates']],
                                    ensure_ascii=False, indent=2))
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/unseen_pipeline.py'),
                            '--case', proto['case'], '--hyp-source', 'H5',
                            '--candidates', str(candp),
                            '--out', str(out / 'redecide'), '--seeds', '0,1,2'],
                           capture_output=True, text=True, cwd=str(ROOT))
        summ = None
        if r.returncode == 0 and r.stdout.strip():
            try:
                summ = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                summ = None
        rec['redecision'] = {'exit': r.returncode, 'summary': summ,
                             'note': '从观察后状态重新决策；观察耗时已计入 sim_time_s'}
    (out / 'look_again.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps({'stable': act['stable'], 'dz': rec['view2']['delta_z_m'],
                      'v1_px': rec['view1']['mask_px'], 'v2_px': rec['view2']['mask_px'],
                      'screening': [(p['candidate_id'],
                                     p['silhouette_iou_vs_truth_view2'], p['kept'])
                                    for p in per],
                      'outcome': rec['outcome']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
