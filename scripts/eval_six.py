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
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import terrain
import trimesh
import wheelleg_env
import runner
import skills

ROOT = pathlib.Path(__file__).resolve().parent.parent
INIT_CFG = json.loads((ROOT / 'configs/unseen_initial_state_v5.json').read_text())
# 完整动作库（S1 跨骑、D1/D2 绕行按公开可见量判定适用性）
OPTIONS = ('R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2', 'A0')
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


def run_episode(world_dir, option, seed, visible, goal_x, time_limit=15.0,
                soil_mode='rigid'):
    """统一执行器：与 Gate P、H5 预演、真值执行完全同一套。"""
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=goal_x,
                             name=pathlib.Path(world_dir).name)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(world_dir)}]
    if soil_mode != 'rigid':
        import v7_soil
        _r = v7_soil.resolve(soil_mode)
        spec['soil'] = {'mode': 'soil', 'label': _r.get('label'), 'params': _r['params']}
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                   v_ref=1.0, tip_deg=60.0)
    r = runner.EpisodeRunner(env, skills.make_skill(option),
                             visible=visible or {}, seed=seed)
    started_at = time.time()
    out = r.run_with_seed(seed)
    finished_at = time.time()
    return {'phase': 'rehearsal', 'option': option, 'seed': seed,
            'started_at': started_at, 'finished_at': finished_at,
            'sim_time_s_': round(float(env.t), 4), 'reason': out['reason'],
            'success': out['success'], 'abort': out['abort'],
            't_end': out['t_end'], 'final_x': out['final_x'],
            'max_tilt': out['max_tilt'], 'contact': out['contact'],
            'triggered': out['triggered'], 'phases': out['phases'],
            'action_fingerprint': out['action_fingerprint'],
            'sim_time_s': round(float(env.t), 4),
            'control_steps': out['steps'],
            'physics_steps': int(env.n_physics), 'q0': out['q0'],
            'initial_full_hash': out.get('initial_full_hash'),
            'initial_qpos': out.get('initial_qpos'),
            'initial_qvel': out.get('initial_qvel'),
            'cost': (out['t_end'] if out['success']
                     else (ABORT if out['abort'] else FAR))}


def run_episode_from_env(env, option, seed, visible, goal_x, time_limit=15.0,
                         hid='episode', soil_mode='rigid', snapshot=None,
                         skill=None, state_mode='project'):
    """在**给定 env** 上跑一段；给了 snapshot 就从该快照续行（不 reset）。

    两种语义显式分开（任务书 §6.1）：
      · snapshot=None -> 新建 episode（会 reset）
      · snapshot 给了 -> 调用 runner.run_from_state，恢复后到第一执行帧之间不 reset
    action_id 不允许缺失：None 直接报错，不能悄悄变成 A0。
    """
    if option is None:
        raise ValueError('action_id 不能为 None（不能把 None 悄悄转成 A0）')
    r = runner.EpisodeRunner(env, skill or skills.make_skill(option),
                             visible=visible or {}, seed=seed)
    started_at = time.time()
    if snapshot is not None:
        out = r.run_from_state(snapshot, mode=state_mode)
        resumed = True
    else:
        env.reset(seed=seed)
        out = r.run()
        resumed = False
    finished_at = time.time()
    return [{'phase': 'rehearsal', 'hypothesis_id': hid, 'option': option, 'seed': seed,
             'resumed': resumed,
             'started_at': started_at, 'finished_at': finished_at,
             'sim_time_s_': round(float(env.t), 4), 'reason': out['reason'],
             'success': out['success'], 'abort': out['abort'], 't_end': out['t_end'],
             'final_x': out['final_x'], 'max_tilt': out['max_tilt'],
             'contact': out['contact'], 'triggered': out['triggered'],
             'phases': out['phases'], 'action_fingerprint': out['action_fingerprint'],
             'control_steps': out['steps'], 'physics_steps': int(env.n_physics),
             'q0': out['q0'], 't_start': out.get('t_start'),
             'initial_full_hash': out.get('initial_full_hash'),
             'cost': (out['t_end'] if out['success']
                      else (ABORT if out['abort'] else FAR))}]


def choose_option(rehearsal, options=OPTIONS):
    """最坏情形规则：任一初态失败即不选；并列按名称排序（tie-break 不宣称更优）。"""
    by = {}
    for r in rehearsal:
        by.setdefault(r['option'], []).append(r)
    safe = []
    for o, rs in by.items():
        if o == 'A0':
            continue
        rs = [x for x in rs if not x.get('not_applicable')]
        if not rs:
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


def plan_width_rule(env_ctx, cfg, actions_mod):
    """
    开发解释用的可见宽度规则：只用公开可见宽度与机器人净空决定是否跨骑。
    不是六方法之一，不进入正式对照表；用来回答"这一例是否只靠可见宽度就能解决"。
    """
    ok, why = actions_mod.applicable('S1', {'W_vis': env_ctx['W_vis']})
    if ok:
        return 'S1', {'rule': f"W_vis {env_ctx['W_vis']:.4f} < 净空 "
                              f"{actions_mod.describe()['straddle_threshold_m']} -> S1"}
    return 'R1', {'rule': f"W_vis {env_ctx['W_vis']:.4f} 不小于净空 -> 回退 R1"}


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
    """
    方盒子：W_vis × D_prior × H_vis。
    前表面必须与观测前沿对齐：中心 x = x_front + D/2（此前放在 x_front，
    导致盒子最前沿提前了 D/2=0.11 m，会改变接触时机）。
    """
    w = env_ctx['W_vis']; h = env_ctx['H_vis']; d_prior = cfg['box_depth_m']
    m = trimesh.creation.box(extents=(d_prior, w, h))
    cx = env_ctx['x_front'] + d_prior / 2.0
    m.apply_translation([cx, 0.0, h / 2])
    wd, sha = make_world_dir_from_mesh(m, out_dir, 'box', 'box_prior')
    meta = {'depth_prior_m': d_prior, 'front_face_x': round(env_ctx['x_front'], 5),
            'center_x': round(cx, 5), 'back_face_x': round(cx + d_prior / 2.0, 5),
            'note': '前表面与观测前沿对齐；背深来自冻结先验，不读真值'}
    return wd, meta


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
    """
    镜像补全：保留观测到的**前表面**，把未知部分补向遮挡侧（+x）。
    此前关于 x=x_front 平面反射，会把补出的几何放到机器人一侧
    （实测最前沿约 1.5667 m < 观测 1.68 m），不是"补到看不见的后部"。
    """
    pts = np.load(pathlib.Path(env_ctx['obs_dir']) / 'visible_points.npy')
    x_min = float(pts[:, 0].min())            # 最靠近机器人（观测前沿）
    x_max = float(pts[:, 0].max())            # 可见面最深点 = 分割平面
    depth = x_max - x_min
    mir = pts.copy()
    # 关于 x = x_max 镜像：镜像点必然落在 x >= x_max，即遮挡侧；可见前表面原样保留
    mir[:, 0] = 2.0 * x_max - pts[:, 0]
    both = np.vstack([pts, mir])
    meta = {'split_plane_x': round(x_max, 5), 'front_x': round(x_min, 5),
            'visible_depth_m': round(depth, 5),
            'min_x_before': round(x_min, 5),
            'mirrored_min_x': round(float(mir[:, 0].min()), 5),
            'note': '保留观测前表面；未知部分关于最深可见点补向 +x（遮挡侧），不读真值中心/背深'}
    import manifold3d as m3
    hm = m3.Manifold.hull_points(np.asarray(both, dtype=np.float32)).to_mesh()
    hull = trimesh.Trimesh(np.asarray(hm.vert_properties)[:, :3],
                           np.asarray(hm.tri_verts), process=True)
    hull.apply_translation([0, 0, -float(hull.bounds[0][2])])
    wd, sha = make_world_dir_from_mesh(hull, out_dir, 'mirror', 'mirror_hypothesis')
    meta['hull_min_x'] = round(float(hull.bounds[0][0]), 5)
    meta['hull_max_x'] = round(float(hull.bounds[1][0]), 5)
    return wd, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--time-limit', type=float, default=30.0,
                    help='统一物理任务时限（V5 默认 30 s；旧 six_v4 是 15 s）')
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
    val_seeds = proto.get('validation_states') or []
    run_val = bool(val_seeds) and not proto.get('disable_validation')
    ctx = {'obs_dir': str(obs_dir), 'H_vis': float(vis['H_vis']),
           'W_vis': float(vis['W_vis']), 'x_front': float(vis['x_front'])}

    # ---- 真值：只给执行端与上限方法 ----
    truth_src = pathlib.Path(case['mesh'])
    tm = trimesh.load(str(truth_src), force='mesh')
    tm = tm.copy()
    tm.apply_translation([case['obstacle_x'], 0.0, -float(tm.bounds[0][2])])
    truth_wd, truth_sha = make_world_dir_from_mesh(tm, out, 'truth', 'truth')
    truth_col, truth_man = collisionize(truth_wd / 'body.stl', out, 'truth_collision')
    truth_col_sha = truth_man.get('collision_sha')
    if not truth_col_sha:
        raise SystemExit('真值碰撞化失败：manifest 无 collision_sha')

    records, decisions = [], []
    phy = {'control_hz': 50.0, 'substeps': None, 'soil_mode': proto.get('soil_mode', 'rigid'),
           'physics_dt_s': None}

    def initial_hash(env_world, seed):
        """同一候选/真值下，reset(seed) 得到的实际初态哈希（qpos，兼容旧记录）。"""
        e = wheelleg_env.WheelLegEnv(_spec_for(env_world, case, goal_x))
        e.reset(seed=seed)
        return hashlib.sha256(
            np.asarray(e.data.qpos, dtype=np.float64).tobytes()).hexdigest()[:16]

    def initial_full_hash(env_world, seed):
        """qpos+qvel 的完整初态哈希（V5：不只 q0/qpos）。"""
        e = wheelleg_env.WheelLegEnv(_spec_for(env_world, case, goal_x))
        e.reset(seed=seed)
        h = hashlib.sha256()
        h.update(np.asarray(e.data.qpos, dtype=np.float64).tobytes())
        h.update(np.asarray(e.data.qvel, dtype=np.float64).tobytes())
        return h.hexdigest()[:16]

    def _spec_for(world_dir, case, gx):
        spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=gx,
                                 name=pathlib.Path(world_dir).name)
        spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
        spec['init_perturbation'] = {'lateral_m': float(INIT_CFG['lateral_m']),
                                     'yaw_rad': float(INIT_CFG['yaw_rad'])}
        spec['skill_cfg'] = {'task': 'M', 'require_contact': False,
                             'settle_seconds': 1.0}
        spec['objects'] = [{'posed_dir': str(world_dir)}]
        if phy['soil_mode'] != 'rigid':
            import v7_soil
            _r = v7_soil.resolve(phy['soil_mode'])
            spec['soil'] = {'mode': 'soil', 'label': _r.get('label'), 'params': _r['params']}
        return spec

    def applicability():
        """按公开可见量判定每个动作是否适用（不读隐藏背深/类型）。"""
        out = {}
        for o in OPTIONS:
            if o == 'A0':
                out[o] = (True, None)
                continue
            sk = skills.make_skill(o)
            if hasattr(sk, 'applicable'):
                try:
                    ok = bool(sk.applicable(vis, case.get('channel_half', 1.2))) \
                        if o.startswith('D') else bool(sk.applicable(vis))
                except TypeError:
                    ok = bool(sk.applicable(vis))
                out[o] = (ok, None if ok else 'not_applicable_by_public_visibility')
            else:
                out[o] = (True, None)
        return out

    APPLY = applicability()
    phy['applicability'] = {k: v[0] for k, v in APPLY.items()}

    def rehearse_on(world_dir, method, phase, env_kind, env_sha):
        rows = []
        for s_ in seeds:
            ish = initial_hash(world_dir, s_)
            ifh = initial_full_hash(world_dir, s_)
            for o in OPTIONS:
                if not APPLY[o][0]:
                    rows.append({'method': method, 'phase': phase,
                                 'hypothesis': method, 'option': o,
                                 'initial_state_id': f'seed{s_}',
                                 'initial_state_hash': ish,
                                 'initial_full_hash': ifh,
                                 'environment_kind': env_kind,
                                 'environment_sha': env_sha,
                                 'truth_sha': truth_sha if env_kind == 'truth' else None,
                                 'soil_mode': phy['soil_mode'],
                                 'not_applicable': APPLY[o][1],
                                 'success': False, 'abort': False,
                                 'reason': APPLY[o][1], 'cost': None})
                    continue
                r = run_episode(world_dir, o, s_, vis, goal_x,
                                time_limit=a.time_limit, soil_mode=phy['soil_mode'])
                row = dict(r)
                row.update({'method': method, 'phase': phase,
                            'hypothesis': method,
                            'initial_state_id': f'seed{s_}',
                            'initial_state_hash': ish,
                            'initial_full_hash': ifh,
                            'environment_kind': env_kind,
                            'environment_sha': env_sha,
                            'truth_sha': truth_sha if env_kind == 'truth' else None,
                            'soil_mode': phy['soil_mode']})
                rows.append(row)
        return rows

    def execute_on_truth(method, dec, env_sha):
        """只保存实际被选动作在真值上的回合。"""
        rows = []
        if dec is not None and not APPLY.get(dec, (True, None))[0]:
            return rows
        for s_ in seeds:
            ish = initial_hash(truth_col, s_)
            ifh = initial_full_hash(truth_col, s_)
            r = run_episode(truth_col, dec, s_, vis, goal_x,
                            time_limit=a.time_limit, soil_mode=phy['soil_mode'])
            row = dict(r)
            row.update({'method': method, 'phase': 'execution',
                        'hypothesis': method, 'initial_state_id': f'seed{s_}',
                        'initial_state_hash': ish,
                        'initial_full_hash': ifh,
                        'environment_kind': 'truth', 'environment_sha': truth_sha,
                        'truth_sha': truth_sha, 'truth_collision_sha': env_sha,
                        'soil_mode': phy['soil_mode']})
            rows.append(row)
        return rows

    pending = []          # (method, action) 待执行；决策全部落盘后才执行真值
    dec_sha_holder = {}

    # 0) 开发解释用诊断：可见宽度规则（不进正式 methods 表）
    import actions as ACT
    dec_w, why_w = plan_width_rule(ctx, cfg, ACT)
    w_rows = execute_on_truth('W_width_rule(diagnostic)', dec_w, truth_col_sha)
    (out / 'width_rule_diagnostic.json').write_text(json.dumps({
        'label': 'DEVELOPMENT_DIAGNOSTIC', 'not_a_formal_method': True,
        'selected_action': dec_w, 'evidence': why_w,
        'n_exec': len(w_rows),
        'success': sum(1 for r in w_rows if r['success']),
        'mean_cost': (round(float(np.mean([r['cost'] for r in w_rows])), 3)
                      if w_rows else None),
        'note': '只回答"是否仅靠可见宽度就能选对动作"；不替换六方法'},
        ensure_ascii=False, indent=2))
    records += w_rows

    # 1) 盲走：规则直接定动作，不需要在真值上试遍所有动作
    dec, why = plan_blind(ctx)
    decisions.append({'method': 'B0_blind', 'selected_action': dec, 'evidence': why,
                      'planning_inputs': ['no candidate']})
    pending.append(('B0_blind', dec))

    # 2) 可见高度规则
    dec, why = plan_height(ctx, cfg)
    decisions.append({'method': 'B1_height', 'selected_action': dec, 'evidence': why,
                      'planning_inputs': ['H_vis', 'wheel_r', 'frozen thresholds']})
    pending.append(('B1_height', dec))

    # 3) 方盒子：盒子前表面与观测前沿对齐
    box_wd, box_meta = plan_box(ctx, cfg, out / 'hyps')
    box_col, box_man = collisionize(box_wd / 'body.stl', out / 'hyps', 'box_collision')
    reh = rehearse_on(box_col, 'B2_box', 'rehearsal', 'box_prior', box_man.get('collision_sha'))
    dec, why, tied = choose_option(reh)
    decisions.append({'method': 'B2_box', 'selected_action': dec, 'evidence': why,
                      'tied': tied, 'rehearsal_on': 'box_prior',
                      'rehearsal_environment_sha': box_man.get('collision_sha'),
                      'hypothesis_geometry': box_meta,
                      'planning_inputs': ['W_vis', 'H_vis', 'x_front', 'frozen depth prior']})
    records += reh
    pending.append(('B2_box', dec))

    # 4) 镜像补全：保留观测前表面，未知部分补向遮挡侧
    mir_wd, mir_meta = plan_mirror(ctx, out / 'hyps')
    mir_col, mir_man = collisionize(mir_wd / 'body.stl', out / 'hyps', 'mirror_collision')
    reh = rehearse_on(mir_col, 'B3_mirror', 'rehearsal', 'mirror_hypothesis',
                      mir_man.get('collision_sha'))
    dec, why, tied = choose_option(reh)
    decisions.append({'method': 'B3_mirror', 'selected_action': dec, 'evidence': why,
                      'tied': tied, 'rehearsal_on': 'mirror_hypothesis',
                      'rehearsal_environment_sha': mir_man.get('collision_sha'),
                      'hypothesis_geometry': mir_meta,
                      'planning_inputs': ['visible point cloud (disclosed)']})
    records += reh
    pending.append(('B3_mirror', dec))

    # 5) Lux3D 多候选
    cands = proto.get('candidates') or []
    if cands:
        per, reh_all = [], []
        for c in cands:
            rows = rehearse_on(pathlib.Path(c['collision_dir']),
                               f"H5_lux3d", 'rehearsal', 'lux3d_candidate',
                               c.get('collision_sha'))
            for r_ in rows:
                r_['candidate_id'] = c['candidate_id']
            per.append({'candidate_id': c['candidate_id'], 'rows': rows})
            reh_all += rows
        merged = []
        for o in OPTIONS:
            rows_o = [r for r in reh_all if r['option'] == o]
            # not_applicable 行的 cost 是 None，必须排除后再取最大值
            costs = [r['cost'] for r in rows_o if r.get('cost') is not None]
            merged.append({'option': o,
                           'success': bool(rows_o) and all(r['success'] for r in rows_o),
                           'cost': (max(costs) if costs else FAR)})
        dec, why, tied = choose_option(merged)
        decisions.append({'method': 'H5_lux3d', 'selected_action': dec, 'evidence': why,
                          'tied': tied, 'candidates': [c['candidate_id'] for c in cands],
                          'rehearsal_on': 'independent Lux3D candidates',
                          'planning_inputs': ['RGB observation', 'candidate meshes']})
        records += reh_all
        pending.append(('H5_lux3d', dec))
    else:
        decisions.append({'method': 'H5_lux3d', 'selected_action': None,
                          'evidence': 'no planning_eligible Lux3D candidate',
                          'no_candidate': True, 'planning_inputs': []})

    # 6) 真实形状上限：拥有完整真值几何
    reh = rehearse_on(truth_col, 'U_truth', 'rehearsal', 'truth', truth_col_sha)
    dec, why, tied = choose_option(reh)
    decisions.append({'method': 'U_truth', 'selected_action': dec, 'evidence': why,
                      'tied': tied, 'rehearsal_on': 'full truth geometry',
                      'planning_inputs': ['full truth geometry (ceiling only)']})
    records += reh
    pending.append(('U_truth', dec))

    # ---- 验证初态（§15.3）：决策冻结后，在**未参与规划**的初态上执行同一批动作 ----
    def run_validation(dec_sha):
        """决策冻结后，在未参与规划的验证初态上执行同一批动作。"""
        out_rows = []
        if not run_val:
            return out_rows
        for method, dec in pending:
            for s_ in val_seeds:
                r = run_episode(truth_col, dec, s_, vis, goal_x, time_limit=a.time_limit,
                                soil_mode=phy['soil_mode'])
                row = dict(r)
                row.update({'method': method, 'phase': 'validation',
                            'hypothesis': method, 'initial_state_id': f'val_seed{s_}',
                            'environment_kind': 'truth', 'environment_sha': truth_sha,
                            'truth_sha': truth_sha, 'truth_collision_sha': truth_col_sha,
                            'soil_mode': phy['soil_mode'], 'decision_sha': dec_sha})
                out_rows.append(row)
        return out_rows

    # ---- 两阶段：决策先落盘并定身份，之后才允许真值执行（任务书 §8.1）----
    import hashlib as _h, time as _t
    _payload = json.dumps(decisions, ensure_ascii=False, sort_keys=True)
    dec_sha = _h.sha256(_payload.encode()).hexdigest()
    dec_written_at = _t.time()
    (out / 'decisions.json').write_text(json.dumps(
        {'schema': 'decision-list/v7', 'decision_sha': dec_sha,
         'written_at': dec_written_at, 'decisions': decisions},
        ensure_ascii=False, indent=2))
    dec_sha_holder['sha'] = dec_sha
    with (out / 'decision_events.jsonl').open('w') as f:
        f.write(json.dumps({'event': 'decisions_written', 'decision_sha': dec_sha,
                            'written_at': dec_written_at,
                            'n_methods': len(decisions)}, ensure_ascii=False) + '\n')

    for method, dec in pending:
        started = _t.time()
        rows = execute_on_truth(method, dec, truth_col_sha)
        for r in rows:
            r['decision_sha'] = dec_sha
            r['execution_started_at'] = started
        records += rows
        with (out / 'decision_events.jsonl').open('a') as f:
            f.write(json.dumps({'event': 'execution_started', 'decision_sha': dec_sha,
                                'method': method, 'started_at': started,
                                'after_decision_write': started > dec_written_at},
                               ensure_ascii=False) + '\n')

    records += run_validation(dec_sha)

    # ---- 汇总：只统计 phase=execution ----
    summary = []
    for d_ in decisions:
        m = d_['method']
        ex = [r for r in records if r['method'] == m and r['phase'] == 'execution']
        n_exp = len(seeds) if d_['selected_action'] else 0
        summary.append({'method': m, 'selected_action': d_['selected_action'],
                        'n_exec': len(ex), 'n_expected': n_exp,
                        'complete': len(ex) == n_exp,
                        'success': sum(1 for r in ex if r['success']),
                        'validation': {'n': sum(1 for r in records
                                                if r['method'] == m and r['phase'] == 'validation'),
                                       'success': sum(1 for r in records
                                                      if r['method'] == m
                                                      and r['phase'] == 'validation'
                                                      and r['success'])},
                        'n_validation_states': len(val_seeds),
                        'abort': sum(1 for r in ex if r['abort']),
                        'fail': sum(1 for r in ex if not r['success'] and not r['abort']),
                        'mean_cost': (round(float(np.mean([r['cost'] for r in ex])), 3)
                                      if ex else None),
                        'outcomes': [r['reason'] for r in ex],
                        'no_candidate': d_.get('no_candidate', False)})
    (out / 'records.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n')
    _now = json.loads((out / 'decisions.json').read_text())
    assert _now.get('decision_sha') == dec_sha, '决策文件在执行期间被改写'
    (out / 'summary.json').write_text(json.dumps({
        'protocol': a.protocol, 'truth_sha': truth_sha,
        'truth_collision_sha': truth_col_sha,
        'soil_mode': phy['soil_mode'],
        'time_limit_s': a.time_limit,
        'expected_keys': [{'method': d_['method'],
                           'initial_state_id': f'seed{s_}',
                           'n_expected': (len(seeds) if d_['selected_action'] else 0)}
                          for d_ in decisions for s_ in seeds],
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
