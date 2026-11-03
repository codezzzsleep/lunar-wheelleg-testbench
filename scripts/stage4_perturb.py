"""Stage004：按冻结扰动修改完整初始快照，并同步重算 state_hash。"""
import hashlib
import json
import numpy as np


def _compute_hash(rec):
    h = hashlib.sha256()
    h.update(np.asarray(rec['mjstate'], dtype=np.float64).tobytes())
    h.update(np.asarray([rec['data_time'], rec['env_t'],
                         rec['t_last_zero_cmd']], dtype=np.float64).tobytes())
    h.update(np.asarray(rec['prev_action'], dtype=np.float64).tobytes())
    h.update(np.asarray([rec['prev_x'], rec['nav_target_y'],
                         rec['n_physics'], rec['n_control'],
                         rec['contact_steps'], rec['wheel_contact_steps']],
                        dtype=np.float64).tobytes())
    if rec.get('soil'):
        h.update(json.dumps(rec['soil'], sort_keys=True).encode())
    if rec.get('command') is not None:
        h.update(json.dumps(rec['command'], sort_keys=True).encode())
    h.update(repr((rec['data_time'], rec['env_t'], rec['n_physics'],
                   rec.get('n_control', 0))).encode())
    return h.hexdigest()[:32]


def perturb_snapshot(snapshot, dx=0.0, dy=0.0, dyaw_deg=0.0):
    rec = json.loads(json.dumps(snapshot))
    nq = int(rec['nq'])
    st = np.asarray(rec['mjstate'], dtype=np.float64).copy()
    q = st[:nq].copy()
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
    st[:nq] = q
    rec['mjstate'] = st.tolist()
    rec['state_hash'] = _compute_hash(rec)
    return rec
