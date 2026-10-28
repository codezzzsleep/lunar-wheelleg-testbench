"""
六方法评测器：每种方法各自规划 -> 在同一真值、同一实际初态上执行。

  MUJOCO_GL=osmesa .venv/bin/python scripts/eval_six.py \
      --protocol plans/unseen_v2_protocol.json --out runs/unseen/recovery_r3/six

方法（固定六种，不扩张）：
  B0_blind    盲走：只按 R1 直行
  B1_height   可见高度规则：按公开可见高度选直行/抬腿/刹停
  B2_box      方盒子：把障碍当成 W_vis × H_vis × D_prior 的盒子做预演
  B3_mirror   镜像补全：把可见前表面镜像到背面得到候选
  H5_lux3d    真实 Lux3D 多候选（只有合格候选时存在）
  U_truth     真实形状上限：拥有完整真值几何的规划方法

关键约束（E4 任务 7 / 10.2）：
  · 每个方法先用**它被允许的信息**产生 selected_action；
  · 然后所有方法在**同一个** truth_asset_sha、同一初态上执行；
  · 禁止把某方法自己的假设当作最终执行环境；
  · 预演不等于执行成绩。
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import trimesh
import wheelleg_env
import runner
import skills

ROOT = pathlib.Path(__file__).resolve().parent.parent
OPTIONS = ('R1', 'R2', 'L1', 'L2', 'A0')
FAR, ABORT = 60.0, 40.0


def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def make_world_dir(mesh, out_dir, name, kind):
    """把任意网格写成世界坐标资产（z_min=0，body identity）。"""
    d = pathlib.Path(out_dir) / name
    d.mkdir(parents=True, exist_ok=True)
    m = trimesh.load(str(mesh), force='mesh')
    m = m.copy()
    m.apply_translation([0, 0, -float(m.bounds[0][2])])
    body = d / 'body.stl'
    m.export(body)
    h = _sha(body)
    (d / 'manifest.json').write_text(json.dumps({
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'parts': ['body.stl'], 'world_sha': h, 'source_kind': kind}, indent=2))
    return d, h


def collisionize(world_body, out_dir, hid):
    d = pathlib.Path(out_dir) / hid
    subprocess.run([sys.executable, str(ROOT / 'scripts/physicalize.py'),
                    '--mesh', str(world_body), '--out', str(d),
                    '--hypothesis-id', hid, '--skip-probe'],
                   capture_output=True, text=True, cwd=str(ROOT))
    man = json.loads((d / 'manifest.json').read_text())
    return d, man


def run_episode(world_dir, option, seed, visible, goal_x, time_limit=15.0):
    """统一执行器：与 Gate P、H5 预演、真值执行完全同一套。"""
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=goal_x,
                             name=pathlib.Path(world_dir).name)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(world_dir)}]
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                   v_ref=1.0, tip_deg=60.0)
    r = runner.EpisodeRunner(env, skills.make_skill(option),
                             visible=visible or {}, seed=seed)
    out = r.run_with_seed(seed)
    return {'option': option, 'seed': seed, 'reason': out['reason'],
            'success': out['success'], 'abort': out['abort'],
            't_end': out['t_end'], 'final_x': out['final_x'],
            'max_tilt': out['max_tilt'], 'contact': out['contact'],
            'triggered': out['triggered'], 'phases': out['phases'],
            'action_fingerprint': out['action_fingerprint'],
            'sim_time_s': round(float(env.t), 4),
            'control_steps': out['steps'],
            'physics_steps': int(env.n_physics), 'q0': out['q0'],
            'cost': (out['t_end'] if out['success']
                     else (ABORT if out['abort'] else FAR))}


def choose_option(rehearsal, options=OPTIONS):
    """最坏情形规则：任一初态失败即不选；并列按名称排序（tie-break 不宣称更优）。"""
    by = {}
    for r in rehearsal:
        by.setdefault(r['option'], []).append(r)
    safe = []
    for o, rs in by.items():
        if o == 'A0':
            continue
        if all(x['success'] for x in rs):
            safe.append((o, max(x['cost'] for x in rs)))
    if not safe:
        return 'A0', 'no non-A0 option succeeded in every initial state', []
    best = min(c for _, c in safe)
    tied = sorted(o for o, c in safe if abs(c - best) < 1e-9)
    return tied[0], f'worst-case min cost {best:.3f}; tied={tied}', tied


# ---------------- 六个方法的规划器 ----------------
def plan_blind(env_ctx):
    return 'R1', {'rule': 'blind: always R1'}


def plan_height(env_ctx, cfg):
    """可见高度规则：用公开可见高度比决定直行/抬腿/刹停（阈值在开发集冻结）。"""
    H = env_ctx['H_vis']
    r = H / cfg['wheel_r']
    if r <= cfg['climb_direct']:
        return 'R1', {'rule': f'visible height ratio {r:.2f} <= {cfg["climb_direct"]}'}
    if r <= cfg['climb_leg']:
        return 'L1', {'rule': f'{cfg["climb_direct"]} < ratio {r:.2f} <= {cfg["climb_leg"]}'}
    return 'A0', {'rule': f'visible height ratio {r:.2f} > {cfg["climb_leg"]}'}


def plan_box(env_ctx, cfg, out_dir):
    """方盒子：W_vis × D_prior × H_vis 的盒子做预演（不读真值背面）。"""
    w = env_ctx['W_vis']; h = env_ctx['H_vis']; d_prior = cfg['box_depth_m']
    m = trimesh.creation.box(extents=(d_prior, w, h))
    m.apply_translation([env_ctx['x_front'], 0.0, h / 2])
    return make_world_dir_from_mesh(m, out_dir, 'box', 'box_prior')


def make_world_dir_from_mesh(mesh, out_dir, name, kind):
    d = pathlib.Path(out_dir) / name
    d.mkdir(parents=True, exist_ok=True)
    body = d / 'body.stl'
    mesh.export(body)
    h = _sha(body)
    (d / 'manifest.json').write_text(json.dumps({
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'parts': ['body.stl'], 'world_sha': h, 'source_kind': kind}, indent=2))
    return d, h


def plan_mirror(env_ctx, out_dir):
    """镜像补全：把观测可见点云沿 x_front 平面镜像，形成背面假设。"""
    pts = np.load(pathlib.Path(env_ctx['obs_dir']) / 'visible_points.npy')
    mir = pts.copy()
    mir[:, 0] = 2.0 * env_ctx['x_front'] - pts[:, 0]     # 关于 x=x_front 镜像
    both = np.vstack([pts, mir])
    import manifold3d as m3
    hm = m3.Manifold.hull_points(np.asarray(both, dtype=np.float32)).to_mesh()
    hull = trimesh.Trimesh(np.asarray(hm.vert_properties)[:, :3],
                           np.asarray(hm.tri_verts), process=True)
    hull.apply_translation([0, 0, -float(hull.bounds[0][2])])
    return make_world_dir_from_mesh(hull, out_dir, 'mirror', 'mirror_hypothesis')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    proto = json.loads(pathlib.Path(a.protocol).read_text())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)

    cfg = proto['height_rule']
    obs_dir = pathlib.Path(proto['observation_dir'])
    obs = json.loads((obs_dir / 'observation.json').read_text())
    vis = obs['visible']
    case = json.loads(pathlib.Path(proto['case']).read_text())
    goal_x = proto.get('goal_x', 2.6)
    seeds = proto['initial_states']
    ctx = {'obs_dir': str(obs_dir), 'H_vis': float(vis['H_vis']),
           'W_vis': float(vis['W_vis']), 'x_front': float(vis['x_front'])}

    # ---- 真值：只给执行端与上限方法 ----
    truth_src = pathlib.Path(case['mesh'])
    tm = trimesh.load(str(truth_src), force='mesh')
    tm = tm.copy()
    tm.apply_translation([case['obstacle_x'], 0.0, -float(tm.bounds[0][2])])
    truth_wd, truth_sha = make_world_dir_from_mesh(tm, out, 'truth', 'truth')
    truth_col, truth_man = collisionize(truth_wd / 'body.stl', out, 'truth_collision')

    records, decisions = [], []

    def rehearse_on(world_dir, method):
        rows = []
        for s in seeds:
            for o in OPTIONS:
                r = run_episode(world_dir, o, s, vis, goal_x)
                rows.append({'method': method, 'hypothesis': method,
                             'initial_state_id': f'seed{s}', **r})
        return rows

    # 1) 盲走
    dec, why = plan_blind(ctx)
    decisions.append({'method': 'B0_blind', 'selected_action': dec, 'evidence': why})
    records += rehearse_on(truth_col, 'B0_blind')      # 盲走无候选，直接在真值上跑

    # 2) 可见高度规则
    dec, why = plan_height(ctx, cfg)
    decisions.append({'method': 'B1_height', 'selected_action': dec, 'evidence': why})
    records += rehearse_on(truth_col, 'B1_height')

    # 3) 方盒子：先在盒子上预演，再在真值上执行
    box_wd, _ = plan_box(ctx, cfg, out / 'hyps')
    box_col, _ = collisionize(box_wd / 'body.stl', out / 'hyps', 'box_collision')
    reh = rehearse_on(box_col, 'B2_box')
    dec, why, tied = choose_option([r for r in reh if r['option'] != 'A0'])
    decisions.append({'method': 'B2_box', 'selected_action': dec, 'evidence': why,
                      'tied': tied, 'rehearsal_on': 'box_prior'})
    records += [r for r in rehearse_on(truth_col, 'B2_box') if r['option'] == dec]

    # 4) 镜像补全
    mir_wd, _ = plan_mirror(ctx, out / 'hyps')
    mir_col, _ = collisionize(mir_wd / 'body.stl', out / 'hyps', 'mirror_collision')
    reh = rehearse_on(mir_col, 'B3_mirror')
    dec, why, tied = choose_option(reh)
    decisions.append({'method': 'B3_mirror', 'selected_action': dec, 'evidence': why,
                      'tied': tied, 'rehearsal_on': 'mirror_hypothesis'})
    records += [r for r in rehearse_on(truth_col, 'B3_mirror') if r['option'] == dec]

    # 5) Lux3D 多候选
    cands = proto.get('candidates') or []
    if cands:
        per = []
        for c in cands:
            reh = rehearse_on(pathlib.Path(c['collision_dir']), f"H5_lux3d:{c['candidate_id']}")
            per.append({'candidate_id': c['candidate_id'], 'rows': reh})
        # 多假设：每个动作必须在所有候选、所有初态都通过
        merged = []
        for o in OPTIONS:
            rows_o = [r for p in per for r in p['rows'] if r['option'] == o]
            worst = max((r['cost'] for r in rows_o), default=FAR)
            merged.append({'option': o, 'success': all(r['success'] for r in rows_o),
                           'cost': worst})
        dec, why, tied = choose_option([{'option': m['option'],
                                         'success': m['success'],
                                         'cost': m['cost']} for m in merged])
        decisions.append({'method': 'H5_lux3d', 'selected_action': dec, 'evidence': why,
                          'tied': tied, 'candidates': [c['candidate_id'] for c in cands],
                          'rehearsal_on': 'independent Lux3D candidates'})
        records += [r for r in rehearse_on(truth_col, 'H5_lux3d') if r['option'] == dec]
    else:
        decisions.append({'method': 'H5_lux3d', 'selected_action': None,
                          'evidence': 'no planning_eligible Lux3D candidate',
                          'no_candidate': True})

    # 6) 真实形状上限：拥有完整真值几何
    reh = rehearse_on(truth_col, 'U_truth')
    dec, why, tied = choose_option(reh)
    decisions.append({'method': 'U_truth', 'selected_action': dec, 'evidence': why,
                      'tied': tied, 'rehearsal_on': 'full truth geometry'})
    records += [r for r in rehearse_on(truth_col, 'U_truth') if r['option'] == dec]

    # ---- 汇总：每个方法只在**真值**上的执行结果计入 ----
    summary = []
    for d in decisions:
        m = d['method']
        rows = [r for r in records if r['method'] == m and r.get('is_exec') is not False]
        # 执行行：方法在真值上、且 option == 选定动作
        ex = [r for r in rows if r['option'] == d['selected_action']]
        summary.append({'method': m, 'selected_action': d['selected_action'],
                        'n_exec': len(ex),
                        'success': sum(1 for r in ex if r['success']),
                        'abort': sum(1 for r in ex if r['abort']),
                        'fail': sum(1 for r in ex if not r['success'] and not r['abort']),
                        'mean_cost': (round(float(np.mean([r['cost'] for r in ex])), 3)
                                      if ex else None),
                        'outcomes': [r['reason'] for r in ex],
                        'no_candidate': d.get('no_candidate', False)})
    (out / 'records.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n')
    (out / 'decisions.json').write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    (out / 'summary.json').write_text(json.dumps({
        'protocol': a.protocol, 'truth_sha': truth_sha,
        'truth_collision_sha': truth_man.get('collision_sha'),
        'initial_states': seeds, 'n_initial_states': len(seeds),
        'methods': summary,
        'note': ('所有方法在同一 truth_sha 上执行；预演只在各自假设上进行，'
                 '不计入执行成绩')}, ensure_ascii=False, indent=2))
    print(json.dumps({'truth_sha': truth_sha[:12], 'methods': [
        {k: v for k, v in s.items() if k != 'outcomes'} for s in summary]},
        ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
