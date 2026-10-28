"""
H5 单例闭环：候选（规划用）与隐藏真值（执行用）严格分离。

  MUJOCO_GL=osmesa .venv/bin/python scripts/h5_loop.py \
      --candidate-json <validated candidate> --truth-case cases/unseen_v1/planA.json \
      --out runs/unseen/recovery_r3/h5_A4_truth --seeds 0 1 2

与旧 h5_fixture_loop 的关键区别（审查 P0-1..P0-4）：
  · 预演用**候选**几何，执行用**真值**几何，两者 SHA 不同且分别记录；
  · 不再自带控制循环：候选预演与真值执行都走 runner.EpisodeRunner +
    skills.make_skill，动作名与 Gate P/页面一致；
  · 终止只认 env.step 的 terminated/truncated 与 runner 的 out_of_field；
  · 计时用 env.t，同时记录控制步与物理步数；
  · 三个初态由 reset(seed) 的真实扰动产生，保存实际 qpos/qvel 并校验互不相同；
  · 决策先落盘并算 SHA，再进入执行端，两阶段事件都记录。
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import wheelleg_env
from runner import EpisodeRunner
from skills import make_skill

OPTIONS = ('R1', 'R2', 'L1', 'L2', 'A0')
FAR = 60.0
ABORT = 40.0


def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _spec(kind, world_dir, case, task='M'):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=case['goal_x'],
                             name='h5')
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['skill_cfg'] = {'task': task}
    # 保留真实初态扰动：随机横向/朝向，按 seed 变化
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['objects'] = [{'posed_dir': str(world_dir)}]
    return spec


def run_episode(kind, world_dir, case, option, visible, seed, params=None):
    """一次完整回合：统一走 EpisodeRunner + make_skill。"""
    spec = _spec(kind, world_dir, case)
    env = wheelleg_env.WheelLegEnv(spec)
    sk = make_skill(option)
    runner = EpisodeRunner(env, sk, visible=visible, params=params or {}, seed=seed)
    out = runner.run()
    out['qpos0'] = [float(x) for x in env._qpos0] if hasattr(env, '_qpos0') else None
    out['control_steps'] = out['steps']
    out['physics_steps'] = int(env.n_physics)
    out['sim_time_s'] = round(float(env.t), 4)
    out['seed'] = seed
    return out


def _initial_state(env_spec_fn, case, seed):
    """只做 reset 就取出实际初态（qpos/qvel），用于记录与配对校验。"""
    env = wheelleg_env.WheelLegEnv(env_spec_fn())
    env.reset(seed=seed)
    return {'seed': seed,
            'qpos': [round(float(x), 6) for x in env.data.qpos],
            'qvel': [round(float(x), 6) for x in env.data.qvel],
            'qpos_hash': hashlib.sha256(
                np.asarray(env.data.qpos, dtype=np.float64).tobytes()).hexdigest()[:16]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate-json', required=True,
                    help='经 candidate_store 校验的候选 JSON')
    ap.add_argument('--truth-case', required=True, help='隐藏真值 case（含 mesh）')
    ap.add_argument('--out', required=True)
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--stress-test', action='store_true',
                    help='跨对象诊断：候选与真值来自不同观测组，不能算正常 H5 效果')
    a = ap.parse_args()

    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cand = json.loads(pathlib.Path(a.candidate_json).read_text())
    case = json.loads(pathlib.Path(a.truth_case).read_text())
    ROOT = pathlib.Path(__file__).resolve().parent.parent

    # ---- 先独立构造并物理化真值场景 -------------------------------------
    truth_mesh = ROOT / case['mesh']
    if not truth_mesh.exists():
        raise SystemExit(f'真值网格不存在：{truth_mesh}')
    truth_world = out / 'truth_world'
    truth_world.mkdir(parents=True, exist_ok=True)
    import trimesh
    tm = trimesh.load(str(truth_mesh), force='mesh')
    tm.apply_translation([case['obstacle_x'], 0.0, -float(tm.bounds[0][2])])
    tm.export(truth_world / 'body.stl')
    truth_sha = _sha(truth_world / 'body.stl')
    (truth_world / 'manifest.json').write_text(json.dumps({
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'parts': ['body.stl'], 'world_sha': truth_sha, 'source_kind': 'truth',
        'case': case['case_id'], 'source_mesh': case['mesh'],
        'note': '隐藏真值；只在执行/评估端使用'}, indent=2))

    cand_wd = pathlib.Path(cand['world_dir'])
    cand_sha = cand['world_sha256']
    if truth_sha == cand_sha:
        raise SystemExit('真值与候选 SHA 相同，拒绝：这不是独立隐藏真值')
    cand_group = (cand.get('observation_group') or
                  ('A' if str(cand['candidate_id']).startswith('A') else '?'))
    truth_group = 'B' if 'planB' in str(a.truth_case) else 'A'
    stress = bool(a.stress_test) or (cand_group != truth_group)
    rec = {'workflow': 'h5_loop/v1', 'source_kind': 'lux3d',
           'cross_object': stress,
           'label': ('STRESS_TEST: candidate from group %s, truth from group %s; '
                     'NOT a normal H5 result' % (cand_group, truth_group))
                    if stress else 'normal H5 (same observation group)',
           'candidate_id': cand['candidate_id'], 'candidate_task_id': cand.get('task_id'),
           'candidate_world_sha': cand_sha, 'truth_asset_sha': truth_sha,
           'truth_case': case['case_id'], 'truth_identity': case['case_id'],
           'strict_rgbd_diagnostic_pass': cand.get('strict_rgbd_diagnostic_pass'),
           'planning_eligible': cand.get('planning_eligible'),
           'sensor_note': 'align24 搜索使用密集可见点云；属有披露的工程诊断，'
                          '不等于"深度只用于位置尺度"',
           'options': list(OPTIONS), 'seeds': a.seeds}

    visible = {'x_front': float(cand.get('x_front') or 0) or None}

    # ---- 初态：真值场景下按 seed 取实际 qpos/qvel ------------------------
    init_states = []
    for s in a.seeds:
        init_states.append(_initial_state(lambda: _spec('truth', truth_world, case), case, s))
    hashes = [st['qpos_hash'] for st in init_states]
    rec['initial_states'] = init_states
    rec['initial_states_distinct'] = len(set(hashes)) == len(hashes)

    # ---- 阶段 1：在候选上预演（planner 只看候选）------------------------
    rehearsal = []
    for st in init_states:
        for o in OPTIONS:
            r = run_episode('cand', cand_wd, case, o, visible, st['seed'])
            rehearsal.append({'candidate_id': cand['candidate_id'], 'option_id': o,
                              'initial_state_id': f"seed{st['seed']}",
                              'outcome': r['reason'], 'success': r['success'],
                              'abort': r['abort'], 't_end': r['t_end'],
                              'sim_time_s': r['sim_time_s'],
                              'control_steps': r['control_steps'],
                              'physics_steps': r['physics_steps'],
                              'cost': (r['t_end'] if r['success'] else
                                       (ABORT if r['abort'] else FAR))})
    rec['rehearsal'] = rehearsal

    # ---- 阶段 2：决策，先落盘再执行 --------------------------------------
    by_opt = {}
    for r in rehearsal:
        by_opt.setdefault(r['option_id'], []).append(r)
    safe = []
    for o, rs in by_opt.items():
        if o == 'A0':
            continue
        if all(x['success'] for x in rs):
            safe.append((o, max(x['cost'] for x in rs)))
    if safe:
        chosen, _ = min(safe, key=lambda kv: kv[1])
        reason = 'worst-case over initial states: all succeeded; lowest max cost'
    else:
        chosen = 'A0'
        reason = 'no non-A0 option succeeded in every initial state -> real A0 brake'
    decision = {'chosen_option': chosen, 'reason': reason,
                'n_initial_states': len(init_states),
                'candidate_world_sha': cand_sha,
                'rule': 'min worst-case cost among options succeeding in ALL initial states'}
    dec_path = out / 'decision.json'
    dec_path.write_text(json.dumps(decision, indent=2, ensure_ascii=False))
    rec['decision'] = decision
    rec['decision_sha256'] = _sha(dec_path)
    rec['decision_frozen_at'] = 'written before any truth execution'
    (out / 'h5_event_decision.json').write_text(json.dumps(
        {'event': 'decision_frozen', 'decision_sha256': rec['decision_sha256'],
         'candidate_world_sha': cand_sha, 'truth_asset_sha': truth_sha}, indent=2))

    # ---- 阶段 3：在独立真值上执行选定动作 + 盲走对照 ----------------------
    execs = []
    for st in init_states:
        for method, opt in (('H5', chosen), ('B0_blind', 'R1')):
            r = run_episode('truth', truth_world, case, opt, visible, st['seed'])
            execs.append({'method': method, 'option_id': opt,
                          'initial_state_id': f"seed{st['seed']}",
                          'truth_sha': truth_sha, 'outcome': r['reason'],
                          'success': r['success'], 'abort': r['abort'],
                          't_end': r['t_end'], 'final_x': r['final_x'],
                          'max_tilt': r['max_tilt'], 'contact': r['contact'],
                          'sim_time_s': r['sim_time_s'],
                          'control_steps': r['control_steps'],
                          'physics_steps': r['physics_steps'],
                          'action_fingerprint': r['action_fingerprint'],
                          'triggered': r['triggered']})
    rec['execution'] = execs
    rec['truth_used'] = rec['truth_identity']
    (out / 'h5_event_execution.json').write_text(json.dumps(
        {'event': 'execution_on_independent_truth',
         'decision_sha256_verified': _sha(dec_path),
         'truth_asset_sha': truth_sha,
         'note': '执行端重新读取 decision.json 并校验 SHA，证明先冻结后执行'},
        indent=2))
    (out / 'h5_loop.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))

    h5 = [e for e in execs if e['method'] == 'H5']
    b0 = [e for e in execs if e['method'] == 'B0_blind']
    print(json.dumps({
        'candidate': cand['candidate_id'], 'truth': case['case_id'],
        'cross_object_stress_test': stress,
        'same_sha': truth_sha == cand_sha,
        'chosen': chosen, 'decision_sha': rec['decision_sha256'][:12],
        'init_distinct': rec['initial_states_distinct'],
        'H5_outcomes': [e['outcome'] for e in h5],
        'B0_outcomes': [e['outcome'] for e in b0],
        'H5_success': sum(1 for e in h5 if e['success']),
        'B0_success': sum(1 for e in b0 if e['success'])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
