"""V7-R1 §6：状态合同 A/B（生产函数）。

  A 同场景完整恢复：成功，时钟/位姿一致
  B 把同场景快照恢复进**候选场景**：必须被拒绝（场景签名不符）
  C 跨候选投射：只搬机器人状态，不搬碰撞材质（按索引的摩擦一律跳过）
  D 不同土壤参数 -> 场景签名不同

  .venv/bin/python scripts/v7_state_contract_test.py --out <json>
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain, wheelleg_env

def env_of(col, soil=None):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='ab')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['objects'] = [{'posed_dir': str(col)}]
    if soil:
        import v7_soil
        r = v7_soil.resolve(soil)
        spec['soil'] = {'mode': 'soil', 'params': r['params']}
    return wheelleg_env.WheelLegEnv(spec)

ap = argparse.ArgumentParser()
ap.add_argument('--truth', default='runs/unseen/recovery_r3/look_loop_R01_v3/truth/truth_world')
ap.add_argument('--candidate-collision',
                default='runs/unseen/delivery_v7/v7_20261030/processed/V7_R01_s2/collision')
ap.add_argument('--out', default=None)
a = ap.parse_args()
T = str(ROOT / a.truth)
C = str(ROOT / a.candidate_collision)
res = {}
e1 = env_of(T); e1.reset(seed=0)
for _ in range(40): e1.step([0.0,0.0,0.0])
snap = e1.save_state()
res['scene_sig'] = str(snap['scene_signature'])
print('scene_sig', snap['scene_signature'], 'robot_sig', snap['robot_signature'][:12])

# A) 同场景完整恢复
e2 = env_of(T); e2.reset(seed=0); info = e2.restore_state(snap, mode='same_scene')
res['A_same_scene_ok'] = bool(abs(float(e2.t)-float(e1.t)) < 1e-9)
print('A same_scene ok', abs(float(e2.t)-float(e1.t)) < 1e-9, 'mode', info['mode'])

# B) 同场景但放进候选场景 -> 必须拒绝
e3 = env_of(C); e3.reset(seed=0)
try:
    e3.restore_state(snap, mode='same_scene')
    res['B_same_scene_rejected'] = False
    print('B same_scene rejected', False)
except ValueError as _ex:
    res['B_same_scene_rejected'] = True
    res['B_message'] = str(_ex)[:80]
    print('B same_scene rejected', True, str(_ex)[:60])

# C) 跨候选投射：机器人状态一致、材质不搬
info = e3.restore_state(snap, mode='project')
ok_robot = (abs(float(e3.t)-float(e1.t)) < 1e-9 and
            (e3.data.qpos == e1.data.qpos).all())
res['C_project_ok'] = bool(ok_robot)
res['C_material_not_transferred'] = bool(not info['collision_material_transferred'])
print('C project ok', ok_robot, 'material_transferred', info['collision_material_transferred'],
      'skipped_friction', info['geom_friction_skipped'],
      'scene_changed', info['source_scene_sha'] != info['target_scene_sha'])

# D) 不同土壤参数 -> 场景签名必须不同
e4 = env_of(T, 'low_traction'); e4.reset(seed=0)
res['D_soil_changes_scene_sig'] = bool(e4.scene_signature() != e1.scene_signature())
print('D soil_changes_scene_sig', e4.scene_signature() != e1.scene_signature())

res['all_pass'] = bool(all(v for k, v in res.items() if k.startswith(('A_', 'B_', 'C_', 'D_'))))
if a.out:
    p = ROOT / a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'schema': 'state-contract-test/v7', **res}, ensure_ascii=False, indent=2))
print(json.dumps({'all_pass': res['all_pass']}, ensure_ascii=False))
raise SystemExit(0 if res['all_pass'] else 1)
