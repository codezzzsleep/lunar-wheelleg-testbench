"""≥50 Hz 全状态轨迹记录（数组单独持久化，矩阵只引用）。

设计（SPEC §5）：
  * 每个真实执行、每个实际预演格都记录；控制频率 >= 50 Hz（本环境 50 Hz）。
  * 分块压缩数组：<dir>/chunk_00000.npz（数值）+ contacts_00000.jsonl（稀疏接触）；
    每块写完立刻写 SHA；关闭时写 index.json（字段名/单位/顺序、块清单、总帧数、
    record_hz、trajectory_sha256）。
  * 数值向量一律附 names/units，不用下标暗示语义。
  * 未实现的量写 unavailable（不拿公式估计冒充实测）。
  * 轨迹先写临时片段，再原子封卷；中断可从上一次完整块恢复（remaining 记录）。

  rec = Recorder(dir, meta, hz=50)
  rec.add(frame)          # 每控制步一次
  ref = rec.close()       # -> {trajectory_path, trajectory_sha256, frame_count, record_hz, ...}
"""
import hashlib
import json
import pathlib
import time

import numpy as np

SCHEMA = 'v3-trajectory/v2'
CHUNK_FRAMES = 250

FIELDS = {
    't': 's',
    'control_index': '1',
    'physics_index': '1',
    'qpos': 'm / rad (MuJoCo 顺序)',
    'qvel': 'm/s / rad/s (MuJoCo 顺序)',
    'action_raw': '控制器输出（归一化，含义见 action_names）',
    'joint_target': 'rad',
    'joint_vel_target': 'rad/s',
    'wheel_omega_target': 'rad/s',
    'wheel_brake': '0/1',
    'joint_torque': 'N*m (实际执行器)',
    'wheel_torque': 'N*m (实际执行器)',
    'nav_target_y': 'm (机体横向目标)',
    'tilt_deg': 'deg',
    'n_contact': '1',
}
JOINT_NAMES = [f'{leg}_{j}' for leg in ('FR', 'FL', 'RR', 'RL')
               for j in ('hip', 'thigh', 'calf')]
WHEEL_NAMES = ['FR', 'FL', 'RR', 'RL']


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _copy_frame(frame):
    """入队时深拷贝所有可变数组，避免后续仿真步改写已记录帧。"""
    import copy as _copy
    out = {}
    for k, v in frame.items():
        if isinstance(v, np.ndarray):
            out[k] = v.copy()
        elif k == 'contacts' and isinstance(v, list):
            out[k] = _copy.deepcopy(v)
        else:
            out[k] = v
    return out


class Recorder:
    def __init__(self, out_dir, meta, hz=50.0, chunk_frames=CHUNK_FRAMES):
        self.dir = pathlib.Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = dict(meta)
        self.hz = float(hz)
        self.chunk_frames = int(chunk_frames)
        self.buf = []
        self.chunks = []
        self.n_frames = 0
        self.n_contacts = 0
        self.started_at = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        self.closed = False
        self.unavailable = []

    def add(self, frame):
        if self.closed:
            raise RuntimeError('recorder already closed')
        self.buf.append(_copy_frame(frame))
        if len(self.buf) >= self.chunk_frames:
            self._flush()

    def _flush(self):
        if not self.buf:
            return
        idx = len(self.chunks)
        arr_path = self.dir / f'chunk_{idx:05d}.npz'
        con_path = self.dir / f'contacts_{idx:05d}.jsonl'
        keys = [k for k in FIELDS if k in self.buf[0]]
        arrays, contacts = {}, []
        for k in keys:
            vals = [f.get(k) for f in self.buf]
            if k in ('action_raw', 'qpos', 'qvel', 'joint_target', 'joint_vel_target',
                     'wheel_omega_target', 'wheel_brake', 'joint_torque', 'wheel_torque'):
                arrs = [None if v is None else np.asarray(v, dtype=np.float32)
                        for v in vals]
                shapes = {a.shape for a in arrs if a is not None}
                if len(shapes) == 1:
                    # None 段（如 coast 的轮目标）按同形状 NaN 填充，避免
                    # “有的帧 4 值、有的帧 1 个 NaN”被 numpy 判为 ragged。
                    fill = np.full(shapes.pop(), np.nan, np.float32)
                    arrays[k] = np.stack([fill if a is None else a for a in arrs])
                elif len(shapes) == 0:
                    arrays[k] = np.full((len(arrs), 1), np.nan, np.float32)
                else:
                    arrays[k] = np.asarray(arrs, dtype=object)
                    self.unavailable.append(k + ':ragged_shapes')
            else:
                arrays[k] = np.asarray([np.nan if v is None else v for v in vals],
                                       dtype=np.float64)
        for f in self.buf:
            contacts.extend(f.get('contacts') or [])
        np.savez_compressed(arr_path, **arrays)
        with con_path.open('w') as fh:
            for c in contacts:
                fh.write(json.dumps(c, ensure_ascii=False) + '\n')
        self.chunks.append({'chunk': idx, 'frames': len(self.buf),
                            'arrays': arr_path.name, 'arrays_sha256': sha256_file(arr_path),
                            'contacts': con_path.name,
                            'contacts_sha256': sha256_file(con_path),
                            'contacts_n': len(contacts),
                            't_first': self.buf[0].get('t'),
                            't_last': self.buf[-1].get('t')})
        self.n_frames += len(self.buf)
        self.n_contacts += len(contacts)
        self.buf = []

    def close(self):
        self._flush()
        self.closed = True
        index = {
            'schema': SCHEMA,
            'meta': self.meta,
            'record_hz': self.hz,
            'fields': FIELDS,
            'field_keys': sorted(FIELDS),
            'array_names': {'joint': JOINT_NAMES, 'wheel': WHEEL_NAMES,
                            'qpos': 'MuJoCo model.nq', 'qvel': 'MuJoCo model.nv'},
            'units_note': ('关节/轮的量都按关节名顺序；qpos/qvel 是 MuJoCo 原生顺序，'
                           '渲染与回放必须读同一模型'),
            'unavailable': sorted(set(self.unavailable)),
            'chunks': self.chunks,
            'frame_count': self.n_frames,
            'contacts_n': self.n_contacts,
            'started_at': self.started_at,
            'closed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'duration_s': ((self.chunks[-1]['t_last'] - self.chunks[0]['t_first'])
                           if self.chunks else None),
        }
        idx_path = self.dir / 'index.json'
        body = json.dumps(index, ensure_ascii=False, indent=2)
        tmp = idx_path.with_suffix('.json.tmp')
        tmp.write_text(body)
        tmp.replace(idx_path)
        digest = sha256_file(idx_path)
        (self.dir / 'index.sha256').write_text(digest + '\n')
        return {'trajectory_path': str(self.dir / 'index.json'),
                'trajectory_sha256': digest,
                'frame_count': self.n_frames,
                'record_hz': self.hz,
                'duration_s': index['duration_s'],
                'n_chunks': len(self.chunks),
                'contacts_n': self.n_contacts}


def frame_from_env(env, skill, action_raw, steps, t, extra=None):
    """从当前仿真状态取一帧；拿不到的量写 None 并登记 unavailable。"""
    import numpy as np
    d = env.data
    # 采样即拷贝：d.qpos/d.qvel/actuator_force 是 MuJoCo 的原地缓冲区，
    # 若只存 view，后续仿真步会改写已入队的帧（记录器缺陷）。
    f = {'t': float(t), 'control_index': int(steps),
         'physics_index': int(getattr(env, 'n_physics', 0)),
         'qpos': np.array(d.qpos, dtype=np.float64, copy=True),
         'qvel': np.array(d.qvel, dtype=np.float64, copy=True),
         'action_raw': np.array(action_raw, dtype=np.float64, copy=True).reshape(-1),
         'tilt_deg': float(env._tilt()),
         'nav_target_y': float(getattr(env, 'nav_target_y', np.nan)),
         'contacts': _contacts(env)}
    # 关节目标 / 轮目标：环境当前保存的最近一次控制（有则记，没有记 None）
    def _snap(v):
        return None if v is None else np.array(v, dtype=np.float64, copy=True)
    f['joint_target'] = _snap(getattr(env, '_last_joint_targets', None))
    f['joint_vel_target'] = _snap(getattr(env, '_last_joint_vel_targets', None))
    f['wheel_omega_target'] = _snap(getattr(env, '_last_wheel_omega', None))
    f['wheel_brake'] = _snap(getattr(env, '_last_wheel_brake', None))
    # 实际执行器力矩
    try:
        act = np.array(d.actuator_force, dtype=np.float64, copy=True)
        nw = 4
        f['wheel_torque'] = act[-nw:].copy() if act.size >= nw else None
        f['joint_torque'] = act[:-nw].copy() if act.size > nw else None
    except Exception:  # noqa: BLE001
        f['joint_torque'] = None
        f['wheel_torque'] = None
    if extra:
        f.update(extra)
    return f


def _contacts(env):
    import mujoco
    d, m = env.data, env.model
    out = []
    for i in range(int(d.ncon)):
        c = d.contact[i]
        force = np.zeros(6, dtype=np.float64)
        try:
            mujoco.mj_contactForce(m, d, i, force)
        except Exception:  # noqa: BLE001
            pass
        out.append({'i': i,
                    'geom1': int(c.geom1), 'geom2': int(c.geom2),
                    'dist': float(c.dist),
                    'pos': [round(float(x), 6) for x in c.pos],
                    'frame': [round(float(x), 6) for x in c.frame],
                    'normal_force': round(float(force[0]), 6),
                    'friction': None})
    out.append({'n_contact': int(d.ncon)})
    return out


def record_cell(out_dir, meta, frames, hz=50.0):
    """便利入口：一次性写入一组帧（用于已有列表/回放）。"""
    rec = Recorder(out_dir, meta, hz=hz)
    for f in frames:
        rec.add(f)
    return rec.close()
