"""
H5 接口 fixture 闭环：加载 → 预演 → 决策 → 共同真值执行 → 回放。

  MUJOCO_GL=osmesa .venv/bin/python scripts/h5_fixture_loop.py \
      --out runs/unseen/recovery_r3/h5_fixture

只用 source_kind=fixture 的已知几何验证接口与错误路径。
fixture 结果**不进入**真实生成效果表，也不能当作 Lux3D 收益证据。
"""
import argparse
import json
import pathlib
import shutil
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import wheelleg_env
import mujoco

ROOT = pathlib.Path(__file__).resolve().parent.parent
OPTIONS = ('R1', 'R2', 'L1', 'L2', 'A0')


def make_fixture_world(out_dir, width=0.62, height=0.26, depth=0.22, tag="fixture_obstacle"):
    """已知非对称方台：x 方向宽、z 方向高、y 方向深；放在 x=1.8。"""
    import trimesh
    m = trimesh.creation.box(extents=(depth, width, height))
    m.apply_translation([1.8, 0.0, height / 2])
    wd = pathlib.Path(out_dir) / tag
    wd.mkdir(parents=True, exist_ok=True)
    body = wd / 'body.stl'
    m.export(body)
    import hashlib
    h = hashlib.sha256(body.read_bytes()).hexdigest()
    (wd / 'manifest.json').write_text(json.dumps({
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'parts': ['body.stl'], 'world_sha': h, 'source_kind': 'fixture',
        'note': 'fixture 已知几何；不是 Lux3D 产物'
    }, indent=2))
    return wd, h


def run_option(wd, option, seed=0):
    """在共同真值场景里执行一个动作，返回结局与代价。"""
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=2.6, name='h5fx')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['objects'] = [{'posed_dir': str(wd)}]
    env = wheelleg_env.WheelLegEnv(spec)
    env.reset(seed=seed)
    m, d = env.model, env.data
    nav = {'R1': 0.0, 'R2': 0.0, 'L1': 0.0, 'L2': 0.0, 'A0': None}[option]
    max_steps = 900
    t_end = None
    # 统一动作库：R1/R2/L1/L2 都是 env.step(前向动作)，A0 走 brake_step
    act = {'R1': np.array([1.0, 0.0, 0.0]),
           'R2': np.array([1.0, 0.3, 0.0]),
           'L1': np.array([1.0, -0.3, 0.0]),
           'L2': np.array([0.6, 0.0, 0.0])}[option] if option != 'A0' else None
    for step in range(max_steps):
        if option == 'A0':
            env.brake_step()
            for _ in range(env.substeps):
                mujoco.mj_step(m, d)
        else:
            env.step(act)
        b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
        p = d.xpos[b]
        tilt = float(np.degrees(np.arccos(np.clip(d.xmat[b].reshape(3, 3)[2, 2], -1, 1))))
        if tilt > 45:
            return {'outcome': 'tipover', 'cost': 60.0, 't_end': None}
        if float(p[2]) < -0.2:
            return {'outcome': 'out_of_field', 'cost': 60.0, 't_end': None}
        if float(p[0]) > 2.6:
            return {'outcome': 'success', 'cost': float(step) * float(m.opt.timestep),
                    't_end': float(step) * float(m.opt.timestep)}
    return {'outcome': 'abort' if option == 'A0' else 'timeout',
            'cost': 40.0 if option == 'A0' else 60.0, 't_end': None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--height', type=float, default=0.26)
    ap.add_argument('--width', type=float, default=0.62)
    ap.add_argument('--tag', default='fixture_obstacle')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    wd, wsha = make_fixture_world(out, width=a.width, height=a.height, tag=a.tag)
    rec = {'workflow': 'h5_fixture_loop/v1', 'source_kind': 'fixture',
           'truth_asset_sha': wsha, 'truth_identity': 'fixture_obstacle',
           'note': 'fixture 仅验证接口；不计入真实 Lux3D 主张',
           'options': list(OPTIONS), 'seeds': a.seeds}

    # 1) 预演：候选 × 动作 × 初态（fixture 只有一个候选）
    rehearsal = []
    for s in a.seeds:
        for o in OPTIONS:
            r = run_option(wd, o, seed=s)
            rehearsal.append({'candidate_id': a.tag, 'option_id': o,
                              'initial_state_id': f'seed{s}', **r})
    # 2) 决策：最坏情形（任一初态失败即不选该动作），A0 兜底
    by_opt = {}
    for r in rehearsal:
        by_opt.setdefault(r['option_id'], []).append(r)
    safe = []
    for o, rs in by_opt.items():
        if o == 'A0':
            continue
        if all(x['outcome'] == 'success' for x in rs):
            safe.append((o, max(x['cost'] for x in rs)))
    chosen, reason = ('A0', None)
    if safe:
        chosen, _ = min(safe, key=lambda kv: kv[1])
        reason = 'worst-case: every initial state succeeded; lowest max cost'
    else:
        reason = 'no option passed in all initial states -> real A0 brake'
    # 3) 在共同真值上执行被选动作（每方法同一 truth_sha、同一初态）
    execs = []
    for s in a.seeds:
        r = run_option(wd, chosen, seed=s)
        execs.append({'method': 'fixture_H5', 'option_id': chosen,
                      'initial_state_id': f'seed{s}',
                      'truth_sha': wsha, **r})
    rec['rehearsal'] = rehearsal
    rec['decision'] = {'chosen_option': chosen, 'reason': reason,
                       'frozen_before_execution': True}
    rec['execution'] = execs
    (out / 'h5_fixture.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps({'truth_sha': wsha[:12], 'chosen': chosen,
                      'n_rehearsal': len(rehearsal),
                      'outcomes': [x['outcome'] for x in execs]}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
