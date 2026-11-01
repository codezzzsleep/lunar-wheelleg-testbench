"""公平三臂第二观察对照（下一批任务书 §4）。

  A：从 S1 出发，只用第一张图与第一眼假设；
  B：从同一 S1 出发，用**本次采集的第二张图**筛选/更新后的假设；
  C：从 S0 出发，只用当时已得的第一张图与假设（不得用两视角候选或观察后 visible）。

三臂调用同一共同规划器，决策各自落盘，再从各自起点在同一独立真值上执行；
从 S0 统计总模拟时间与结局，不再用位移相减解释观察成本。

  python scripts/v7_second_view_fair.py --config R02_s0.9 --soil nominal --seed 7 --out <dir>
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import candidate_qualification as CQ
import common_planner as CP
import runner
import skills
import v7_common_matrix as MX

PY = sys.executable
BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'


def sh(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    import hashlib
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def build_two_view(obs1, obs2, out_dir, cfg):
    """用本次真实第二张图重做两视角占据，并融合成候选。"""
    out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([PY, 'scripts/v7_two_view_occupancy.py',
                        '--parent', cfg['parent_world'],
                        '--parent-id', f"tv_{cfg['config_id']}",
                        '--obs1', str(obs1), '--obs2', str(obs2),
                        '--out', str(out_dir), '--pitch', '0.0025',
                        '--edge-thr', '0'],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        return None, {'error': (r.stderr or '')[-800:]}
    rep = out_dir / 'two_view_report.json'
    if not rep.is_file():
        return None, {'error': '两视角报告缺失'}
    # 从占据重建网格与碰撞（确定性）
    subprocess.run([PY, 'scripts/v7_rebuild_from_occ.py', '--occ', str(out_dir / 'occ.npz'),
                    '--out', str(out_dir)], cwd=str(ROOT), capture_output=True, text=True)
    subprocess.run([PY, 'scripts/collision_box_union.py', '--occupancy',
                    str(out_dir / 'occ.npz'), '--out', str(out_dir / 'collision'),
                    '--pitch', '0.0025', '--hypothesis-id',
                    f"tv_{cfg['config_id']}"], cwd=str(ROOT), capture_output=True, text=True)
    return out_dir, {'two_view_report': str(rep.relative_to(ROOT)),
                     'occ_sha': sh(out_dir / 'occ.npz')}



def measure_two_view_visibility(tv_dir, obs_dir):
    """两视角重建只有占据与报告；可见指标必须现场测量后再作为准入输入。"""
    import numpy as np
    import align
    import fuse_observed as FO
    import meshdist
    tv_dir = pathlib.Path(tv_dir)
    obs_dir = pathlib.Path(obs_dir)
    out_path = tv_dir / 'visible_two_view.json'
    if out_path.is_file():
        return json.loads(out_path.read_text())
    mesh = FO._load_mesh(tv_dir / 'body.stl')
    tmp = tv_dir / '_vis.stl'
    mesh.export(tmp)
    # 面数超过 MuJoCo 单 mesh 上限时用多视觉 mesh 渲染（几何不变）
    posed = None
    try:
        import v7_multimesh as _MM
        if len(mesh.faces) > _MM.MAX_FACES_DEFAULT:
            pd = tv_dir / '_visual_parts'
            parts, meta = _MM.split_mesh(mesh, _MM.MAX_FACES_DEFAULT)
            _MM.write_world(parts, pd, FO.sha_file(tmp), len(mesh.faces), {'split': meta})
            posed = str(pd)
    except Exception:
        posed = None
    m = align.render_eval(mesh, str(obs_dir), tmpdir=str(tmp), W=None, H=None,
                          want_vis_pt=False, posed_dir=posed)
    tmp.unlink(missing_ok=True)
    vis = np.load(obs_dir / 'visible_points.npy')
    if len(vis) > 1200:
        vis = vis[np.random.default_rng(0).choice(len(vis), 1200, replace=False)]
    d = meshdist.point_to_mesh_distance(mesh, vis, chunk=64)
    rec = {'obs1': {'mask_iou': m.get('mask_iou'),
                    'vis_pt_p95_mm': round(float(np.percentile(d, 95)) * 1000, 3),
                    'freespace_violation': m.get('freespace_violation')},
           'both_views': False,
           'measured_here': True,
           'note': '两视角重建后现场测量的 obs1 可见指标'}
    out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def admit(asset_dir, obs, case, label):
    """候选准入：严格门通过→qualified；否则作为**诊断假设**准入但如实标 strict=false。"""
    d = ROOT / asset_dir
    proc = d / 'manifest.json'
    if not proc.is_file() and (d / 'two_view_report.json').is_file():
        proc = CQ.record_from_two_view(d)
    res = CQ.qualify_candidate({'candidate_id': d.name, 'process': str(proc),
                                'collision_dir': str(d / 'collision'),
                                'mesh': str(d / 'body.stl')}, obs, case=case, strict=True)
    return {'candidate_id': d.name, 'collision_dir': str(d.relative_to(ROOT)),
            'strict_qualified': bool(res['qualified']),
            'admitted_as': ('qualified' if res['qualified'] else 'diagnostic_hypothesis'),
            'visible': res.get('visible_metrics'), 'reasons': res.get('reasons', [])[:3],
            'label': label}


def plan_and_execute(tag, cfg, soil, seed, snapshot, vis, hyps, out_root, budget):
    out = out_root / tag
    out.mkdir(parents=True, exist_ok=True)
    table = {h['id']: h['collision_dir'] for h in hyps}
    builder = lambda h, s: MX.build_env(cfg, s, collision_dir=table[h['id']])
    plan = CP.plan_action(hyps, snapshot, vis, [soil], budget, builder,
                          goal_x=json.loads((ROOT / cfg['case_config']).read_text())['goal_x'],
                          seed=seed)
    CP.write_plan(plan, out)
    act = plan['decision']['chosen']
    (out / 'decision.json').write_text(json.dumps(
        {'arm': tag, 'chosen': act, 'decision': plan['decision'],
         'hypotheses': [h['id'] for h in hyps], 'planning_soils': [soil]},
        ensure_ascii=False, indent=2))
    env = MX.build_env(cfg, soil, collision_dir=MX.truth_collision_for(cfg))
    env.reset(seed=seed)
    env.restore_state(snapshot, mode='same_scene')
    r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=seed,
                             record_trajectory=True).run_current()
    frames = r.get('trajectory') or []
    if frames:
        (out / 'trajectory.jsonl').write_text(
            '\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
    return {'arm': tag, 'chosen': act, 'cells': plan['counts']['rows'],
            'safe_set': plan['decision'].get('safe_set'),
            'success': bool(r.get('success')), 'reason': r.get('reason'),
            'execution_sim_time_s': round(float(env.t), 4),
            'final_x': r.get('final_x'), 'frames': len(frames),
            'hypotheses': [h['id'] for h in hyps]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='R02_s0.9')
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--first-candidate', default=None,
                    help='第一张图派生的候选目录（诊断或合格都可）')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out_root = ROOT / a.out if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    out_root.mkdir(parents=True, exist_ok=True)

    plan = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
    cfg = dict(next(c for c in plan['configs'] if c['config_id'] == a.config))
    cfg['parent_world'] = (f"runs/unseen/delivery_v7/v7_20261030/candidates/"
                           f"{'V7_R02_s1' if a.config.startswith('R02') else 'V7_R01_s2'}/world/align")
    cfg['parent_world'] = (f"runs/unseen/delivery_v7/v7_20261030/candidates/"
                           f"{'V7_R02_s1' if a.config.startswith('R02') else 'V7_R01_s2'}/world/align")
    unit = ROOT / BATCH / 'common_states' / a.config / a.soil / f'seed{a.seed}'
    acq = json.loads((unit / 'acquisition.json').read_text())
    s1 = json.loads((ROOT / acq['state']['snapshot']).read_text())
    s0_path = (acq.get('s0') or {}).get('snapshot')
    s0 = json.loads((ROOT / s0_path).read_text()) if s0_path else None
    vis_s1 = acq.get('visible') or {}          # 观察后（S1）可见量
    obs2 = ROOT / (acq.get('observation') or {}).get('dir', '')
    case = json.loads((ROOT / cfg['case_config']).read_text())
    budget = float(cfg.get('budget_s', 30.0))

    rec = {'schema': 'second-view-fair/v1', 'config': a.config, 'soil': a.soil,
           'seed': a.seed, 'state_S1': s1.get('state_hash'),
           'state_S0': (s0 or {}).get('state_hash'),
           'observation_S1': (acq.get('observation') or {}),
           'budget_s': budget, 'arms': {}}

    # 第一张图（S0 时刻既有观测）：该配置的主观测包
    obs1 = ROOT / (f"runs/unseen/delivery_v7/v7_20261030_r1/scan_obs2/{a.config}"
                   if a.config != 'R03_s1' else 'runs/unseen/recovery_r3/obs_R03')
    vis_first = json.loads((obs1 / 'observation.json').read_text()).get('visible') or {}
    rec['observation_S0_first_image'] = {'dir': str(obs1.relative_to(ROOT)),
                                         'visible': vis_first}

    # 假设 1：第一眼候选（A 与 C 共用，只用第一张图）
    first_dir = a.first_candidate or (
        f"{BATCH}/refuse_R02_s0.9" if a.config.startswith('R02')
        else f"{BATCH}/fusion_diagnostics/off1_R03_s1")
    h_first = admit(first_dir, CQ.load_observation_set(obs1), case, 'first_image')
    rec['hypothesis_first'] = h_first

    # 假设 2：用本次真实第二张图重建（B 专用）
    tv_dir, tv_meta = build_two_view(obs1, obs2, out_root / 'two_view', cfg)
    if tv_dir is not None:
        tv_meta['visible'] = measure_two_view_visibility(tv_dir, obs1)
    rec['two_view_build'] = tv_meta
    h_two = None
    if tv_dir is not None:
        h_two = admit(str(tv_dir.relative_to(ROOT)), CQ.load_observation_set(obs1), case,
                      'two_view_this_run')
        rec['hypothesis_two_view'] = h_two

    hyps_first = [{'id': 'first_image', 'kind': 'first_image',
                   'collision_dir': h_first['collision_dir']}]
    rec['arms']['A_S1_first_image'] = plan_and_execute(
        'A_S1_first_image', cfg, a.soil, a.seed, s1, vis_s1, hyps_first, out_root, budget)
    if h_two:
        hyps_two = [{'id': 'two_view', 'kind': 'two_view',
                     'collision_dir': h_two['collision_dir']}]
        rec['arms']['B_S1_second_image'] = plan_and_execute(
            'B_S1_second_image', cfg, a.soil, a.seed, s1, vis_s1, hyps_two, out_root, budget)
    else:
        rec['arms']['B_S1_second_image'] = {'arm': 'B', 'error': '两视角重建失败，未执行'}

    if s0 is None:
        rec['arms']['C_S0_direct'] = {'arm': 'C', 'error': '缺 S0 快照，未执行'}
    else:
        # C 只能使用 S0 时刻已有的信息：第一张图的可见量 + 第一眼假设
        rec['arms']['C_S0_direct'] = plan_and_execute(
            'C_S0_direct', cfg, a.soil, a.seed, s0, vis_first, hyps_first, out_root, budget)

    # 从 S0 起的总模拟时间：观察成本（S1 采集时的模拟时间）+ 各自执行时间
    obs_cost = float((acq.get('state') or {}).get('env_t') or 0.0)
    for name, arm in rec['arms'].items():
        if 'execution_sim_time_s' in arm:
            exec_t = float(arm['execution_sim_time_s'])
            arm['observation_sim_time_s'] = 0.0 if name.startswith('C_') else obs_cost
            arm['total_sim_time_from_S0_s'] = round(arm['observation_sim_time_s'] + exec_t, 4)
    rec['accounting'] = {
        'observation_sim_time_s': obs_cost,
        'note': ('从 S0 起算：A/B 含观察阶段模拟时间，C 不含；'
                 '不再用位移相减解释观察成本。')}
    (out_root / 'fair_ablation.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: {kk: v.get(kk) for kk in ('chosen', 'success', 'reason',
                                                   'total_sim_time_from_S0_s')}
                      for k, v in rec['arms'].items()}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
