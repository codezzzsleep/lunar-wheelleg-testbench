"""C 包五条件隔离：同一状态、固定 L2，只改"物理真值/碰撞表示/恢复模式"。

C3 的五臂（全部 project，除 A 用 same_scene）：
  A truth_mesh_same_scene   完整物理真值（mesh geom，MuJoCo 凸包碰撞），同场景恢复
  B truth_mesh_project      同一物理真值，project 恢复
  C truth_fine_project      同一完整真值源占据，细盒表示（truth/coll，6.08 mm）
  D truth_coarse_project    同一源占据，部署粗盒表示（downsample=2，12.17 mm）
  E tparent_fine_project    生产融合 T-as-parent，细盒（tparent/coll）

C1：恢复后的状态在 restore 完成、第一条控制命令之前采样（pre_step_hook），
     不再用创建 env 时的采样冒充 S0。
C2：读取编译后的模型 geom，记录物理真值到底用何种接触表示。
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core            # noqa: E402


def sha_bytes(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def full_snapshot(env, restore_info):
    """restore 之后、第一条命令之前的完整状态（C1 正确采样点）。"""
    import mujoco
    d, m = env.data, env.model
    qpos = np.asarray(d.qpos, dtype=np.float64).copy()
    qvel = np.asarray(d.qvel, dtype=np.float64).copy()
    ctrl = np.asarray(d.ctrl, dtype=np.float64).copy()
    xfrc = np.asarray(d.xfrc_applied, dtype=np.float64).ravel().copy()
    warm = np.asarray(d.qacc_warmstart, dtype=np.float64).ravel().copy()
    fr = np.asarray(m.geom_friction, dtype=np.float64).ravel().copy()
    soil = getattr(env, '_soil_prev_force', {}) or {}
    soil_concat = np.concatenate([np.asarray(v, dtype=np.float64).ravel()
                                  for _, v in sorted(soil.items())]) if soil else np.zeros(0)
    loads = {}
    for leg in ('FR', 'FL', 'RR', 'RL'):
        b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_wheel_link')
        s = 0.0
        for i in range(int(d.ncon)):
            c = d.contact[i]
            b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
            if b in (b1, b2):
                f = np.zeros(6)
                mujoco.mj_contactForce(m, d, i, f)
                s += abs(float(f[0]))
        loads[leg] = round(s, 4)
    digest = sha_bytes(np.concatenate([qpos, qvel, ctrl, xfrc, warm, soil_concat]))
    return {
        'restore_mode': restore_info.get('mode'),
        'state_schema': restore_info.get('state_schema'),
        'qpos': [round(float(x), 6) for x in qpos],
        'qvel': [round(float(x), 6) for x in qvel],
        'qpos_sha256': sha_bytes(qpos), 'qvel_sha256': sha_bytes(qvel),
        'ctrl_sha256': sha_bytes(ctrl), 'xfrc_sha256': sha_bytes(xfrc),
        'warmstart_sha256': sha_bytes(warm),
        'friction_sha256': sha_bytes(fr),
        'soil_prev_force_sha256': sha_bytes(soil_concat),
        'full_sha256': digest,
        'data_time': round(float(d.time), 6), 'env_t': round(float(env.t), 6),
        'n_physics': int(env.n_physics), 'n_control': int(env.n_control),
        'wheel_loads_n': loads,
        'ncon': int(d.ncon),
        'scene_signature': restore_info.get('source_scene_sha'),
        'state_mode': restore_info.get('mode'),
    }


def representation(env):
    """C2：编译后模型里物体几何的接触表示。"""
    import mujoco
    m = env.model
    obj = []
    for i in range(m.ngeom):
        t = int(m.geom_type[i])
        if t == int(mujoco.mjtGeom.mjGEOM_MESH):
            obj.append({'geom': i, 'type': 'mesh', 'dataid': int(m.geom_dataid[i]),
                        'size': [round(float(x), 5) for x in m.geom_size[i]]})
    return {'ngeom': int(m.ngeom), 'n_mesh_geoms': len(obj), 'mesh_geoms': obj,
            'note': 'mesh geom 在 MuJoCo 里按凸包参与接触；凹扫描件不等价于凹网格接触。'}


def run_arm(spec, st, proto, mode):
    env = v3_core.make_env(spec, proto)
    cap = {}

    def hook(e, info):
        cap['after_restore'] = full_snapshot(e, info)

    r = v3_core.run_action(env, st['snapshot'], 'L2', st['visible'], mode=mode,
                           seed=0, record=True, pre_step_hook=hook)
    after = cap.get('after_restore') or {}
    traj = [np.asarray(f['qpos'], dtype=np.float64) for f in (r.get('trajectory') or [])]
    out = {'outcome': r.get('outcome'), 'reason': r.get('reason'),
           'final_x': r.get('final_x'), 'steps': len(traj),
           'after_restore': after, 'ncon_start': after.get('ncon'),
           'wheel_loads_start': after.get('wheel_loads_n')}
    rep = representation(env)
    del env
    return out, traj, rep


def first_div(a, b, tol=1e-6):
    n = min(len(a), len(b))
    for i in range(n):
        d = float(np.max(np.abs(a[i] - b[i])))
        if d > tol:
            return i, d
    return (None if len(a) == len(b) else n), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default='runs/v3/states/moon_rock_04_h1v0')
    ap.add_argument('--out', default='runs/v3/isolation5')
    ap.add_argument('--action', default='L2')
    ap.add_argument('--repeat', type=int, default=1)
    a = ap.parse_args()
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    sd = ROOT / a.state
    st = v3_core.load_state(sd)
    truth = v3_core.truth_spec(st)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    # D：与 C 同一源占据（truth/coll/_occ_ds.npz），只把降采样从 1 改成 2
    truth_coll = sd / 'truth' / 'coll'
    man = json.loads((truth_coll / 'manifest.json').read_text())
    src_pitch = float(man.get('pitch_m') or 0.0)
    coarse = v3_core.build_collision(truth_coll / '_occ_ds.npz', out / 'coll_truth_ds2',
                                     pitch=src_pitch, downsample=2, force=True)
    if not coarse.get('ok'):
        raise SystemExit(f'粗盒构建失败：{coarse.get("error")}')

    arms = {
        'A_truth_mesh_same_scene': (truth, 'same_scene'),
        'B_truth_mesh_project': (truth, 'project'),
        'C_truth_fine_project': (v3_core.spec_with_geometry(truth, truth_coll), 'project'),
        'D_truth_coarse_project': (v3_core.spec_with_geometry(
            truth, out / 'coll_truth_ds2'), 'project'),
        'E_tparent_fine_project': (v3_core.spec_with_geometry(
            truth, sd / 'tparent' / 'coll'), 'project'),
    }
    res, trajs, reps, repeats = {}, {}, {}, {}
    for name, (spec, mode) in arms.items():
        rr = [run_arm(spec, st, proto, mode) for _ in range(a.repeat)]
        r, t, rep = rr[0]
        res[name] = r
        trajs[name] = t
        reps[name] = rep
        repeats[name] = {'runs': [{'outcome': x[0]['outcome'],
                                   'final_x': x[0]['final_x'],
                                   'steps': x[0]['steps']} for x in rr],
                         'deterministic': all(x[0]['outcome'] == r['outcome']
                                              and x[0]['final_x'] == r['final_x']
                                              for x in rr)}

    names = list(arms)
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            idx, mag = first_div(trajs[names[i]], trajs[names[j]])
            pairs.append({'a': names[i], 'b': names[j], 'first_divergence_step': idx,
                          'max_abs_qpos_diff_at_div': mag,
                          'outcome_a': res[names[i]]['outcome'],
                          'outcome_b': res[names[j]]['outcome']})

    # C1：A/B 恢复后状态对比（同真值，只差恢复模式）
    sa = res['A_truth_mesh_same_scene']['after_restore']
    sb = res['B_truth_mesh_project']['after_restore']
    restore_cmp = {k: (sa.get(k) == sb.get(k))
                   for k in ('qpos_sha256', 'qvel_sha256', 'ctrl_sha256',
                             'xfrc_sha256', 'warmstart_sha256', 'friction_sha256',
                             'soil_prev_force_sha256', 'data_time', 'env_t',
                             'n_physics', 'n_control')}
    restore_cmp['both_sampled_after_restore'] = bool(sa and sb)

    payload = {
        'schema': 'v3-isolation5/v2', 'repeat': a.repeat,
        'repeats': repeats,
        'state': a.state, 'action': a.action,
        'arms': res, 'pairs': pairs,
        'c1_restore_compare': restore_cmp,
        'c2_representation': {k: v for k, v in reps.items()},
        'c3_build': {'truth_fine_pitch_m': src_pitch, 'coarse': coarse},
        'env_before_note': 'after_restore 是 restore 完成、第一条控制命令之前的采样',
    }
    (out / 'result.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    for name, t in trajs.items():
        if t:
            np.save(out / f'qpos_{name}.npy', np.asarray(t))
    print(json.dumps({
        'arms': {k: {'outcome': v['outcome'], 'final_x': v['final_x'],
                     'steps': v['steps'], 'ncon0': v['ncon_start']}
                 for k, v in res.items()},
        'restore_cmp': restore_cmp,
        'repeats': {k: v['deterministic'] for k, v in repeats.items()},
        'pairs': [{k: p[k] for k in ('a', 'b', 'first_divergence_step',
                                     'outcome_a', 'outcome_b')} for p in pairs],
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
