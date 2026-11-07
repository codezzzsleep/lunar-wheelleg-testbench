"""V7 遭遇决策：观测目录（局部坐标）+ Lux3D 候选 GLB -> decision.json。

全部调用已验证的模块，不重新实现：
  栅格/观测体   v3_fuse.frozen_grid / observe_volume
  配准          v3_register.register
  准入          v5_core.admission_metrics + configs/v5_admission.json（冻结门槛）
  阴影          v5_core.shadow_mask
  预演          v5_eval.robust_arm（三次扰动、零机身接触、通道横向 5 cm 余量）
  绕行规划      v5_eval.plan_detour（每臂按自己的几何算偏移与回位点）

决策规则（SPEC V5 §2.7 / R1–R3）：
  FULL     每份准入候选各预演一次；多数（≥⌊n/2⌋+1）安全的动作中选平均代价最低者；同时报告最坏（n/n）。
  OBS_CONS 在 V∪U_shadow（看不见的当实心）与 Vsh（看不见的当空）两种几何上用同一份计划预演，取交集。
  零准入   FULL 回退到 OBS_CONS，记 fallback。
  轮子优先 代价相差 <5% 时选纯轮动作（R1/R2/D1/D2）。
"""
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_fuse, v3_register, v5_core as C, v5_metrics_ref as R, v5_eval as E, wheelleg_env  # noqa: E402

WHEEL = ('R1', 'R2', 'D1', 'D2')
PROTO = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
ADM = json.loads((ROOT / 'configs/v5_admission.json').read_text())
ACTIONS = [a for a in json.loads((ROOT / 'configs/stage6_protocol.json').read_text())['actions'] if a != 'CLIMB']
import os as _os
if _os.environ.get('V7_TEST_ACTIONS'):          # 仅供负责人在 2 核测试机上缩短测试；正式运行不得设置
    ACTIONS = [a for a in ACTIONS if a in _os.environ['V7_TEST_ACTIONS'].split(',')]


def plan_for(arm, low, detour):
    p = {'raise_z': 0.06, 'ramp_steps': 40, 'speed': 0.4, 'lower_at_x': round(float(low), 3), 'end_x': 2.6,
         'stop_tilt_deg': 12.0, 'far_edge_source': arm,
         'offset_m': detour['offset_m'], 'leave_x': detour['leave_x']}
    p['plan_id'] = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]
    return p


def admitted(m):
    return bool(ADM['scale_ratio']['min'] <= m['scale_ratio'] <= ADM['scale_ratio']['max']
                and m['hidden_frac'] >= ADM['hidden_frac_min'] and m['shell_contact'] >= ADM['shell_contact_min']
                and m['free_intrusion_frac'] <= ADM['free_intrusion_max'] and (m['contour_iou'] or 0) >= ADM['contour_iou_min'])


def build_volume(obs_dir, out):
    st = json.loads((pathlib.Path(obs_dir) / 'state.json').read_text())
    vis = st['visible']
    g = v3_fuse.frozen_grid(PROTO, vis)
    space, shell, stats, _ = v3_fuse.observe_volume(obs_dir, g, PROTO)
    fd = pathlib.Path(out) / 'fusion'; fd.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(fd / 'V.npz', shell=shell, space=space, origin=np.asarray(g['origin'], float),
                        pitch=np.float64(g['pitch']), dims=np.asarray(g['dims'], int))
    (fd / 'V.json').write_text(json.dumps({'stats': stats, 'visible': vis}, indent=2))
    V = dict(np.load(fd / 'V.npz'))
    return V, C.grid_from_V(V), vis, st


def local_snapshot(st, channel_half, V, out):
    """把停车时的机器人状态平移/转正到局部原点，作为预演的初始状态。
    快照必须来自与预演场景同构的环境（stage8 make_scene：同样的障碍 body 数、同样的月壤），否则状态长度不同。"""
    import mujoco
    import stage8_matrix2 as M
    yaw = st['local_frame']['yaw0']
    if abs(np.degrees(yaw)) > 5.0:       # 预演的扰动含 ±2°；停车偏航超过 5° 视为路线控制失败
        raise RuntimeError(f'stop yaw {np.degrees(yaw):.2f} deg > 5 deg; the route controller must stop square to the lane')
    sd = pathlib.Path(out) / 'snap'; sd.mkdir(parents=True, exist_ok=True)
    _, env, _ = M.make_scene(M.resample_walls(V['shell'], V['origin'], float(V['pitch'])), sd, 'snap', channel_half=channel_half)
    q = np.asarray(st['robot_qpos_world'], float).copy()
    w, x, y, z = q[3:7]                     # 去掉偏航，保留俯仰/横滚
    cy, sy = np.cos(-yaw / 2), np.sin(-yaw / 2)
    q[3:7] = [cy * w - sy * z, cy * x - sy * y, cy * y + sy * x, cy * z + sy * w]
    q[3:7] /= np.linalg.norm(q[3:7])
    q[0], q[1] = 0.0, 0.0
    env.data.qpos[:] = q; env.data.qvel[:] = 0.0
    mujoco.mj_forward(env.model, env.data)
    snap = env.save_state()
    return snap, (np.asarray(env.data.qpos, float).copy(), np.asarray(env.data.qvel, float).copy())


def choose(result, safe):
    c = [r for r in result if r['action'] in safe]
    if not c:
        return 'A0', []
    c.sort(key=lambda r: r['cost'])
    best = c[0]
    # 轮子优先：代价差 <5% 的范围内有纯轮动作就选它
    near = [r for r in c if r['cost'] <= best['cost'] * 1.05]
    wheel = [r for r in near if r['action'] in WHEEL]
    pick = (wheel[0] if wheel else best)['action']
    return pick, [{'action': r['action'], 'cost': r['cost']} for r in c]


def decide(obs_dir, glbs, out, channel_half=1.2, actions=None):
    """glbs: [{'id','glb'}]；返回并写出 decision.json（局部坐标）。"""
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    actions = actions or ACTIONS
    V, g, vis, st = build_volume(obs_dir, out)
    U = (V['space'] == 0); Vsh = V['shell']
    obs = v3_register.load_observation(str(obs_dir))
    sh = C.shadow_mask(V, g, obs)
    snap, ref = local_snapshot(st, channel_half, V, out)

    # ---- 候选：配准 -> 准入
    cands = []
    for c in glbs:
        rd = out / 'reg' / c['id']; rd.mkdir(parents=True, exist_ok=True)
        rec = v3_register.register(str(c['glb']), str(obs_dir), PROTO, rd, top_k=6)
        M = np.asarray(rec['best']['M'], float)
        mesh = trimesh.load(str(c['glb']), force='mesh', process=False)
        ev = v3_register.evaluate_matrix(mesh, obs, M)
        m = C.admission_metrics(mesh, M, V, g, ev)
        row = {k: v for k, v in m.items() if k != 'P'}
        row.update({'id': c['id'], 'glb': str(c['glb']), 'M': M.tolist(), 'admitted': admitted(m)})
        cands.append((row, m['P']))
    (out / 'candidates.json').write_text(json.dumps([r for r, _ in cands], indent=2))
    adm = [(r, P) for r, P in cands if r['admitted']]

    # ---- OBS_CONS：两种极端几何，同一份计划
    solid = Vsh | sh
    det_obs = E.plan_detour(solid, V, vis, channel_half)
    plan_obs = plan_for('OBS_CONS', 2.45, det_obs)
    acts_obs = [a for a in actions if det_obs['applicable'] or a not in ('D1', 'D2')]
    r_solid = E.robust_arm(solid, V, snap, ref, vis, plan_obs, acts_obs, out / 'OBS_CONS/solid', channel_half, tag='obs_solid')
    r_empty = E.robust_arm(Vsh, V, snap, ref, vis, plan_obs, acts_obs, out / 'OBS_CONS/empty', channel_half, tag='obs_empty')
    obs_safe = r_solid['safe'] & r_empty['safe']
    obs_pick, obs_rank = choose(r_solid['combined'], obs_safe)

    # ---- FULL：每份准入候选各自预演
    per = []
    for r, P in adm:
        occ = Vsh | (P & U)
        ax = (P & U).any(axis=(1, 2))
        low = float(g['xs'][ax].max()) + 0.10 if ax.any() else 2.45
        det = E.plan_detour(occ, V, vis, channel_half)
        plan = plan_for('FULL', low, det)
        acts = [a for a in actions if det['applicable'] or a not in ('D1', 'D2')]
        res = E.robust_arm(occ, V, snap, ref, vis, plan, acts, out / 'FULL' / r['id'], channel_half, tag=r['id'])
        per.append({'id': r['id'], 'safe': sorted(res['safe']), 'plan': plan,
                    'cost': {x['action']: x['cost'] for x in res['combined']}})
    n = len(per)
    if n:
        need = n // 2 + 1
        votes = {a: sum(a in p['safe'] for p in per) for a in actions}
        maj = {a for a, v in votes.items() if v >= need}
        worst = {a for a, v in votes.items() if v == n}
        mean_cost = [{'action': a, 'cost': float(np.mean([p['cost'][a] for p in per if a in p['safe']]))} for a in maj]
        full_pick, full_rank = choose(mean_cost, maj)
        worst_cost = [{'action': a, 'cost': float(np.mean([p['cost'][a] for p in per]))} for a in worst]
        worst_pick, _ = choose(worst_cost, worst)
        # 执行用的计划：取选中动作在各候选里的计划中，偏移最大、回位最晚的那份（偏保守）
        plans = [p['plan'] for p in per if full_pick in p['safe']]
        full_plan = max(plans, key=lambda p: (p['offset_m'], p['leave_x'])) if plans else plan_obs
        branch = 'accept'
    else:
        votes, full_pick, full_rank, worst_pick, full_plan, branch = {}, obs_pick, obs_rank, obs_pick, plan_obs, 'reject_all'

    dec = {'schema': 'v7-decision/v1', 'frame': 'local', 'local_frame': st['local_frame'], 'visible': vis,
           'channel_half': channel_half, 'branch': branch, 'actions': list(actions),
           'n_candidates': len(cands), 'n_admitted': n,
           'full': {'chosen': full_pick, 'worst_rule': worst_pick, 'votes': votes, 'ranked': full_rank,
                    'plan': full_plan, 'per_candidate': per,
                    'fallback': None if n else 'zero_admitted -> OBS_CONS'},
           'obs_cons': {'chosen': obs_pick, 'safe_solid': sorted(r_solid['safe']), 'safe_empty': sorted(r_empty['safe']),
                        'safe_both': sorted(obs_safe), 'ranked': obs_rank, 'plan': plan_obs},
           'shadow_voxels': int(sh.sum())}
    (out / 'decision.json').write_text(json.dumps(dec, indent=2))
    return dec


def to_world(dec, arm):
    """局部计划 -> 路线世界坐标（停车偏航 <5°，按平移换算；动作执行中车道跟随会把航向拉回）。"""
    lf = dec['local_frame']; x0, y0 = lf['x0'], lf['y0']
    d = dec['full'] if arm == 'FULL' else dec['obs_cons']
    p = dict(d['plan'])
    p['lower_at_x'] = p['lower_at_x'] + x0; p['end_x'] = p['end_x'] + x0; p['leave_x'] = p['leave_x'] + x0
    vis = dict(dec['visible']); vis['x_front'] = vis['x_front'] + x0; vis['y_center'] = vis['y_center'] + y0
    return d['chosen'], p, vis
