"""五臂隔离：同一状态、固定 L2，只改"几何来源 / 恢复模式"，找首次分叉。

臂：
  1 truth_mesh / same_scene      （真值执行）
  2 truth_mesh / project         （同几何，换恢复模式）
  3 T_boxes    / project         （完美几何 + 盒碰撞）
  4 A1_boxes   / project         （真实候选 A1）
  5 obs_boxes  / project         （仅观测 V 的碰撞）
产出：每臂逐步 qpos 轨迹、两两首次分叉步与幅值、环境差异（外力/土壤/warmstart）。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core


def env_snapshot(env):
    import mujoco
    d, m = env.data, env.model
    return {'ngeom': int(m.ngeom), 'nq': int(m.nq), 'nv': int(m.nv),
            'xfrc_nonzero': int(np.count_nonzero(d.xfrc_applied)),
            'ctrl_nonzero': int(np.count_nonzero(d.ctrl)),
            'qacc_warmstart_norm': round(float(np.linalg.norm(d.qacc_warmstart)), 6),
            'soil_mode': getattr(env, 'soil_mode', None),
            'soil_limits': bool(getattr(env, '_soil_limits', {})),
            'soil_prev_force_n': len(getattr(env, '_soil_prev_force', {}) or {}),
            'time': round(float(d.time), 4), 'env_t': round(float(env.t), 4)}


def run_arm(spec, st, proto, mode):
    env = v3_core.make_env(spec, proto)
    before = env_snapshot(env)
    r = v3_core.run_action(env, st['snapshot'], 'L2', st['visible'], mode=mode,
                           seed=0, record=True)
    after = env_snapshot(env)
    traj = [np.asarray(f['qpos'], dtype=np.float64) for f in (r.get('trajectory') or [])]
    out = {'outcome': r.get('outcome'), 'reason': r.get('reason'),
           'final_x': r.get('final_x'), 'steps': len(traj),
           'env_before': before, 'env_after': after}
    del env
    return out, traj


def first_div(a, b, tol=1e-6):
    n = min(len(a), len(b))
    for i in range(n):
        d = float(np.max(np.abs(a[i] - b[i])))
        if d > tol:
            return i, d
    return (None if len(a) == len(b) else n), float(np.max(np.abs(a[-1] - b[-1]))) if n else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default='runs/v3/states/moon_rock_04_h1v0')
    ap.add_argument('--out', default='runs/v3/isolation5')
    a = ap.parse_args()
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    sd = ROOT / a.state
    st = v3_core.load_state(sd)
    truth = v3_core.truth_spec(st)
    arms = {
        'truth_mesh_same_scene': (truth, 'same_scene'),
        'truth_mesh_project': (truth, 'project'),
        'T_boxes_project': (v3_core.spec_with_geometry(truth, sd / 'tparent' / 'coll'), 'project'),
        'A1_boxes_project': (v3_core.spec_with_geometry(truth, sd / 'candidates' / 'A1' / 'coll'), 'project'),
        'obs_boxes_project': (v3_core.spec_with_geometry(truth, sd / 'obs_only' / 'coll'), 'project'),
    }
    res, trajs = {}, {}
    for name, (spec, mode) in arms.items():
        r, t = run_arm(spec, st, proto, mode)
        res[name] = r
        trajs[name] = t
    names = list(arms)
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            idx, mag = first_div(trajs[names[i]], trajs[names[j]])
            pairs.append({'a': names[i], 'b': names[j], 'first_divergence_step': idx,
                          'max_abs_qpos_diff_at_div': mag,
                          'outcome_a': res[names[i]]['outcome'],
                          'outcome_b': res[names[j]]['outcome']})
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').write_text(json.dumps(
        {'schema': 'v3-isolation5/v1', 'state': a.state, 'action': 'L2',
         'arms': res, 'pairs': pairs}, ensure_ascii=False, indent=2))
    for name, t in trajs.items():
        if t:
            np.save(out / f'qpos_{name}.npy', np.asarray(t))
    print(json.dumps({'arms': {k: {'outcome': v['outcome'], 'final_x': v['final_x'],
                                   'steps': v['steps'],
                                   'xfrc': v['env_before']['xfrc_nonzero'],
                                   'soil_limits': v['env_before']['soil_limits'],
                                   'warm': v['env_before']['qacc_warmstart_norm']}
                              for k, v in res.items()},
                      'pairs': [{k: p[k] for k in ('a', 'b', 'first_divergence_step',
                                                   'outcome_a', 'outcome_b')} for p in pairs]},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
