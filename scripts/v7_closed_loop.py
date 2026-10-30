"""
V7 §9：观察后的重规划与独立真值续行（闭环后半段）。

流程（与任务书一致）：
  1. 读取真实行驶观察留下的**完整状态合同**（env.save_state），严格恢复（哈希/签名/版本校验）；
  2. 用恢复后的状态，对"第二观察筛选后仍保留"的候选重新预演（观察后预演）；
  3. 用同一判据（worst-case-risk/v2）重新决策；
  4. 在**独立真值场景**里从同一状态续行执行该动作（不 reset，不换初态）；
  5. 记录：观察前决策、观察后决策、续行初始状态哈希、执行结果。

  .venv/bin/python scripts/v7_closed_loop.py \
      --drive runs/unseen/delivery_v7/v7_20261030/observation/drive_R03/drive_observe.json \
      --seed 0 --truth runs/unseen/recovery_r3/stone_materials/R03.stl \
      --hypotheses <json> --before <decisions.json> --out <dir>
"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import decision
import eval_six
import terrain
import wheelleg_env
import actions as ACT

OPTIONS = list(ACT.OPTIONS)


def build_env(obstacle_mesh, seed, goal_x, time_limit, soil_mode='rigid'):
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=goal_x, name='closed_loop')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}   # 初态由状态合同给出
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(obstacle_mesh)}]
    if soil_mode != 'rigid':
        spec['soil'] = {'mode': soil_mode}
    return wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                    v_ref=1.0, tip_deg=60.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--drive', required=True, help='drive_observe.json（含 env_state）')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--truth', required=True, help='真值 posed world 目录')
    ap.add_argument('--hypotheses', default=None, help='[{id, world}]（观察后仍保留的候选）')
    ap.add_argument('--screen', default=None,
                    help='second_view_screen.json；给了就只用 kept_by_second_view 的候选')
    ap.add_argument('--seeds', default='0,1,2', help='观察后预演用的初态编号（只用于多初态复核）')
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--time-limit', type=float, default=30.0)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    drv = json.loads((ROOT / a.drive).read_text())
    rec = next((r for r in drv.get('runs', []) if int(r.get('seed', -1)) == a.seed), None)
    if rec is None:
        raise SystemExit(f'drive 记录里没有 seed {a.seed}')
    if 'env_state' not in rec:
        raise SystemExit('drive 记录缺少 env_state（完整状态合同），不能续行')

    # ---- 1. 严格恢复 ----
    env = build_env(ROOT / a.truth, a.seed, a.goal_x, a.time_limit)
    env.reset(seed=a.seed)
    env.restore_state(rec['env_state'], strict=True)
    state0 = env.save_state()
    rows = [{'phase': 'restore', 'state_hash': state0.get('state_hash'),
             'mujoco_version': state0.get('mujoco_version'),
             'n_physics': state0.get('n_physics'), 'n_control': state0.get('n_control')}]

    # ---- 2/3. 观察后预演 + 重新决策 ----
    hyps = []
    kept_ids = None
    if a.screen:
        sc = json.loads((ROOT / a.screen).read_text())
        kept_ids = [r['candidate'] for r in sc.get('rows', []) if r.get('kept_by_second_view')]
    if a.hypotheses:
        hyps = json.loads((ROOT / a.hypotheses).read_text())
        if kept_ids is not None:
            hyps = [h for h in hyps if h['id'] in kept_ids]
    matrix = []
    for h in hyps:
        menv = build_env(ROOT / h['world'], a.seed, a.goal_x, a.time_limit)
        for sd in [int(x) for x in a.seeds.split(',')]:
            menv.reset(seed=sd)
            menv.restore_state(rec['env_state'], strict=True)
            vis = json.loads((ROOT / h['world'] / 'manifest.json').read_text())
            matrix += eval_six.run_episode_from_env(menv, None, sd, vis, a.goal_x,
                                                    a.time_limit, hid=h['id'])
    if hyps:
        dec_after = decision.evaluate(matrix, OPTIONS)
    else:
        dec_after = {'chosen': 'A0', 'safe_set': [],
                     'reason': 'no_candidate_after_second_view：第二观察后没有保留的候选'}
    rows += matrix

    # ---- 4. 独立真值续行 ----
    tenv = build_env(ROOT / a.truth, a.seed, a.goal_x, a.time_limit)
    tenv.reset(seed=a.seed)
    tenv.restore_state(rec['env_state'], strict=True)
    chosen = dec_after['chosen']
    exe = eval_six.run_episode_from_env(tenv, chosen, a.seed, {}, a.goal_x, a.time_limit,
                                        hid='TRUTH_continue')
    rows += exe

    payload = {
        'schema': 'closed-loop/v7',
        'drive': a.drive, 'seed': a.seed,
        'restored_state_hash': state0.get('state_hash'),
        'hypotheses_after_observation': [h['id'] for h in hyps],
        'decision_after_observation': {'chosen': chosen, 'safe_set': dec_after.get('safe_set')},
        'continuation': exe[0] if exe else None,
        'note': ('观察后用完整状态合同恢复（哈希/机器人签名/MuJoCo 版本严格校验），'
                 '在独立真值场景从同一状态续行，未 reset、未换初态。'),
    }
    (out / 'closed_loop.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    with (out / 'records.jsonl').open('w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(json.dumps({'chosen': chosen, 'safe_set': dec_after.get('safe_set'),
                      'continuation_success': (exe[0] or {}).get('success') if exe else None,
                      'restored_state_hash': state0.get('state_hash')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
