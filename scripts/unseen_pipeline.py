"""
单例闭环：观察 → 假设 → 预演 → 决策 → 真值执行 → 揭晓。

  .venv/bin/python scripts/unseen_pipeline.py --case cases/unseen_v1/case_A.json \
      --hyp-source H3 --cached-only --out runs/unseen/e2e/<run_id>

诚实边界（必须写进产物）：
  · 本轮 `--hyp-source H3` 用的是**几何先验假设**（由可见面按固定背面型面补全），
    **不是 Lux3D 生成结果**。Lux3D 图生路径需要付费授权，未启用。
  · 假设只由 (x_front, W_vis, H_vis) 与固定背面型面生成，不读真值背深/类型。
  · 真值只给 evaluator 用；planner 侧不读 truth 字段。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gate_physics as GP
import physicalize as PH
import runner
import skills
import terrain
import twins
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent

# H3 先验：3 个固定背面型面，**故意不等于**真值可能取到的 5 种
PRIOR_BACKS = [('ramp_s', 18.0), ('ramp_l', 30.0), ('drop', 45.0)]


def build_hypotheses(obs, case, out_dir):
    """
    由**可见量**构造假设：只把观测到的 x_front / W_vis / H_vis 映射到米制，
    再套用固定背面型面。不读真值。
    """
    vis = obs['visible']
    H = float(vis['H_vis'])
    W = float(vis['W_vis'])
    D = float(case['obstacle_x'] - vis['x_front']) if vis.get('x_front') else 0.12
    hyps = []
    for kind, ang in PRIOR_BACKS:
        if kind == 'drop':
            mesh, Lb = twins.twin_solid('drop', H, W, max(D, 0.05))
        else:
            # 用角度换算成等效背长，复用同一生成器
            L = H / np.tan(np.deg2rad(ang))
            mesh, Lb = twins.twin_solid(kind, H, W, max(D, 0.05))
            mesh, Lb = twins.twin_solid(kind, H, W, max(D, 0.05))
        hid = f'{kind}_{int(ang)}'
        mpath = out_dir / 'hyp' / f'{hid}.stl'
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(mpath)
        pdir = out_dir / 'posed' / hid
        hyps.append({'hypothesis_id': hid, 'kind': kind, 'angle_deg': ang,
                     'mesh': str(mpath), 'posed_dir': str(pdir),
                     'L_back_prior': round(float(Lb), 4),
                     'H': round(H, 4), 'W': round(W, 4), 'D_front': round(D, 4)})
    return hyps


def physicalize_hyps(hyps):
    import subprocess
    for h in hyps:
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/physicalize.py'),
                            '--mesh', h['mesh'], '--out', h['posed_dir'],
                            '--hypothesis-id', h['hypothesis_id'], '--skip-probe'],
                           capture_output=True, text=True, cwd=str(ROOT))
        h['physicalize_rc'] = r.returncode
        if r.returncode != 0:
            h['physicalize_error'] = r.stderr[-300:]


def _spec_from_posed(posed_dir, H, x, seed):
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=2.8,
                             name=pathlib.Path(posed_dir).name)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': GP.INIT_LAT, 'yaw_rad': GP.INIT_YAW}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(posed_dir), 'x': x, 'y': 0.0,
                        'yaw_deg': 0.0, 'target_height_m': H}]
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.20], 'pitch_deg': -12.0, 'fovy': 70.0}
    return spec


def _spec_from_world(world_dir, seed, goal_x=2.6):
    """世界坐标资产：body identity，不再平移/缩放/贴地。"""
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=goal_x,
                             name=pathlib.Path(world_dir).name)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': GP.INIT_LAT, 'yaw_rad': GP.INIT_YAW}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(world_dir)}]      # 只有这一项，x/y/yaw 全不传
    return spec


def rehearse_world(world_dir, option, seed, visible=None, time_limit=15.0, goal_x=2.6):
    """世界坐标资产上跑一个回合：与 Gate P、真值执行共用同一执行器与动作库。"""
    spec = _spec_from_world(world_dir, seed, goal_x=goal_x)
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                   v_ref=1.0, tip_deg=60.0)
    r = runner.EpisodeRunner(env, skills.make_skill(option),
                             visible=visible or {}, seed=seed)
    out = r.run_with_seed(seed)
    return {'option': option, 'seed': seed, 'reason': out['reason'],
            'success': out['success'], 'abort': out['abort'], 't_end': out['t_end'],
            'x': out['final_x'], 'contact': out['contact'],
            'belly_contact': out['belly_contact'],
            'triggered': out['triggered'], 'brake_steps': out['brake_steps'],
            'action_fingerprint': out['action_fingerprint'],
            'phases': out['phases'], 'n_actions': out['n_actions'],
            'sim_time_s': round(float(env.t), 4),
            'control_steps': out['steps'],
            'physics_steps': int(env.n_physics),
            'q0': out['q0']}


def rehearse_option(posed_dir, H, x, option, seed, visible=None, time_limit=15.0):
    """与 Gate P、真值执行共用同一个执行器。"""
    spec = _spec_from_posed(posed_dir, H, x, seed)
    spec['goal_x'] = 2.8
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                   v_ref=1.0, tip_deg=60.0)
    r = runner.EpisodeRunner(env, skills.make_skill(option),
                             visible=visible or {}, seed=seed)
    out = r.run_with_seed(seed)
    return {'option': option, 'seed': seed, 'reason': out['reason'],
            'success': out['success'], 't_end': out['t_end'],
            'x': out['final_x'], 'contact': out['contact'],
            'belly_contact': out['belly_contact'],
            'triggered': out['triggered'], 'brake_steps': out['brake_steps'],
            'action_fingerprint': out['action_fingerprint'],
            'phases': out['phases']}


def decide(matrix, options, tau=0.0, c_fail=60.0, c_abort=40.0):
    """
    最坏假设风险规则（任务书 8.2）：
      f(o,h) = 该动作在该假设下 3 个初态的失败比例
      c(o,h) = 平均代价（成功取 t_end，失败 C_fail，放弃 C_abort）
      R(o)   = max_h f(o,h)
      safe_set = {o : R(o) <= tau}，A0 不参与 safe_set
    """
    hyps = sorted({m['hypothesis_id'] for m in matrix})
    seeds = sorted({m['seed'] for m in matrix})
    stats = {}
    for o in options:
        if o == 'A0':
            continue
        per_h = {}
        for h in hyps:
            cells = [m for m in matrix if m['option'] == o and m['hypothesis_id'] == h]
            if len(cells) != len(seeds):
                return {'insufficient_evidence': True,
                        'missing': f'{o}/{h} 只有 {len(cells)}/{len(seeds)} 条'}
            fails = [c for c in cells if not c['success']]
            f = len(fails) / len(cells)
            costs = [(c['t_end'] if c['success'] and c['t_end'] else c_fail) for c in cells]
            per_h[h] = {'f': round(f, 3), 'c': round(float(np.mean(costs)), 3)}
        risk = max(v['f'] for v in per_h.values())
        mean_c = float(np.mean([v['c'] for v in per_h.values()]))
        stats[o] = {'f': {h: per_h[h]['f'] for h in hyps},
                    'c': {h: per_h[h]['c'] for h in hyps},
                    'R': round(risk, 3), 'mean_c': round(mean_c, 3)}
    safe = [o for o in options if o != 'A0' and o in stats and stats[o]['R'] <= tau]
    tie, tied = False, []
    if safe:
        safe.sort(key=lambda o: (stats[o]['mean_c'], o))
        chosen, no_robust = safe[0], False
        # 同分必须如实标注：此时"选了谁"是名称排序，不能当成选中了更好的动作
        best_c = stats[safe[0]]['mean_c']
        tied = [o for o in safe if abs(stats[o]['mean_c'] - best_c) < 1e-9]
        tie = len(tied) > 1
    else:
        chosen, no_robust = 'A0', True
    return {'rule': 'worst-case-risk/v1', 'tau': tau, 'c_fail': c_fail,
            'c_abort': c_abort, 'hypotheses': hyps, 'n_seeds': len(seeds),
            'stats': stats, 'safe_set': safe, 'chosen': chosen,
            'tie': tie, 'tied_options': tied,
            'no_robust_option': no_robust,
            'insufficient_evidence': False,
            'reason_text': (
                (f'在这 {len(hyps)} 个候选、每个 {len(seeds)} 个测试初态中均通过'
                 + (f'；{len(tied)} 个动作同分（{"/".join(tied)}），按名称排序取 {chosen}，'
                    '这只是 tie-break，不代表它更优' if tie else ''))
                if safe else '没有任何通行动作在所有候选里都通过 -> 选择 A0 刹停')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--hyp-source', default='H3')
    ap.add_argument('--cached-only', action='store_true')
    ap.add_argument('--out', required=True)
    ap.add_argument('--options', default='R1,R2,L1,L2,A0')
    ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--candidates', default=None,
                    help='candidate_store 输出的候选 JSON 列表；H4/H5 必需')
    ap.add_argument('--policy', default='configs/unseen_planning_policy.json')
    ap.add_argument('--goal-x', type=float, default=2.6)
    a = ap.parse_args()

    case = json.loads(pathlib.Path(a.case).read_text())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    options = a.options.split(',')
    seeds = [int(x) for x in a.seeds.split(',')]

    # --- 1. 观测（已有缓存则直接读，不重复渲染） ---
    obs_path = out / 'observation.json'
    if not obs_path.exists():
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/observe.py'),
                            '--case', a.case, '--out', str(out)],
                           capture_output=True, text=True, cwd=str(ROOT))
        if r.returncode != 0:
            raise SystemExit(f'观测失败：{r.stderr[-400:]}')
    obs = json.loads((out / 'observation.json').read_text())

    # --- 2. 假设 ---
    if a.hyp_source == 'H3':
        hyps = build_hypotheses(obs, case, out)
        world_mode = False
    elif a.hyp_source in ('H4', 'H5'):
        # 真实生成候选：只从本地缓存读，绝不 create
        import candidate_store as CS
        if not a.candidates:
            raise SystemExit('H4/H5 需要 --candidates（candidate_store 校验后的候选）')
        cands = json.loads(pathlib.Path(a.candidates).read_text())
        if isinstance(cands, dict):
            cands = cands.get('accepted') or cands.get('candidates') or []
        for c in cands:
            if c.get('coordinate_frame') != 'world':
                raise SystemExit(f"候选 {c.get('candidate_id')} 不是 world 坐标系，拒绝")
            if not c.get('planning_eligible'):
                raise SystemExit(f"候选 {c.get('candidate_id')} 未通过 planning_eligible，"
                                 '不能进入正式预演')
        if a.hyp_source == 'H4':
            cands = sorted(cands, key=lambda c: str(c.get('task_id') or ''))[:1]
        hyps = [{'hypothesis_id': c['candidate_id'],
                 'kind': 'lux3d', 'world_dir': c['world_dir'],
                 'world_sha': c['world_sha256'],
                 'task_id': c.get('task_id'),
                 'source_kind': 'lux3d',
                 'metrics': c.get('best')} for c in cands]
        world_mode = True
    else:
        raise SystemExit(f'未知假设来源 {a.hyp_source}')
    if a.cached_only:
        pass
    if world_mode:
        # 保姿态碰撞化：世界网格 -> CoACD 部件，保持 world identity
        import subprocess
        for h in hyps:
            cd = out / 'collision' / h['hypothesis_id']
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/physicalize.py'),
                                '--mesh', str(pathlib.Path(h['world_dir']) / 'body.stl'),
                                '--out', str(cd), '--hypothesis-id', h['hypothesis_id']],
                               capture_output=True, text=True, cwd=str(ROOT))
            h['collision_dir'] = str(cd)
            h['physicalize_rc'] = r.returncode
            if r.returncode != 0:
                h['physicalize_error'] = r.stderr[-300:]
            else:
                cm = json.loads((cd / 'manifest.json').read_text())
                h['collision_sha'] = cm.get('collision_sha')
                h['coacd_parts'] = cm.get('coacd_parts')
                h['concavity'] = cm.get('concavity')
    else:
        physicalize_hyps(hyps)
    bad = [h for h in hyps if h.get('physicalize_rc') != 0]
    if bad:
        raise SystemExit(f'物理化失败 {len(bad)} 个：{[b["hypothesis_id"] for b in bad]}')

    # --- 3. 预演（候选上；planner 只看到候选取样与公共观测） ---
    matrix = []
    for h in hyps:
        for o in options:
            if o == 'A0':
                continue
            for sd in seeds:
                if world_mode:
                    # 物理用 CoACD 碰撞部件（世界坐标、保姿态）；视觉网格不参与碰撞
                    m = rehearse_world(pathlib.Path(h['collision_dir']), o, sd,
                                       visible=obs['visible'], goal_x=a.goal_x)
                else:
                    m = rehearse_option(h['posed_dir'], h['H'], case['obstacle_x'], o, sd,
                                        visible=obs['visible'])
                m['hypothesis_id'] = h['hypothesis_id']
                matrix.append(m)
    (out / 'rehearsal.jsonl').write_text(
        '\n'.join(json.dumps(m, ensure_ascii=False) for m in matrix) + '\n')

    # --- 4. 决策 ---
    dec = decide(matrix, options)
    (out / 'decision.json').write_text(json.dumps(dec, indent=2, ensure_ascii=False))
    if dec.get('insufficient_evidence'):
        raise SystemExit(f'证据不足：{dec["missing"]}')

    # --- 5. 真值执行与揭晓（只有这一步用 truth） ---
    import hashlib
    import subprocess

    def _sha(p):
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
        return h.hexdigest()

    truth = pathlib.Path(case['mesh'])
    if not truth.exists():
        raise SystemExit(f'真值网格不存在：{truth}')
    truth_world = out / 'truth_world'
    truth_world.mkdir(parents=True, exist_ok=True)
    import trimesh as _tm
    _m = _tm.load(str(truth), force='mesh')
    _m.apply_translation([case['obstacle_x'], 0.0, -float(_m.bounds[0][2])])
    _m.export(truth_world / 'body.stl')
    truth_sha = _sha(truth_world / 'body.stl')
    if world_mode:
        for h in hyps:
            if h.get('world_sha') == truth_sha:
                raise SystemExit(f"候选 {h['hypothesis_id']} 与真值 SHA 相同，"
                                 '这不是独立隐藏真值')
    (truth_world / 'manifest.json').write_text(json.dumps({
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'parts': ['body.stl'], 'world_sha': truth_sha, 'source_kind': 'truth',
        'case': case['case_id'], 'source_mesh': str(truth)}, indent=2))

    truth_collision = out / 'truth_collision'
    if world_mode:
        subprocess.run([sys.executable, str(ROOT / 'scripts/physicalize.py'),
                        '--mesh', str(truth_world / 'body.stl'),
                        '--out', str(truth_collision),
                        '--hypothesis-id', 'TRUTH'],
                       capture_output=True, text=True, cwd=str(ROOT))
    else:
        # H3 路径保留旧的局部坐标物理化（兼容）
        subprocess.run([sys.executable, str(ROOT / 'scripts/physicalize.py'),
                        '--mesh', str(truth), '--out', str(out / 'truth_posed'),
                        '--hypothesis-id', 'TRUTH', '--skip-probe'],
                       capture_output=True, text=True, cwd=str(ROOT))

    exec_runs = []
    for o in {dec['chosen'], 'R1'} | ({'A0'} if dec['chosen'] != 'A0' else set()):
        for sd in seeds:
            if world_mode:
                m = rehearse_world(truth_collision, o, sd, visible=obs['visible'],
                                   goal_x=a.goal_x)
            else:
                m = rehearse_option(out / 'truth_posed', case['H'],
                                    case['obstacle_x'], o, sd,
                                    visible=obs['visible'])
            m['is_truth'] = True
            m['truth_sha'] = truth_sha
            exec_runs.append(m)
    (out / 'execution.jsonl').write_text(
        '\n'.join(json.dumps(m, ensure_ascii=False) for m in exec_runs) + '\n')

    chosen_rows = [m for m in exec_runs if m['option'] == dec['chosen']]
    blind_rows = [m for m in exec_runs if m['option'] == 'R1']
    summary = {
        'case_id': case['case_id'], 'hyp_source': a.hyp_source,
        'hyp_source_note': ('几何先验假设，不是 Lux3D 生成结果'
                            if a.hyp_source == 'H3'
                            else '真实 Lux3D 候选（本地缓存，未新建任务）'),
        'truth_sha': truth_sha,
        'collision_geometry': ('CoACD convex parts (world frame, posture preserved)'
                               if world_mode else 'posed parts (legacy local frame)'),
        'candidates': [{'hypothesis_id': h['hypothesis_id'],
                        'task_id': h.get('task_id'),
                        'world_sha': h.get('world_sha'),
                        'collision_sha': h.get('collision_sha'),
                        'coacd_parts': h.get('coacd_parts')} for h in hyps],
        'n_hypotheses': len(hyps), 'n_seeds': len(seeds), 'options': options,
        'chosen': dec['chosen'], 'no_robust_option': dec['no_robust_option'],
        'chosen_truth_success': f"{sum(1 for m in chosen_rows if m['success'])}/{len(chosen_rows)}",
        'blind_truth_success': f"{sum(1 for m in blind_rows if m['success'])}/{len(blind_rows)}",
    }
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
