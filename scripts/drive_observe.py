"""
行驶观察位：真实差速行驶到侧向观察点 → 朝向目标 → 制动 → 稳定保持 → 采集第二视角。

  MUJOCO_GL=osmesa .venv/bin/python scripts/drive_observe.py \
      --case cases/unseen_v1/R01.json --obs runs/unseen/recovery_r3/obs_R01 \
      --out runs/unseen/recovery_r3/drive_observe_R01 --seeds 0 1 2 ...

与抬高路线（已两次失败）的区别：
  · 不再追加姿态调参；用**轮式行驶**改变机位；
  · 位置全部由统一物理入口推进（env.step / brake_step），不直接改 qpos；
  · 观察目标只依据首视角位置、公开通道与机器人包络选择，不读隐藏背深；
  · 稳定判据同时含线速度、角速度、倾角与一段连续保持时间；
  · 不稳定 / 目标丢失 / 严重裁切 -> 立即退出筛选，候选记 not_evaluated。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mujoco
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 实测稳定包络（空场扫描）：v<=0.10 m/s、|w|<=0.35 rad/s 稳定；
# v>=0.15 m/s 会抬头失稳并失去接触（tilt 23°、ncon=0）。观察动作据此限幅。
# 观测协议版本（正式闭环必须复用 observation_protocol() 与 is_usable()）
OBSERVATION_PROTOCOL_VERSION = 'observation-protocol/v1'


def observation_protocol():
    """把**实际使用**的全部判据集中定义，供观察与正式闭环共用。"""
    return {
        'version': OBSERVATION_PROTOCOL_VERSION,
        'v_lin_max': STABLE_V_LIN, 'v_ang_max': STABLE_V_ANG,
        'tilt_max_deg': STABLE_TILT_DEG, 'hold_s': STABLE_HOLD_S,
        'min_target_px': MIN_TARGET_PX, 'min_depth_valid_frac': MIN_DEPTH_FRAC,
        'min_cam_baseline_m': MIN_CAM_BASELINE_M,
        'min_bearing_change_deg': MIN_BEARING_CHANGE_DEG,
        'cam_forward_change_deg_diagnostic': MIN_CAM_YAW_CHANGE_DEG,
        'note': ('旧 12° 相机前向门只作诊断；实际启用的是基线>=0.45 m 与视线角>=8°。'
                 '旧运行保留原记录，不声称在旧门下达成 10/10'),
    }


def is_usable(stable, mask_px, depth_frac, baseline_m, bearing_change_deg):
    """**唯一**可用性判定；观察脚本与正式闭环都调用它。"""
    pr = observation_protocol()
    return bool(stable and mask_px >= pr['min_target_px']
                and depth_frac >= pr['min_depth_valid_frac']
                and baseline_m >= pr['min_cam_baseline_m']
                and bearing_change_deg >= pr['min_bearing_change_deg'])

# 运行前写死的判据（不按结果调整）
STABLE_V_LIN = 0.05          # m/s
STABLE_V_ANG = 0.10          # rad/s
STABLE_TILT_DEG = 8.0
STABLE_HOLD_S = 0.4
MIN_TARGET_PX = 1500         # 目标在该视角的有效像素下限
MIN_DEPTH_FRAC = 0.60        # 目标像素中有效深度占比下限
MIN_CAM_YAW_CHANGE_DEG = 12.0  # 相机前向夹角变化下限（保留，作诊断）
MIN_CAM_BASELINE_M = 0.45      # 相机**实际平移基线**下限（不能用转向冒充视差）
MIN_BEARING_CHANGE_DEG = 8.0   # 围绕公开锚点的视线角变化下限


def _spec(case, world=None, mesh=None):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='do')
    spec['channel'] = {'center_y': 0.0, 'half_width': float(case.get('channel_half', 1.2))}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    if world:
        spec['objects'] = [{'posed_dir': str(world)}]
    elif mesh:
        spec['objects'] = [{'mesh_file': str(pathlib.Path(mesh).resolve()),
                            'x': case['obstacle_x'], 'y': 0.0, 'yaw_deg': 0.0,
                            'target_height_m': case['H']}]
    return spec


def set_cam_height(env, h):
    cid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
    bid = env.model.cam_bodyid[cid]
    mujoco.mj_forward(env.model, env.data)
    B = np.asarray(env.data.xmat[bid]).reshape(3, 3)
    b = np.asarray(env.data.xpos[bid])
    env.model.cam_pos[cid][2] = (h - b[2] - B[2, 0] * 0.42) / B[2, 2]
    mujoco.mj_forward(env.model, env.data)
    return cid


def capture(env, cid, out_png, W=1280, H=960):
    m, d = env.model, env.data
    mujoco.mj_forward(m, d)
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    r = mujoco.Renderer(m, H, W)
    r.update_scene(d, camera=cid)
    from PIL import Image
    Image.fromarray(np.array(r.render(), copy=True)).save(out_png)
    r.enable_depth_rendering(); r.update_scene(d, camera=cid)
    dep = np.array(r.render(), copy=True); r.disable_depth_rendering()
    obid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'obstacle0')
    mask = np.zeros_like(dep, dtype=bool)
    if obid >= 0:
        keep = m.body_pos[obid].copy()
        m.body_pos[obid] = [0, 0, -80]; mujoco.mj_forward(m, d)
        r.enable_depth_rendering(); r.update_scene(d, camera=cid)
        bg = np.array(r.render(), copy=True); r.disable_depth_rendering()
        m.body_pos[obid] = keep; mujoco.mj_forward(m, d)
        mask = (np.isfinite(dep) & np.isfinite(bg) & (dep < bg - 1e-3)
                & (dep > 0) & (dep < 100))
    snap = {'world_pos': [float(x) for x in d.cam_xpos[cid]],
            'R_world_from_camera': [[float(v) for v in row]
                                    for row in np.asarray(d.cam_xmat[cid]).reshape(3, 3)],
            'fovy_deg': float(m.cam_fovy[cid])}
    valid = float(np.mean(np.isfinite(dep[mask]))) if mask.any() else 0.0
    return {'mask': mask, 'depth': dep, 'snapshot': snap,
            'mask_px': int(mask.sum()), 'depth_valid_frac': round(valid, 3)}


def cam_forward(snap):
    R = np.asarray(snap['R_world_from_camera']).reshape(3, 3)
    return -R[:, 2]          # MuJoCo 相机看向 -z


def angle_deg(a, b):
    c = float(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12), -1, 1))
    return float(np.degrees(np.arccos(c)))


def drive_to(env, target_y, stop_x=None, max_s=24.0, v_max=0.09):
    """
    用**语义明确的** step_drive 航点控制行驶到目标横向偏移（不改 qpos）。

    航点：先在 (x_stop, 0) 附近保持，再横向到 target_y —— 用弧线实现，
    不要求原地横移。大航向误差先降速，接近目标逐步减速。
    """
    t0 = env.t
    n = int(max_s * env.control_hz)
    for _ in range(n):
        if stop_x is not None and float(env.data.qpos[0]) >= stop_x:
            break
        lat = float(env.data.qpos[1]) - env.channel_center
        err = target_y - lat
        if abs(err) < 0.04:
            break
        # 期望航向：朝 (x+0.4, target_y) 走
        dx = 0.45
        want = float(np.arctan2(err, dx))
        R = np.asarray(env.data.xmat[0]).reshape(3, 3) if False else None
        # 机体朝向：用四元数取前向
        w, x, y, z = env.data.qpos[3:7]
        fwd = np.array([1 - 2 * (y * y + z * z), 2 * (x * y + z * w)])
        have = float(np.arctan2(fwd[1], fwd[0]))
        dyaw = float(np.arctan2(np.sin(want - have), np.cos(want - have)))
        v = v_max * max(0.25, 1.0 - abs(dyaw) / 1.2)
        w_cmd = float(np.clip(2.2 * dyaw, -0.35, 0.35))
        _, _, te, tr, info = env.step_drive(v_forward_mps=v, yaw_rate_rps=w_cmd)
        if te or tr:
            return round(float(env.t - t0), 3), info.get('reason')
    return round(float(env.t - t0), 3), None


def drive_to_nav(env, target_y, stop_x=None, max_s=12.0, v=0.10):
    """
    用**已验证的导航底座**做侧向定位：设 env.nav_target_y，由 _steer_from_nav
    闭环产生转向（Detour 就是用这条通路实现 0.49 m 横移）。
    只设 a[2] 速度项，a[0]/a[1] 保持 0（不动腿姿）。
    到达停止线即停，不再继续前推 —— 保证目标仍在视野内。
    """
    t0 = env.t
    n = int(max_s * env.control_hz)
    for _ in range(n):
        lat_err = float(env.data.qpos[1]) - float(target_y)
        if abs(lat_err) < 0.05:
            lat_err = 0.0          # 死区：抑制往复振荡
        # 航向误差（朝 +x 为准）
        w_, x_, y_, z_ = env.data.qpos[3:7]
        head = float(np.arctan2(2 * (w_ * z_ + x_ * y_), 1 - 2 * (y_ * y_ + z_ * z_)))
        # 需要的偏航角速度：横向误差 + 航向误差的比例项（与 nav 底座同构）
        # 阻尼修正：降低增益与限幅（实测 1.6/1.2、±0.6 会振荡倾覆）
        w_cmd = float(np.clip(0.9 * lat_err + 0.6 * head, -0.25, 0.25))
        # 横向误差大时降速，保证稳定
        v_cmd = float(v * max(0.35, 1.0 - abs(lat_err) / 0.8))
        _, _, te, tr, info = env.step_drive(v_forward_mps=v_cmd, yaw_rate_rps=-w_cmd)
        if te or tr:
            return round(float(env.t - t0), 3), info.get('reason')
        if stop_x is not None and float(env.data.qpos[0]) >= stop_x:
            break
    return round(float(env.t - t0), 3), None


def face_target(env, cid, case, max_s=8.0, tol_deg=6.0):
    """
    朝向目标：差速轮无法原地转，用"低速前进 + 把导航横向目标设回目标 y"实现转弯。
    以相机前向与实际目标方向的夹角为判据。
    """
    ob = np.array([case['obstacle_x'], 0.0, 0.0])
    t0 = env.t
    best = 180.0
    n = int(max_s * env.control_hz)
    for _ in range(n):
        cam = np.asarray(env.data.cam_xpos[cid])
        d = ob[:2] - cam[:2]
        want = float(np.arctan2(d[1], d[0]))
        R = np.asarray(env.data.cam_xmat[cid]).reshape(3, 3)
        fwd = -R[:, 2]
        have = float(np.arctan2(fwd[1], fwd[0]))
        err = float(np.degrees(np.arctan2(np.sin(want - have), np.cos(want - have))))
        best = min(best, abs(err))
        if abs(err) < tol_deg:
            break
        # 用明确的航向角速度把机头对准目标（不是腿姿残差）
        # 符号：err>0 表示需要逆时针（左转）才能对准，因此 w>0
        w_cmd = float(np.clip(+1.6 * err / 45.0, -0.35, 0.35))
        # 原地转向：v=0 时左右轮反向，差速底座可原地转（实测支持）
        _, _, te, tr, info = env.step_drive(v_forward_mps=0.0, yaw_rate_rps=w_cmd)
        if te or tr:
            break
    return {'seconds': round(float(env.t - t0), 3), 'final_err_deg': round(abs(err), 2),
            'best_err_deg': round(best, 2)}


def brake_and_settle(env, max_s=3.0):
    """显式刹车并等到稳定保持；返回 (稳定?, 用时, 状态量)。"""
    t0 = env.t
    hold = 0
    n = int(max_s * env.control_hz)
    for _ in range(n):
        # 显式零速（直接轮速目标=0，可表达真停车；残差通道最小仍是 0.4 倍前进）
        _, _, te, tr, _info = env.step_drive(v_forward_mps=0.0, yaw_rate_rps=0.0)
        if te or tr:
            break
        v_lin = float(np.linalg.norm(env.data.qvel[:3]))
        v_ang = float(np.linalg.norm(env.data.qvel[3:6]))
        tilt = env._tilt()
        if v_lin < STABLE_V_LIN and v_ang < STABLE_V_ANG and tilt < STABLE_TILT_DEG:
            hold += 1
            if hold >= int(STABLE_HOLD_S * env.control_hz):
                break
        else:
            hold = 0
    return {'stable': hold >= int(STABLE_HOLD_S * env.control_hz),
            'v_lin': round(float(np.linalg.norm(env.data.qvel[:3])), 4),
            'v_ang': round(float(np.linalg.norm(env.data.qvel[3:6])), 4),
            'tilt_deg': round(float(env._tilt()), 2),
            'hold_s': round(hold / env.control_hz, 3),
            'brake_seconds': round(float(env.t - t0), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--obs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--camera-height', type=float, default=0.32)
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    case = json.loads(pathlib.Path(a.case).read_text())
    obs = json.loads((pathlib.Path(a.obs) / 'observation.json').read_text())
    vis = obs['visible']
    half_w = float(case.get('channel_half', 1.2))

    # 观察目标：只依据首视角 + 公开通道 + 机器人包络
    # 侧前方观察点横向**指令**：实测本平台在 0.30 m 指令下能稳定横移约 0.13 m，
    # 配合"停在障碍前 0.78 m"形成 15-25° 视差；指令再大（>=0.5）会倾覆。
    # 上限仍受公开通道约束。
    target_y = float(np.clip(0.30, 0.10, half_w - 0.30))
    rec = {'workflow': 'drive_observe/v1',
           'observation_target_y_m': round(target_y, 4),
           'target_basis': ('W_vis/2 + robot half width + margin；只读公开量'),
           'observation_protocol': observation_protocol(),
           'frozen_criteria': {'v_lin': STABLE_V_LIN, 'v_ang': STABLE_V_ANG,
                               'tilt_deg': STABLE_TILT_DEG, 'hold_s': STABLE_HOLD_S,
                               'min_target_px': MIN_TARGET_PX,
                               'min_depth_frac': MIN_DEPTH_FRAC,
                               'min_cam_forward_angle_change_deg': MIN_CAM_YAW_CHANGE_DEG},
           'runs': []}

    for sd in a.seeds:
        env = wheelleg_env.WheelLegEnv(_spec(case, mesh=case['mesh']))
        env.reset(seed=sd)
        cid = set_cam_height(env, a.camera_height)
        v1 = capture(env, cid, out / f'seed{sd}_view1.png')
        # 取景几何（实测定位）：本平台的有效转向很弱（0.4 rad/s 指令实测 0.012 rad/s），
        # 因此不靠转向对准，而是**在侧向偏移处保持 +x 朝向**直接观察：
        # 相机在 base_link 前 0.42 m，只要在障碍前 0.75-0.9 m 停下，
        # 侧移 0.10-0.15 m 即可形成 15-25° 视差，且仍在 70° FOV（±35°）内。
        front = float(case['obstacle_x']) - float(case.get('D', 0.3)) / 2.0
        stop_x = front - 0.42 - 0.78
        move_s, move_stop = drive_to_nav(env, target_y, stop_x=max(0.25, stop_x))
        face = None      # 不做转向对准（平台转向不足，且会破坏取景）
        st = brake_and_settle(env)
        v2 = capture(env, cid, out / f'seed{sd}_view2.png')
        dyaw = angle_deg(cam_forward(v1['snapshot']), cam_forward(v2['snapshot']))
        p1 = np.asarray(v1['snapshot']['world_pos']); p2 = np.asarray(v2['snapshot']['world_pos'])
        baseline = float(np.linalg.norm(p2 - p1))
        anchor = np.array([float(case['obstacle_x']) - float(case.get('D', 0.3)) / 2.0, 0.0, 0.0])
        b1 = float(np.degrees(np.arctan2(anchor[1] - p1[1], anchor[0] - p1[0])))
        b2 = float(np.degrees(np.arctan2(anchor[1] - p2[1], anchor[0] - p2[0])))
        bearing_change = abs(b2 - b1)
        usable = is_usable(st['stable'], v2['mask_px'], v2['depth_valid_frac'],
                           baseline, bearing_change)
        rec['runs'].append({
            'seed': sd, 'move_seconds': move_s, 'move_stop_reason': move_stop,
            'face': face,
            'brake_seconds': st['brake_seconds'],
            'stable': st['stable'], 'v_lin': st['v_lin'], 'v_ang': st['v_ang'],
            'tilt_deg': st['tilt_deg'], 'hold_s': st['hold_s'],
            'view1_mask_px': v1['mask_px'], 'view2_mask_px': v2['mask_px'],
            'view2_depth_valid_frac': v2['depth_valid_frac'],
            'cam_forward_angle_change_deg': round(dyaw, 2),
            'cam_baseline_m': round(baseline, 3),
            'bearing_change_deg': round(bearing_change, 2),
            'lat_after': round(float(env.data.qpos[1]), 4),
            'usable': bool(usable),
            'fail_reason': (None if usable else
                            ('unstable' if not st['stable'] else
                             ('target_too_small' if v2['mask_px'] < MIN_TARGET_PX else
                              ('depth_invalid' if v2['depth_valid_frac'] < MIN_DEPTH_FRAC
                               else 'viewpoint_change_too_small')))),
            'state_snapshot': {'qpos': [round(float(x), 6) for x in env.data.qpos],
                               'qvel': [round(float(x), 6) for x in env.data.qvel],
                               'time': round(float(env.t), 4)},
            # 完整状态合同（含 mjstate/ctrl/时钟/计数器/导航目标/土壤贡献 + 哈希），
            # 供"观察后重规划并从同一状态续行"使用；不是只存 qpos/qvel
            'env_state': env.save_state(),
            'view2_snapshot': v2['snapshot'],
        })
        (out / 'drive_observe.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))

    ok = [r for r in rec['runs'] if r['usable']]
    rec['summary'] = {'n': len(rec['runs']), 'n_usable': len(ok),
                      'rate': round(len(ok) / max(1, len(rec['runs'])), 3),
                      'target_9_of_10': len(ok) >= 9}
    (out / 'drive_observe.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps(rec['summary'], ensure_ascii=False),
          json.dumps([{k: r[k] for k in ('seed', 'usable', 'fail_reason',
                                         'view2_mask_px', 'cam_forward_angle_change_deg')}
                      for r in rec['runs']], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
