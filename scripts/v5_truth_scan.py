"""
V5 真值动作扫描（P2 / 方向诊断）：在独立真值上逐动作 × 初态执行。

  MUJOCO_GL=osmesa .venv/bin/python scripts/v5_truth_scan.py \
      --case cases/unseen_v1/R01.json --observation runs/unseen/recovery_r3/obs_R01 \
      --out runs/unseen/delivery_v5/v5_20261029/cases/R01 --seeds 0 1 2

与 dev_scan 的区别：
  · 接受任意 case（含 world-frame 真值方向实例），不写死开发石头；
  · 复用 actions.OPTIONS / EpisodeRunner / physicalize，不另写控制循环；
  · 记录每个初态的完整 qpos/qvel 与哈希，而不只是 q0；
  · 统一 30 s 阶段协议；A0 也走终止检查。
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import actions as ACT
import eval_six
import runner as R
import skills
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
INIT_CFG = json.loads((ROOT / 'configs/unseen_initial_state_v5.json').read_text())
FAR, ABORT = 60.0, 40.0


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def full_hash(qpos, qvel):
    h = hashlib.sha256()
    h.update(np.asarray(qpos, dtype=np.float64).tobytes())
    h.update(np.asarray(qvel, dtype=np.float64).tobytes())
    return h.hexdigest()[:16]


def build_truth_world(case, out):
    tw = out / 'truth_world'
    tw.mkdir(parents=True, exist_ok=True)
    body = tw / 'body.stl'
    if case.get('world_frame_mesh') or case.get('truth_world_sha'):
        m = trimesh.load(str(ROOT / case['mesh']), force='mesh').copy()
    else:
        m = trimesh.load(str(ROOT / case['mesh']), force='mesh').copy()
        yaw = float(case.get('yaw_deg', 0.0))
        if abs(yaw) > 1e-12:
            m.apply_transform(trimesh.transformations.rotation_matrix(
                np.deg2rad(yaw), [0.0, 0.0, 1.0]))
        m.apply_translation([float(case['obstacle_x']), 0.0, 0.0])
        zmin = float(np.asarray(m.bounds)[0][2])
        if abs(zmin) > 1e-12:
            m.apply_translation([0.0, 0.0, -zmin])
    m.export(body)
    wsha = sha(body)
    (tw / 'manifest.json').write_text(json.dumps({
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'source_kind': 'truth', 'parts': ['body.stl'], 'world_sha': wsha,
        'case': case['case_id'], 'source_mesh': case.get('source_mesh', case['mesh']),
        'note': 'V5 truth scan：world frame，下游 identity 放置'}, indent=2,
        ensure_ascii=False))
    return body, wsha


def spec_for(world_dir, case, goal_x, soil_mode='rigid', seed=0):
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=goal_x,
                             name=f"v5scan_{pathlib.Path(world_dir).name}")
    spec['channel'] = {'center_y': 0.0, 'half_width': float(case.get('channel_half', 1.2))}
    spec['init_perturbation'] = {'lateral_m': float(INIT_CFG['lateral_m']),
                                 'yaw_rad': float(INIT_CFG['yaw_rad'])}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(world_dir)}]
    if soil_mode != 'rigid':
        spec['soil'] = {'mode': soil_mode}
    return spec


def run_one(world_dir, case, option, seed, vis, goal_x, time_limit,
            soil_mode='rigid'):
    spec = spec_for(world_dir, case, goal_x, soil_mode=soil_mode, seed=seed)
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                   v_ref=1.0, tip_deg=60.0)
    env.reset(seed=seed)
    qpos0 = [float(x) for x in env.data.qpos]
    qvel0 = [float(x) for x in env.data.qvel]
    sk = skills.make_skill(option)
    r = R.EpisodeRunner(env, sk, visible=vis, seed=seed)
    out = r.run()
    cost = (out['t_end'] if out['success'] else
            (ABORT if out['abort'] else FAR))
    return {
        'option': option, 'seed': seed, 'reason': out['reason'],
        'success': out['success'], 'abort': out['abort'],
        't_end': out['t_end'], 'final_x': out['final_x'],
        'max_tilt': out['max_tilt'], 'contact': out['contact'],
        'belly_contact': out['belly_contact'], 'triggered': out['triggered'],
        'phases': out['phases'], 'action_fingerprint': out['action_fingerprint'],
        'control_steps': out['steps'], 'physics_steps': int(env.n_physics),
        'initial_qpos': qpos0, 'initial_qvel': qvel0,
        'initial_state_hash': full_hash(qpos0, qvel0),
        'cost': cost, 'soil_mode': soil_mode,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--observation', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--actions', default=None,
                    help='逗号分隔；缺省 actions.OPTIONS')
    ap.add_argument('--goal-x', type=float, default=None)
    ap.add_argument('--time-limit', type=float, default=30.0)
    ap.add_argument('--soil-mode', default='rigid')
    a = ap.parse_args()

    case = json.loads(pathlib.Path(a.case).read_text())
    obs = json.loads((pathlib.Path(a.observation) / 'observation.json').read_text())
    vis = obs['visible']
    goal_x = float(a.goal_x if a.goal_x is not None else case['goal_x'])
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)

    body, wsha = build_truth_world(case, out)
    col, cm = eval_six.collisionize(body, out, 'TRUTH')
    col_sha = cm.get('collision_sha')
    options = (a.actions.split(',') if a.actions else list(ACT.OPTIONS))
    unknown = [o for o in options if o not in ACT.OPTIONS]
    if unknown:
        raise SystemExit(f'未知动作 {unknown}')

    rows = []
    for o in options:
        ok, why = ACT.applicable(o, vis, case.get('channel_half', 1.2))
        for sd in a.seeds:
            if not ok:
                rows.append({'option': o, 'seed': sd, 'not_applicable': why,
                             'success': False, 'cost': None})
                continue
            r = run_one(col, case, o, sd, vis, goal_x, a.time_limit,
                        soil_mode=a.soil_mode)
            rows.append(r)
    (out / 'scan.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')

    summary = {'case': case['case_id'], 'truth_world_sha': wsha,
               'truth_collision_sha': col_sha, 'coacd_parts': cm.get('coacd_parts'),
               'observation': a.observation, 'observation_id': obs.get('observation_id'),
               'seeds': a.seeds, 'time_limit_s': a.time_limit,
               'soil_mode': a.soil_mode, 'visible': vis, 'by_action': {}}
    for o in options:
        rs = [r for r in rows if r['option'] == o and not r.get('not_applicable')]
        na = [r for r in rows if r['option'] == o and r.get('not_applicable')]
        summary['by_action'][o] = {
            'n_run': len(rs), 'success': sum(1 for r in rs if r['success']),
            'outcomes': [r['reason'] for r in rs],
            'mean_cost': (round(float(np.mean([r['cost'] for r in rs])), 3)
                          if rs else None),
            'max_cost': (max(r['cost'] for r in rs) if rs else None),
            'not_applicable': (na[0]['not_applicable'] if na else None),
            'initial_hashes': sorted({r['initial_state_hash'] for r in rs}),
            'qpos0': sorted({tuple(round(x, 6) for x in r['initial_qpos'])
                             for r in rs}),
        }
    non_a0 = [o for o in options if o != 'A0']
    run_ok = {o: (summary['by_action'][o]['n_run'] == len(a.seeds) and
                  summary['by_action'][o]['success'] == len(a.seeds))
              for o in non_a0}
    r1 = summary['by_action'].get('R1', {})
    summary['flags'] = {
        'all_non_a0_pass': all(run_ok.values()),
        'all_non_a0_fail': all(summary['by_action'][o]['success'] == 0
                               for o in non_a0 if not summary['by_action'][o]['not_applicable']),
        'R1_all_success': bool(r1.get('n_run')) and r1.get('success') == len(a.seeds),
        'has_tradeoff': (not (bool(r1.get('n_run')) and r1.get('success') == len(a.seeds))
                         and any(run_ok.values())),
        'passing_actions': [o for o in non_a0 if run_ok.get(o)],
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({'case': summary['case'], 'flags': summary['flags'],
                      'by_action': {o: (summary['by_action'][o]['success'],
                                        summary['by_action'][o]['n_run'])
                                    for o in options}}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
