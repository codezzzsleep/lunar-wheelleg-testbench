"""
完整"再看一眼"链路：

  首视角观测 → 行驶观察位（真实物理）→ 真实第二观测
  → 用第二观测筛选候选 → 从**观察后状态**重建预演 → 冻结决策
  → 在当前真实环境**继续执行**（不 reset）

  MUJOCO_GL=osmesa .venv/bin/python scripts/look_again_loop.py \
      --case cases/unseen_v1/R01.json --obs runs/unseen/recovery_r3/obs_R01 \
      --candidates runs/unseen/recovery_r3/pipeline_fixture_R01/collision \
      --out runs/unseen/recovery_r3/look_loop_R01 --seed 0

要点：
  · 第二观测来自真实行驶后的机位（不是候选自己两张图）；
  · 筛选判据是候选轮廓与**真实第二观测**的 IoU；
  · 不稳定 / 目标丢失 / 裁切 -> 立即停止筛选，候选记 not_evaluated；
  · 预演从观察后状态开始（env.restore_state），不是出生状态；
  · 决策先落盘再执行；执行在真值场景**当前状态**继续，不 reset；
  · 总成本包含观察移动与刹车时间。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import actions as ACT
import camera_io
import drive_observe as DO
import mujoco
import skills
import terrain
import wheelleg_env
from runner import EpisodeRunner

ROOT = pathlib.Path(__file__).resolve().parent.parent
IOU_MIN = 0.85


def _spec(world, case, seed=0):
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=2.6, name='ll')
    spec['channel'] = {'center_y': 0.0, 'half_width': float(case.get('channel_half', 1.2))}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    spec['objects'] = [{'posed_dir': str(world)}]
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--obs', required=True)
    ap.add_argument('--candidates', required=True,
                    help='候选碰撞部件目录的父目录（每个候选一个子目录）')
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--camera-height', type=float, default=0.32)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    case = json.loads(pathlib.Path(a.case).read_text())
    obs = json.loads((pathlib.Path(a.obs) / 'observation.json').read_text())
    vis = obs['visible']
    cands = sorted(p for p in pathlib.Path(a.candidates).iterdir() if p.is_dir())
    rec = {'workflow': 'look_again_loop/v1', 'seed': a.seed,
           'candidates_in': [c.name for c in cands],
           'criteria': {'iou_min': IOU_MIN, 'min_target_px': DO.MIN_TARGET_PX,
                        'stable': 'v_lin<%.2f v_ang<%.2f tilt<%.0f hold>=%.1fs'
                                  % (DO.STABLE_V_LIN, DO.STABLE_V_ANG,
                                     DO.STABLE_TILT_DEG, DO.STABLE_HOLD_S)}}

    # ---------- 1. 首视角 + 真实行驶观察 ----------
    PROTO = json.loads((ROOT / 'configs/unseen_phase_protocol_v2.json').read_text())
    TOTAL_S = float(PROTO['total_task_seconds'])
    rec['phase_protocol'] = PROTO['version']
    rec['total_task_seconds'] = TOTAL_S
    env = wheelleg_env.WheelLegEnv(_spec_world(case), max_seconds=TOTAL_S)
    env.reset(seed=a.seed)
    cid = DO.set_cam_height(env, a.camera_height)
    v1 = DO.capture(env, cid, out / 'view1.png')
    front = float(case['obstacle_x']) - float(case['D']) / 2.0
    target_y = float(np.clip(0.30, 0.10, float(case.get('channel_half', 1.2)) - 0.30))
    move_s, move_reason = DO.drive_to_nav(env, target_y, stop_x=front - 0.42 - 0.78)
    st = DO.brake_and_settle(env)
    v2 = DO.capture(env, cid, out / 'view2.png')
    snapshot = env.save_state()
    rec['observation'] = {
        'move_seconds': move_s, 'move_stop_reason': move_reason,
        'brake': st, 'view1_mask_px': v1['mask_px'], 'view2_mask_px': v2['mask_px'],
        'cam_baseline_m': round(float(np.linalg.norm(
            np.asarray(v2['snapshot']['world_pos']) - np.asarray(v1['snapshot']['world_pos']))), 3),
        'state_hash': snapshot['state_hash'], 'env_t': snapshot['env_t']}
    usable = (st['stable'] and v2['mask_px'] >= DO.MIN_TARGET_PX
              and v2['depth_valid_frac'] >= DO.MIN_DEPTH_FRAC)
    rec['observation']['usable'] = bool(usable)

    if not usable:
        rec['outcome'] = 'observation_failed'
        rec['screening'] = [{'candidate': c.name, 'status': 'not_evaluated'} for c in cands]
        (out / 'look_loop.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        print(json.dumps({'outcome': rec['outcome'],
                          'reason': st.get('stable'), 'mask': v2['mask_px']},
                         ensure_ascii=False))
        return 0

    # ---------- 2. 用真实第二观测筛选候选 ----------
    per = []
    for c in cands:
        e2 = wheelleg_env.WheelLegEnv(_spec(c, case), max_seconds=TOTAL_S)
        e2.reset(seed=a.seed)
        # 关键：恢复到**观察后**状态（不是出生状态）
        e2.restore_state(dict(snapshot))
        cid2 = mujoco.mj_name2id(e2.model, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
        camera_io.restore(e2.model, e2.data, cid2, v2['snapshot'])
        cv = DO.capture(e2, cid2, out / f'{c.name}_view2.png')
        inter = int((cv['mask'] & v2['mask']).sum())
        union = int((cv['mask'] | v2['mask']).sum()) or 1
        iou = inter / union
        kept = bool(cv['mask_px'] > 300 and iou >= IOU_MIN)
        per.append({'candidate': c.name, 'mask_px': cv['mask_px'],
                    'iou_vs_real_view2': round(float(iou), 4), 'kept': kept,
                    'status': 'kept' if kept else 'rejected_by_second_view'})
    rec['screening'] = per
    kept = [c for c in cands if any(p['candidate'] == c.name and p['kept'] for p in per)]
    rec['kept'] = [c.name for c in kept]

    if not kept:
        rec['outcome'] = 'all_candidates_rejected'
        (out / 'look_loop.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        print(json.dumps({'outcome': rec['outcome'], 'kept': []}, ensure_ascii=False))
        return 0

    # ---------- 3. 从观察后状态重建预演 ----------
    options = [o for o in ACT.OPTIONS]
    reh = []
    for c in kept:
        for o in options:
            ok, why = ACT.applicable(o, vis, case.get('channel_half', 1.2))
            if not ok:
                reh.append({'candidate': c.name, 'option': o, 'not_applicable': why,
                            'success': False, 'cost': None})
                continue
            e3 = wheelleg_env.WheelLegEnv(_spec(c, case), max_seconds=TOTAL_S)
            e3.reset(seed=a.seed)
            e3.restore_state(dict(snapshot))        # 观察后状态
            r = EpisodeRunner(e3, skills.make_skill(o), visible=vis, seed=a.seed)
            o_ = r.run_from_state(dict(snapshot))
            reh.append({'candidate': c.name, 'option': o, 'reason': o_['reason'],
                        'success': o_['success'], 'abort': o_['abort'],
                        't_end': o_['t_end'], 't_start': o_['t_start'],
                        'cost': (o_['t_end'] if o_['success'] else
                                 (40.0 if o_['abort'] else 60.0)),
                        'continuing_from': o_['continuing_from']})
    (out / 'rehearsal_from_state.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in reh) + '\n')

    # ---------- 4. 冻结决策 ----------
    safe = {}
    for r in reh:
        if r.get('not_applicable') or r['option'] == ACT.FALLBACK:
            continue
        safe.setdefault(r['option'], []).append(r)
    cand_ok = [o for o, rs in safe.items() if all(x['success'] for x in rs)]
    if cand_ok:
        best = min(cand_ok, key=lambda o: max(x['cost'] for x in safe[o]))
        dec = {'chosen': best,
               'rule': 'worst-case over kept candidates; observations included in cost',
               'n_options': len(cand_ok)}
    else:
        dec = {'chosen': ACT.FALLBACK,
               'rule': 'no non-fallback option passed on every kept candidate'}
    # 成本口径（修正重复计）：
    #   成功 cost = t_end，而 t_end 是**绝对时间**（已含观察阶段），所以再加观察时间会重复。
    #   这里明确记录三项：观察耗时、执行耗时（t_end - t_start）、总耗时（观察 + 执行）。
    dec['observation_seconds'] = round(move_s + st['brake_seconds'], 3)
    if dec['chosen'] in safe:
        xs = safe[dec['chosen']]
        exec_cost = max(x['cost'] for x in xs)
        exec_seconds = max((x['t_end'] or 0) - (x['t_start'] or 0) for x in xs)
        dec['exec_cost_including_observation'] = exec_cost
        dec['exec_seconds'] = round(exec_seconds, 3)
        dec['total_seconds'] = round(dec['observation_seconds'] + exec_seconds, 3)
    else:
        dec['exec_cost_including_observation'] = 40.0
        dec['exec_seconds'] = None
        dec['total_seconds'] = None
    decp = out / 'decision.json'
    decp.write_text(json.dumps(dec, indent=2, ensure_ascii=False))
    import hashlib
    rec['decision'] = dec
    rec['decision_sha256'] = hashlib.sha256(decp.read_bytes()).hexdigest()

    # ---------- 5. 在真值场景**当前状态**继续执行 ----------
    ex = []
    for o in (dec['chosen'], 'R1'):
        e4 = wheelleg_env.WheelLegEnv(_spec_truth(case), max_seconds=TOTAL_S)
        e4.reset(seed=a.seed)
        # 执行端持有真值；状态从观察后继续（同一物理历史）
        e4.restore_state(dict(snapshot))
        r = EpisodeRunner(e4, skills.make_skill(o), visible=vis, seed=a.seed)
        o_ = r.run_from_state(dict(snapshot))
        ex.append({'option': o, 'reason': o_['reason'], 'success': o_['success'],
                   't_start': o_['t_start'], 't_end': o_['t_end'],
                   'first_frame_x': o_['q0'][0],
                   'continuing_from': o_['continuing_from']})
    rec['execution'] = ex
    rec['outcome'] = 'completed'
    (out / 'look_loop.json').write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(json.dumps({'outcome': rec['outcome'], 'kept': rec['kept'],
                      'chosen': dec['chosen'],
                      'exec': [(e['option'], e['reason']) for e in ex]},
                     ensure_ascii=False))
    return 0


def _spec_world(case):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='ll')
    spec['channel'] = {'center_y': 0.0, 'half_width': float(case.get('channel_half', 1.2))}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    spec['objects'] = [{'mesh_file': str(pathlib.Path(case['mesh']).resolve()),
                        'x': case['obstacle_x'], 'y': 0.0, 'yaw_deg': 0.0,
                        'target_height_m': case['H']}]
    return spec


def _spec_truth(case):
    return _spec_world(case)


if __name__ == '__main__':
    sys.exit(main())
