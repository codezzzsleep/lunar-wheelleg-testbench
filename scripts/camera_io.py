"""
相机快照与恢复：observe / align / calibrate 共用同一份实现。

约定（列向量）：
    p_world = R_world_from_camera @ p_camera + t_world_from_camera
    p_camera = R_world_from_camera.T @ (p_world - t_world_from_camera)
MuJoCo 相机看向局部 -Z：
    depth_z = -p_camera[2]
    u = fx * p_camera[0] / depth_z + cx
    v = cy - fy * p_camera[1] / depth_z        # 图像 v 向下

schema: camera-snapshot/v2
"""
import numpy as np
import mujoco

SCHEMA = 'camera-snapshot/v2'


def intrinsics(W, H, fovy_deg):
    fy = (H / 2.0) / np.tan(np.deg2rad(fovy_deg) / 2.0)
    return {'fx': float(fy), 'fy': float(fy),
            'cx': (W - 1) / 2.0, 'cy': (H - 1) / 2.0,
            'width': int(W), 'height': int(H)}


def orthonormalize(R):
    """把可能因四舍五入而不正交的旋转投影到最近的 SO(3)，返回 (R_fix, 修正量)。"""
    U, _, Vt = np.linalg.svd(np.asarray(R, dtype=np.float64))
    Rn = U @ Vt
    if np.linalg.det(Rn) < 0:
        U[:, -1] *= -1
        Rn = U @ Vt
    delta = float(np.max(np.abs(Rn - np.asarray(R))))
    return Rn, delta


def capture(model, data, cid, W, H):
    """在最终 mj_forward 之后调用，保存**实际**相机状态（完整精度）。"""
    mujoco.mj_forward(model, data)
    body_id = int(model.cam_bodyid[cid])
    return {
        'camera_schema': SCHEMA,
        'body_name': mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id) or '',
        'body_id': body_id,
        'local_pos': [float(x) for x in model.cam_pos[cid]],
        'local_quat_wxyz': [float(x) for x in model.cam_quat[cid]],
        'world_pos': [float(x) for x in data.cam_xpos[cid]],
        'R_world_from_camera': [[float(v) for v in row]
                                for row in np.asarray(data.cam_xmat[cid]).reshape(3, 3)],
        'fovy_deg': float(model.cam_fovy[cid]),
        'image_width': int(W), 'image_height': int(H),
        'intrinsics': intrinsics(W, H, float(model.cam_fovy[cid])),
        'robot_qpos': [float(x) for x in data.qpos],
        'robot_qvel': [float(x) for x in data.qvel],
        'depth_convention': 'positive_camera_minus_z',
    }


def restore(model, data, cid, snap, expect_tol=1e-6):
    """
    把相机恢复到快照的世界位姿（挂在当前 body 上）。
    恢复后立即比较 cam_xpos / cam_xmat，超差直接报错，不继续评估。
    """
    R_wc = np.asarray(snap['R_world_from_camera'], dtype=np.float64).reshape(3, 3)
    R_wc, _ = orthonormalize(R_wc)
    t_wc = np.asarray(snap['world_pos'], dtype=np.float64)

    body_id = int(model.cam_bodyid[cid])
    B = np.asarray(data.xmat[body_id], dtype=np.float64).reshape(3, 3)
    b = np.asarray(data.xpos[body_id], dtype=np.float64)

    model.cam_pos[cid] = B.T @ (t_wc - b)
    R_local = B.T @ R_wc
    quat = np.empty(4)
    mujoco.mju_mat2Quat(quat, np.ascontiguousarray(R_local).reshape(9))
    model.cam_quat[cid] = quat
    model.cam_fovy[cid] = float(snap['fovy_deg'])
    mujoco.mj_forward(model, data)

    dpos = float(np.max(np.abs(np.asarray(data.cam_xpos[cid]) - t_wc)))
    R_now = np.asarray(data.cam_xmat[cid]).reshape(3, 3)
    drot = float(np.max(np.abs(R_now - R_wc)))
    if dpos > expect_tol or drot > expect_tol:
        raise RuntimeError(
            f'相机恢复失败：位置差 {dpos:.3e} m、旋转差 {drot:.3e}（容差 {expect_tol:g}）')
    return {'pos_err': dpos, 'rot_err': drot,
            'local_pos': [float(x) for x in model.cam_pos[cid]]}


def install_local_z_for_world_height(model, data, cid, desired_world_z,
                                     local_x=0.42, local_y=0.0):
    """
    --cam-height 表示**世界离地高度**：反解 local z，使相机世界 z 等于目标。
    机身有俯仰时按机体 z 轴投影计算；近奇异姿态明确报错。
    """
    body_id = int(model.cam_bodyid[cid])
    mujoco.mj_forward(model, data)
    B = np.asarray(data.xmat[body_id], dtype=np.float64).reshape(3, 3)
    b = np.asarray(data.xpos[body_id], dtype=np.float64)
    denom = B[2, 2]
    if abs(denom) < 1e-6:
        raise RuntimeError(f'机体 z 轴接近水平（B[2,2]={denom:.2e}），无法按高度放置相机')
    local_z = (float(desired_world_z) - b[2] - B[2, 0] * local_x - B[2, 1] * local_y) / denom
    model.cam_pos[cid] = [float(local_x), float(local_y), float(local_z)]
    mujoco.mj_forward(model, data)
    return float(data.cam_xpos[cid][2])


def project(points_world, snap):
    """世界点 -> 像素 (u, v) 与深度；不可见返回 nan。"""
    K = snap['intrinsics']
    R = np.asarray(snap['R_world_from_camera'], dtype=np.float64).reshape(3, 3)
    t = np.asarray(snap['world_pos'], dtype=np.float64)
    p = (np.asarray(points_world, dtype=np.float64) - t) @ R      # 行向量等价写法
    depth = -p[:, 2]
    ok = depth > 1e-6
    u = np.full(len(p), np.nan)
    v = np.full(len(p), np.nan)
    u[ok] = K['fx'] * p[ok, 0] / depth[ok] + K['cx']
    v[ok] = K['cy'] - K['fy'] * p[ok, 1] / depth[ok]
    return u, v, depth


def unproject_depth(depth, snap):
    """渲染深度图 -> 世界点云（与 observe 同一条链）。"""
    K = snap['intrinsics']
    R = np.asarray(snap['R_world_from_camera'], dtype=np.float64).reshape(3, 3)
    t = np.asarray(snap['world_pos'], dtype=np.float64)
    H, W = depth.shape
    ys, xs = np.nonzero(np.isfinite(depth) & (depth > 0) & (depth < 100.0))
    z = depth[ys, xs]
    pc = np.stack([(xs - K['cx']) * z / K['fx'],
                   -(ys - K['cy']) * z / K['fy'],
                   -z], axis=1)
    return pc @ R.T + t, ys, xs
