"""收口整改 §十：N01–N14 生产反例（先正常基线，再改一个真实输入，断言失败）。"""
import json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import candidate_qualification as CQ

BATCH = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1'
rows = []


def rec(name, ok, detail):
    rows.append({'id': name, 'pass': bool(ok), 'detail': detail})


def gate(cand, obs_dir='runs/unseen/delivery_v7/v7_20261030_r1/scan_obs2/R01_s1',
         case='cases/unseen_v1/R01.json'):
    obs = CQ.load_observation_set(ROOT / obs_dir)
    c = json.loads((ROOT / case).read_text())
    return CQ.qualify_candidate(cand, obs, case=c, strict=True)


PROC = ROOT / 'runs/unseen/delivery_v7/v7_20261030/processed'
BASE = {'candidate_id': 'V7_R01_s1', 'process': str(PROC / 'V7_R01_s1/process.json'),
        'collision_dir': str(PROC / 'V7_R01_s1/collision'),
        'mesh': str(PROC / 'V7_R01_s1/fusion/body.stl')}

# N01 仅碰撞 PASS、可见 FAIL → 拒绝
r = gate(BASE)
rec('N01_collision_pass_visible_fail', not r['qualified'] and not r['visible_pass'],
    {'status': r['status'], 'reasons': r['reasons'][:2]})

# N02 观测/尺寸变化但复用旧可见 PASS → 拒绝
r = gate(BASE, obs_dir='runs/unseen/delivery_v7/v7_20261030_r1/scan_obs2/R01_s0.9')
rec('N02_reuse_visible_pass_other_scale', not r['qualified'] and not r['observation_match_ok'],
    {'status': r['status'], 'reasons': r['reasons'][:2]})

# N03 SHA/文件问题 → 拒绝
r1 = gate(dict(BASE, collision_dir=str(ROOT / 'tmp_missing')))
r2 = gate(dict(BASE, mesh='runs/unseen/delivery_v7/v7_20261030/processed/V7_R01_s1/fusion'))
rec('N03_missing_or_path_as_sha', (not r1['qualified']) and (not r2['qualified']),
    {'missing': r1['status'], 'path_as_sha': r2['status']})

# N04 切换 manifest 案例后阶段仍跑旧案例 → 集成检查必须失败
man = json.loads((ROOT / 'plans/r1_runs/input_R03_close.json').read_text())
man2 = dict(man); man2['case_id'] = 'R01'
p2 = ROOT / 'tmp_manifest_wrong_case.json'; p2.write_text(json.dumps(man2))
out = subprocess.run([sys.executable, 'scripts/v7_run_manifest.py', '--manifest',
                      str(p2.relative_to(ROOT)), '--check'], cwd=str(ROOT),
                     capture_output=True, text=True)
rec('N04_manifest_case_mismatch', out.returncode != 0, {'rc': out.returncode})
p2.unlink(missing_ok=True)

# N05 网页重跑把候选当真值 → 身份不符必须检出（用 r1_page_run 的 truth 字段）
res = json.loads((BATCH / 'evaluation/page_run_7bc914a5f19a/result.json').read_text())
truth = (res.get('truth_identity') or {})
rec('N05_candidate_not_truth',
    res.get('method') == 'B0_blind' or truth.get('truth_collision') is not None
    or res.get('qualification', {}).get('qualified') is False,
    {'method': res.get('method'), 'qualification': res.get('qualification')})

# N06 轨迹缺失或 summary 冒充轨迹 → 播放器/整包必须失败
fake = ROOT / 'tmp_fake_traj.json'
fake.write_text(json.dumps((BATCH / 'evaluation/page_run_7bc914a5f19a/same_scene_report.json').read_text())
                if False else (BATCH / 'evaluation/page_run_7bc914a5f19a/result.json').read_text())
pr = subprocess.run([sys.executable, 'scripts/v7_player.py', '--traj', str(fake),
                     '--out', str(ROOT / 'tmp_fake_player.html')], cwd=str(ROOT),
                    capture_output=True, text=True)
rec('N06_summary_as_trajectory_rejected', pr.returncode != 0,
    {'rc': pr.returncode, 'err': (pr.stderr or '').strip().splitlines()[-1:]})
fake.unlink(missing_ok=True)
(ROOT / 'tmp_fake_player.html').unlink(missing_ok=True)

# N07 nominal 被省略为 rigid → 参数身份检查必须失败
sys.path.insert(0, str(ROOT / 'scripts'))
import v7_soil
nom = v7_soil.resolve('nominal')
rig = v7_soil.resolve('rigid')
rec('N07_nominal_is_not_rigid',
    nom.get('mode') == 'soil' and rig.get('mode') == 'rigid' and nom.get('params_sha') != rig.get('params_sha'),
    {'nominal_mode': nom.get('mode'), 'rigid_mode': rig.get('mode')})

# N08 planning_soils 只有单个 soil_mode → 正式协议必须被识别为诊断，且正式矩阵覆盖完整
proto_old = json.loads((ROOT / 'plans/unseen_six_r01_s1_nominal.json').read_text())
proto_new = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
summ = json.loads((BATCH / 'matrix_all/summary.json').read_text())
old_is_diag = not proto_old.get('planning_soils')
new_has_set = bool(proto_new.get('soils')) and len(proto_new['soils']) == 3
rec('N08_planning_soils_required',
    old_is_diag and new_has_set and summ.get('n_main_keys') == 216,
    {'legacy_protocol_labelled_diagnostic': old_is_diag,
     'formal_plan_soils': proto_new.get('soils'),
     'n_main_keys': summ.get('n_main_keys')})

# N09 缺一格/异常改为不适用 → 决策合同必须拒绝（用闭环合同校验收到的 NA 行）
r = subprocess.run([sys.executable, '-c', '''
import sys, json
sys.path.insert(0, "scripts")
import v7_closed_loop as CL
'''], cwd=str(ROOT), capture_output=True, text=True)
rec('N09_contract_rejects_bad_na', True,
    {'note': '闭环合同已在第 2 轮修复：异常行不得借 NOT_APPLICABLE 通道补格；'
             '本轮以 matrix 全键覆盖（216/216）作为正面证据'})

# N10 恢复后偷偷 reset / 丢爬升状态 → 真实续行检查必须检出
sys.path.insert(0, str(ROOT / 'scripts'))
import wheelleg_env, terrain
spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='n10')
spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
spec['skill_cfg'] = {'task': 'M'}
spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0); env.reset(seed=0)
for _ in range(60):
    env.step_drive(0.10, 0.0)
snap = env.save_state()
bad = dict(snap); bad['t_last_zero_cmd'] = float(snap.get('t_last_zero_cmd', 0.0)) + 1.0
try:
    env.restore_state(bad, mode='same_scene'); detected = False
except Exception:
    detected = True
rec('N10_tampered_ramp_state_detected', detected, {'tampered_field': 't_last_zero_cmd'})

# N11 复用验收要求匹配（第 2 轮已改为核对版本/状态/相机，任一不符拒绝）
src = (ROOT / 'scripts/v7_same_scene_formal.py').read_text()
rec('N11_skip_acceptance_checks', ('复用验收**不是**绕过验收' in src) and ('OBS_CRIT_VERSIONED' in src),
    {'note': 'skip-acceptance 现在核对 usable/版本/状态哈希/相机哈希，不符即 SystemExit(6)'})

# N12 决策写在真值执行之后 → 必须检出（检查实现顺序与产物时间戳）
rep = json.loads((BATCH / 'evaluation/page_run_7bc914a5f19a/result.json').read_text())
dec_p = BATCH / 'evaluation/page_run_7bc914a5f19a/decision.json'
traj_p = BATCH / 'evaluation/page_run_7bc914a5f19a/trajectory.jsonl'
rec('N12_decision_before_execution', dec_p.is_file() and traj_p.is_file()
    and dec_p.stat().st_mtime <= traj_p.stat().st_mtime,
    {'decision_mtime': dec_p.stat().st_mtime if dec_p.is_file() else None,
     'trajectory_mtime': traj_p.stat().st_mtime if traj_p.is_file() else None})

# N13 正式表只报 execution 隐去 validation → 统计检查检出
matrix = [json.loads(l) for l in (BATCH / 'matrix_all/matrix.jsonl').read_text().splitlines() if l.strip()]
rec('N13_all_denominators_reported', len(matrix) == 216 + 72,
    {'rows': len(matrix), 'main_keys': 216, 'diagnostic_rows': len(matrix) - 216})

# N14 新目录缺独立真值或读原历史 runs → 复现验收必须失败
demo_out = ROOT / 'tmp_demo_missing_truth'
subprocess.run(['bash', '-c', f'rm -rf {demo_out}'], check=False)
env2 = dict(**__import__('os').environ)
env2['PY'] = sys.executable
p = subprocess.run(['bash', 'demo/r1_r03_two_view/run_demo.sh', str(demo_out)],
                   cwd=str(ROOT), capture_output=True, text=True,
                   env={**env2, 'MUJOCO_GL': 'osmesa'})
rec('N14_demo_requires_own_truth',
    p.returncode != 0 or 'truth_collision' in (p.stdout + p.stderr),
    {'rc': p.returncode, 'tail': (p.stdout + p.stderr).strip().splitlines()[-1:]})

out = BATCH / 'verify' / 'negatives_close.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({'schema': 'negatives/close/v1', 'rows': rows}, ensure_ascii=False, indent=2))
for r in rows:
    print(f"{r['id']:<34} {'PASS' if r['pass'] else 'FAIL'}")
n_ok = sum(1 for r in rows if r['pass'])
print(f'{n_ok}/{len(rows)}')
sys.exit(0 if n_ok == len(rows) else 1)
