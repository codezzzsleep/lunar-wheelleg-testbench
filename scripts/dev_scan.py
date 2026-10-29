"""
开发扫描：在真值上逐动作执行，找出"有行动取舍"的案例（工作线 A）。

  MUJOCO_GL=osmesa .venv/bin/python scripts/dev_scan.py --out runs/unseen/recovery_r3/devscan

设计（按 f8efba0 复核要求）：
  · 4 块**独立完整**程序化石头（圆钝/较长/扁平/棱角），各自独立种子与网格 SHA；
  · 每块 3 档统一缩放 -> 12 配置；
  · 每配置跑 8 个动作 × 3 个**实际初态** = 24 回合，第一轮上限 288；
  · 在真值上执行（开发诊断，可用真值），目的只是判断动作库有没有空间；
  · not_applicable 必须留记录与原因；实际运行数与预定总数分别统计；
  · 目标甲：R1 三初态至少 2 次失败，且某个非放弃动作 3/3 成功；
    目标乙：保守方法会绕行/停止，而真实几何存在更低代价的直通。
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
import terrain
import wheelleg_env
import runner as R
import skills

ROOT = pathlib.Path(__file__).resolve().parent.parent
ACTIONS = ('R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2', 'A0')
FAR, ABORT = 60.0, 40.0

# 四块石头：名称 -> (形状风格, 种子, 基础尺寸 H/W/D)
# 四块独立石头：覆盖 可跨越/窄高可跨骑/宽高需绕行/扁平回归
STONES = {
    's_round':   {'style': 'round',   'seed': 1101, 'H': 0.150, 'W': 0.360, 'D': 0.300},
    's_narrow':  {'style': 'angular', 'seed': 5505, 'H': 0.230, 'W': 0.165, 'D': 0.300},
    's_wide':    {'style': 'long',    'seed': 2202, 'H': 0.215, 'W': 0.560, 'D': 0.420},
    's_flat':    {'style': 'flat',    'seed': 3303, 'H': 0.100, 'W': 0.420, 'D': 0.340},
}
SCALES = (0.95, 1.10, 1.30)

# 第二轮：针对第一轮结论做定向扫描
#  - 第一轮 s_narrow@1.3 出现 R1 个别翻覆而 R2 3/3
#  - S1 从未触发：可见宽度都 >= 跨骑净空 CLR=0.1911，需要更窄的石头
STONES_R2 = {
    'r2_narrow_tall':  {'style': 'angular', 'seed': 6606, 'H': 0.240, 'W': 0.135, 'D': 0.260},
    'r2_narrow_mid':   {'style': 'round',   'seed': 7707, 'H': 0.190, 'W': 0.150, 'D': 0.280},
    'r2_narrow_short': {'style': 'flat',    'seed': 8808, 'H': 0.140, 'W': 0.160, 'D': 0.260},
}
SCALES_R2 = (1.0, 1.15, 1.30)


def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def make_stone(style, seed, H, W, D, out_dir):
    """
    生成独立的完整石头几何（不同种子 -> 不同形状）。

    用**闭合椭球参数化**（上下两极各一个顶点 + 中间环），拓扑上必然水密；
    形状扰动是低频谐波，保证不产生自交。石头底部自然是最低点，放在地面上。
    """
    rng = np.random.default_rng(seed)
    nu, nv = 40, 72                       # 环数、每环顶点数
    a, b, c = D / 2, W / 2, H / 2      # c 是半轴：总高 ≈ H
    if style == 'flat':
        c *= 0.85
    elif style == 'long':
        a *= 1.25
    elif style == 'angular':
        c *= 1.05
    k = {'round': 0.06, 'long': 0.08, 'flat': 0.05, 'angular': 0.15}[style]
    ph = rng.uniform(0, 2 * np.pi, 4)

    verts, faces = [], []
    verts.append([0.0, 0.0, c])                       # 北极
    for i in range(1, nu):
        u = np.pi * i / nu
        for j in range(nv):
            v = 2 * np.pi * j / nv
            r = 1.0 + k * (np.sin(3 * v + ph[0]) * np.sin(2 * u + ph[1])
                           + 0.6 * np.sin(3 * u + ph[2]))
            verts.append([a * r * np.sin(u) * np.cos(v),
                          b * r * np.sin(u) * np.sin(v),
                          c * r * np.cos(u)])
    verts.append([0.0, 0.0, -c])                      # 南极
    south = len(verts) - 1
    # 北极扇形
    for j in range(nv):
        faces.append([0, 1 + j, 1 + (j + 1) % nv])
    # 中间四边形带
    for i in range(nu - 2):
        base0 = 1 + i * nv
        base1 = base0 + nv
        for j in range(nv):
            j2 = (j + 1) % nv
            faces.append([base0 + j, base1 + j, base1 + j2])
            faces.append([base0 + j, base1 + j2, base0 + j2])
    # 南极扇形
    baseS = 1 + (nu - 2) * nv
    for j in range(nv):
        faces.append([south, baseS + (j + 1) % nv, baseS + j])

    m = trimesh.Trimesh(np.asarray(verts), np.asarray(faces), process=True)
    m.merge_vertices()
    m.apply_translation([0, 0, -float(m.bounds[0][2])])
    d = pathlib.Path(out_dir); d.mkdir(parents=True, exist_ok=True)
    p = d / 'body.stl'
    m.export(p)
    return m, p, _sha(p)


def world_asset(mesh, out_dir, scale, x, obstacle=True):
    d = pathlib.Path(out_dir); d.mkdir(parents=True, exist_ok=True)
    m = mesh.copy()
    m.apply_scale(scale)
    m.apply_translation([x, 0.0, 0.0])
    m.apply_translation([0, 0, -float(m.bounds[0][2])])
    p = d / 'body.stl'
    m.export(p)
    sha = _sha(p)
    (d / 'manifest.json').write_text(json.dumps({
        'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
        'parts': ['body.stl'], 'world_sha': sha, 'source_kind': 'truth' if obstacle else 'other'},
        indent=2))
    return d, sha


def spec_for(world_dir, case, seed, goal_x=2.6):
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=goal_x,
                             name=pathlib.Path(world_dir).name)
    spec['channel'] = {'center_y': 0.0,
                       'half_width': float(case.get('channel_half', 1.2))}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['objects'] = [{'posed_dir': str(world_dir)}]
    return spec


def run_one(world_dir, case, action, seed, vis, goal_x=2.6):
    env = wheelleg_env.WheelLegEnv(spec_for(world_dir, case, seed, goal_x),
                                   control_hz=50.0, max_seconds=15.0,
                                   v_ref=1.0, tip_deg=60.0)
    r = R.EpisodeRunner(env, skills.make_skill(action), visible=vis, seed=seed)
    out = r.run_with_seed(seed)
    return {'action': action, 'seed': seed, 'reason': out['reason'],
            'success': out['success'], 'abort': out['abort'],
            't_end': out['t_end'], 'final_x': out['final_x'],
            'max_tilt': out['max_tilt'], 'contact': out['contact'],
            'belly': out['belly_contact'], 'triggered': out['triggered'],
            'phases': out['phases'], 'fp': out['action_fingerprint'],
            'sim_time_s': round(float(env.t), 4),
            'control_steps': out['steps'], 'physics_steps': int(env.n_physics),
            'cost': (out['t_end'] if out['success']
                     else (ABORT if out['abort'] else FAR))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-episodes', type=int, default=288)
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--x', type=float, default=1.8)
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--round2', action='store_true',
                    help='运行第二轮定向扫描（窄石 + 跨骑判定）')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)

    case = {'channel_half': 1.2}
    stones = STONES_R2 if a.round2 else STONES
    scales = SCALES_R2 if a.round2 else SCALES
    planned = len(stones) * len(scales) * len(ACTIONS) * len(a.seeds)
    rows, stone_meta = [], {}
    n_run = 0
    for name, cfg in stones.items():
        mesh, base_p, base_sha = make_stone(cfg['style'], cfg['seed'], cfg['H'],
                                            cfg['W'], cfg['D'], out / 'stones' / name)
        stone_meta[name] = {'style': cfg['style'], 'seed': cfg['seed'],
                            'base_mesh_sha': base_sha,
                            'base_extents': [round(float(x), 5) for x in mesh.extents]}
        for sc in scales:
            tag = f'{name}@{sc:.2f}'
            wd, wsha = world_asset(mesh, out / 'truth' / f'{name}_{sc:.2f}', sc, a.x)
            col, cman = world_asset(mesh, out / 'collision' / f'{name}_{sc:.2f}', sc, a.x)
            cfg_rec = {'stone': name, 'scale': sc, 'world_sha': wsha,
                       'collision_sha': cman}
            # 公开可见量：从该配置的几何直接量（开发诊断允许用真值量观测）
            m2 = mesh.copy(); m2.apply_scale(sc)
            vis = {'W_vis': float(m2.extents[1]), 'H_vis': float(m2.extents[2]),
                   'x_front': float(a.x - m2.extents[0] / 2)}
            for act in ACTIONS:
                app = True
                why = None
                sk = skills.make_skill(act)
                if hasattr(sk, 'applicable'):
                    try:
                        app = bool(sk.applicable(vis, case['channel_half'])) \
                            if act.startswith('D') else bool(sk.applicable(vis))
                    except TypeError:
                        app = bool(sk.applicable(vis))
                    if not app:
                        why = 'not_applicable_by_public_visibility'
                for sd in a.seeds:
                    if n_run >= a.max_episodes:
                        rows.append({**cfg_rec, 'action': act, 'seed': sd,
                                     'skipped': 'episode_budget_reached'})
                        continue
                    if not app:
                        rows.append({**cfg_rec, 'action': act, 'seed': sd,
                                     'skipped': why, 'cost': None})
                        continue
                    r = run_one(wd, case, act, sd, vis, a.goal_x)
                    r.update(cfg_rec)
                    rows.append(r)
                    n_run += 1

    # ---- 目标判定 ----
    def per_cfg(rows):
        by = {}
        for r in rows:
            if r.get('skipped'):
                continue
            by.setdefault((r['stone'], r['scale'], r['action']), []).append(r)
        return by

    by = per_cfg(rows)
    target_a, target_b = [], []
    for (stone, sc, act), rs in by.items():
        if act != 'R1' or len(rs) != len(a.seeds):
            continue
        r1_fail = sum(1 for r in rs if not r['success'])
        # 记录所有 R1 有失败且其它动作全通过的配置（含 1 次失败的部分达成）
        for other in ('R2', 'L1', 'L2', 'S1', 'D1', 'D2'):
            o = by.get((stone, sc, other), [])
            if r1_fail >= 1 and len(o) == len(a.seeds) and all(x['success'] for x in o):
                target_b.append({'kind': 'r1_less_robust', 'stone': stone, 'scale': sc,
                                 'r1_fail': r1_fail, 'passing_action': other,
                                 'r1_cost': round(float(np.mean([x['cost'] for x in rs])), 3),
                                 'alt_cost': round(float(np.mean([x['cost'] for x in o])), 3)})
        if r1_fail < 2:
            continue
        for other in ('R2', 'L1', 'L2', 'S1', 'D1', 'D2'):
            o = by.get((stone, sc, other), [])
            if len(o) == len(a.seeds) and all(x['success'] for x in o):
                target_a.append({'stone': stone, 'scale': sc, 'r1_fail': r1_fail,
                                 'passing_action': other,
                                 'mean_cost': round(float(np.mean([x['cost'] for x in o])), 3),
                                 'r1_mean_cost': round(float(np.mean([x['cost'] for x in rs])), 3)})
    for (stone, sc, act), rs in by.items():
        if act in ('S1', 'D1', 'D2', 'A0'):
            continue
        o = by.get((stone, sc, 'S1'), [])
        if o and all(x['success'] for x in rs) and all(x['success'] for x in o):
            c_direct = float(np.mean([x['cost'] for x in rs]))
            c_s1 = float(np.mean([x['cost'] for x in o]))
            if c_s1 > c_direct * 1.3:
                target_b.append({'stone': stone, 'scale': sc, 'direct': act,
                                 'direct_cost': round(c_direct, 3),
                                 's1_cost': round(c_s1, 3)})

    summary = {
        'version': 'dev-scan/v1', 'planned_episodes': planned,
        'actual_episodes': n_run,
        'not_applicable': sum(1 for r in rows if r.get('skipped')),
        'round': 2 if a.round2 else 1,
        'stones': stone_meta, 'scales': list(scales), 'actions': list(ACTIONS),
        'seeds': a.seeds, 'x': a.x, 'goal_x': a.goal_x,
        'target_a_cases': target_a, 'target_b_cases': target_b,
        'note': ('开发诊断：在真值上逐动作执行，可用真值；不是盲规划器，'
                 '也不保证生成模型能解决这些案例'),
    }
    (out / 'scan.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({'planned': planned, 'actual': n_run,
                      'not_applicable': summary['not_applicable'],
                      'target_a': target_a[:3], 'n_target_a': len(target_a),
                      'n_target_b': len(target_b)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
