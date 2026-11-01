"""页面/演示共用的单次正式闭环运行。

与其他生产入口一样：候选必须过唯一资格门；决策先落盘；真值执行用同一份
独立真值；轨迹由生产执行器落盘；失败分类明确（无候选/资格失败/观测失败/计算异常）。

  python scripts/r1_page_run.py --case R03 --soil nominal --seed 7 --out <dir>
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np

import candidate_qualification as CQ
import runner
import skills
import v7_common_matrix as MX

PY = sys.executable
BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'

# 案件 → 权威输入（案例、观测、真值、候选映射、状态目录）
CASES = {
    'R01': {'config_id': 'R01_s1', 'case_config': 'cases/unseen_v1/R01.json',
            'observation': f'{BATCH}/scan_obs2/R01_s1',
            'truth_collision': None, 'candidates': f'{BATCH}/verify/candidates_R03_s1.json'},
    'R02': {'config_id': 'R02_s0.9', 'case_config': 'cases/unseen_v1/R02.json',
            'observation': f'{BATCH}/scan_obs2/R02_s0.9',
            'truth_collision': None, 'candidates': f'{BATCH}/verify/candidates_R03_s1.json'},
    'R03': {'config_id': 'R03_s1', 'case_config': 'cases/unseen_v1/R03.json',
            'observation': 'runs/unseen/recovery_r3/obs_R03',
            'truth_collision': None, 'candidates': f'{BATCH}/verify/candidates_R03_s1.json'},
    'R04': {'config_id': 'R04_s1', 'case_config': 'cases/unseen_v1/R04.json',
            'observation': f'{BATCH}/scan_obs2/R04_s1',
            'truth_collision': None, 'candidates': f'{BATCH}/verify/candidates_R03_s1.json'},
}
DEFAULT_METHOD = 'H5_F'


def sha_file(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def cfg_for(case_key):
    c = CASES[case_key]
    plan = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
    base = next(x for x in plan['configs'] if x['config_id'] == c['config_id'])
    cfg = dict(base)
    cfg.update({'case_config': c['case_config'], 'observation': c['observation'],
                'truth_collision': c['truth_collision']})
    return cfg


def candidate_map(case_key):
    c = CASES[case_key]
    p = ROOT / c['candidates']
    if not p.is_file():
        return {}
    d = json.loads(p.read_text())
    return d.get(c['config_id'], {})


def run(case_key, soil, seed, out, method=DEFAULT_METHOD):
    if case_key not in CASES:
        raise SystemExit(f'未知案例 {case_key}')
    out = pathlib.Path(out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    cfg = cfg_for(case_key)
    cfg_id = cfg['config_id']
    state_dir = ROOT / BATCH / 'common_states' / cfg_id / soil / f'seed{seed}'
    started = time.time()
    res = {'schema': 'page-run/v1', 'case': case_key, 'config_id': cfg_id,
           'soil': soil, 'seed': seed, 'method': method,
           'run_id': time.strftime('%Y%m%dT%H%M%S') + f'-{case_key}-{soil}-{seed}',
           'started_at': started}
    # 1 观测与状态
    obs_dir = ROOT / cfg['observation']
    if not (obs_dir / 'observation.json').is_file():
        res.update({'ok': False, 'failure_class': 'observation_failed',
                    'error': f'观测包缺 observation.json：{cfg["observation"]}'})
        (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
        return res
    acq_path = state_dir / 'acquisition.json'
    if not acq_path.is_file():
        res.update({'ok': False, 'failure_class': 'observation_failed',
                    'error': f'缺共同状态：{state_dir.relative_to(ROOT)}'})
        (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
        return res
    acq = json.loads(acq_path.read_text())
    snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
    res['state'] = {'snapshot': acq['state']['snapshot'], 'state_hash': acq['state']['state_hash']}
    res['observation'] = {'dir': cfg['observation'], 'sha': acq['observation']['sha']}
    # 2 资格（唯一门）
    cmap = candidate_map(case_key).get(method) or {}
    res['qualification'] = {'method': method,
                            'qualified': bool(cmap.get('qualified')),
                            'reason': cmap.get('reason')}
    # 3 决策（候选方法走真实预演；无合格候选走真实 A0）
    MX.CFG_CURRENT[0], MX.CFG_CURRENT[1] = cfg, soil
    env, case = MX.make_env(cfg, soil, truth_collision=cfg.get('truth_collision'))
    env.reset(seed=seed)
    cand_col = cmap.get('collision_dir') if cmap.get('qualified') else None
    if method in ('B0_blind', 'B1_height', 'R2_fixed', 'W_width_rule', 'U_truth'):
        act, why = MX.decide(method, acq.get('visible') or {},
                             cand_collision=None, snapshot=snap)
    else:
        act, why = MX.decide(method, acq.get('visible') or {}, cand_collision=cand_col,
                             snapshot=snap)
    dec = {'method': method, 'chosen': act, 'evidence': why,
           'state_hash': snap.get('state_hash'), 'observation_sha': acq['observation']['sha'],
           'soil': soil, 'seed': seed}
    (out / 'decision.json').write_text(json.dumps(dec, ensure_ascii=False, indent=2))
    res['decision'] = {'chosen': act, 'sha': sha_file(out / 'decision.json'),
                       'fallback': bool(why.get('fallback'))}
    # 4 真值执行（生产执行器写轨迹）
    env.restore_state(snap, mode='same_scene')
    r = runner.EpisodeRunner(env, skills.make_skill(act), seed=seed,
                             record_trajectory=True).run_current()
    frames = r.get('trajectory') or []
    traj = out / 'trajectory.jsonl'
    if frames:
        traj.write_text('\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
        with traj.open('a') as f:
            f.write(json.dumps({'terminal': True, 't': round(float(env.t), 5),
                                'reason': r.get('reason'),
                                'success': bool(r.get('success')),
                                'final_x': round(float(env.data.qpos[0]), 6)},
                               ensure_ascii=False) + '\n')
    res['execution'] = {'success': bool(r.get('success')), 'reason': r.get('reason'),
                        'final_x': r.get('final_x'), 'displacement_x': r.get('displacement_x'),
                        'control_steps': r.get('steps'), 'frames': len(frames),
                        'state_mode': 'same_scene'}
    res['trajectory'] = (str(traj.relative_to(ROOT))
                         if frames and traj.is_relative_to(ROOT) else
                         (str(traj) if frames else None))
    res['trajectory_frames'] = len(frames)
    # 5 播放器
    player = None
    if frames:
        pr = subprocess.run([PY, 'scripts/v7_player.py', '--traj', str(traj),
                             '--out', str(out / 'player.html'),
                             '--title', f'{case_key} {soil} seed{seed} {act}'],
                            cwd=str(ROOT), capture_output=True, text=True)
        if pr.returncode == 0:
            player = (str((out / 'player.html').relative_to(ROOT))
                      if (out / 'player.html').is_relative_to(ROOT)
                      else str(out / 'player.html'))
    res['player'] = player
    res['ok'] = bool(frames) and player is not None
    if not res['ok']:
        res['failure_class'] = 'player_failed' if not player else 'trajectory_missing'
    res['seconds'] = round(time.time() - started, 2)
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--method', default=DEFAULT_METHOD)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    r = run(a.case, a.soil, a.seed, a.out, method=a.method)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get('ok') else 4


if __name__ == '__main__':
    sys.exit(main())
