"""Stage004：通过环境恢复入口读真实 qpos，施加冻结扰动后用 save_state 重新取快照。

不改 mjstate 字节，不手算 qpos 偏移；state_hash 由 save_state 生成，
决策里的 state_hash 必须引用这个实际执行快照。
"""
import numpy as np
import mujoco

import v3_core


def env_perturb_snapshot(core, proto, dx=0.0, dy=0.0, dyaw_deg=0.0):
    env = v3_core.make_env(core['spec'], proto)
    env.restore_state(core['snapshot'], mode='same_scene')
    q = np.array(env.data.qpos, dtype=np.float64, copy=True)
    q[0] += float(dx)
    q[1] += float(dy)
    if abs(dyaw_deg) > 1e-9:
        th = np.deg2rad(float(dyaw_deg))
        c, s = np.cos(th / 2), np.sin(th / 2)
        w, x, y, z = (float(v) for v in q[3:7])
        q[3] = c * w - s * z
        q[4] = c * x + s * y
        q[5] = c * y - s * x
        q[6] = c * z + s * w
    env.data.qpos[:] = q
    mujoco.mj_forward(env.model, env.data)
    snap = env.save_state()
    qn = np.asarray(env.data.qpos, dtype=np.float64)
    qv = np.asarray(env.data.qvel, dtype=np.float64)
    w, x, y, z = (float(v) for v in qn[3:7])
    yaw = float(np.degrees(np.arctan2(2.0 * (w * z + x * y),
                                      1.0 - 2.0 * (y * y + z * z))))
    diag = {'x': round(float(qn[0]), 6), 'y': round(float(qn[1]), 6),
            'z': round(float(qn[2]), 6), 'yaw_deg': round(yaw, 4),
            'qvel_base': [round(float(v), 6) for v in qv[:6]],
            'clock_s': round(float(env.t), 4),
            'snapshot_state_hash': snap.get('state_hash'),
            'requested': {'dx': dx, 'dy': dy, 'dyaw_deg': dyaw_deg}}
    return snap, diag
