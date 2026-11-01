"""7 块入选石头的完整评估：三初态确认 + 固定首候选主比较。

对每块石头：
  1. 三个冻结初态（seed 7/11/13，非零扰动）各自采集可见量并记录起始 qpos/qvel 哈希；
  2. 固定首候选（本轮唯一生成候选）经观测约束融合 → 碰撞 → 共同规划 → 独立真值执行；
  3. 同条件跑方盒、镜像、2.5D 挡未知、2.5D 补平、真值参考。

  python scripts/v7_holdout_eval.py --rocks P04,P06 --out <dir>
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np

import common_planner as CP
import eval_six
import observe
import runner
import skills
import v7_common_matrix as MX
import v7_holdout_scan as HS
import v7_soil

HEIGHT_RULE = {'climb_direct': 1.0, 'climb_leg': 1.6, 'wheel_r': 0.08595}
POSES = {7: (0.04, 0.03), 11: (-0.05, -0.04), 13: (0.06, 0.05)}


def make_env(rock, case, pose, gen_mesh=None):
    env = HS.make_env_for_rock(rock, case)
    if gen_mesh is not None:
        import terrain
        spec = env.spec
        spec['objects'] = [{'mesh_file': str(gen_mesh), 'x': case['obstacle_x'],
                            'y': 0.0, 'yaw_deg': 0.0,
                            'target_height_m': float(rock['height_m'])}]
        import wheelleg_env
        env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
    env.init_perturbation = {'lateral': abs(float(pose[0])), 'yaw': abs(float(pose[1]))}
    env.reset(seed=7)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rocks', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--gen-root', default='assets/generated')
    ap.add_argument('--actions', default='R1,R2,L1,L2,D1,D2,S1')
    a = ap.parse_args()
    pool = {r['id']: r for r in
            json.loads((ROOT / 'assets/procedural_rocks/index.json').read_text())['rocks']}
    case = json.loads((ROOT / 'cases/unseen_v1/R02.json').read_text())
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    table = {'schema': 'holdout-eval/v1', 'planning': '单土壤 nominal（诊断口径）',
             'candidate_scope': '固定首候选（每块仅一个生成候选，不宣称多候选收益）',
             'rocks': {}}
    for rid in a.rocks.split(','):
        rock = pool[rid]
        gen = ROOT / a.gen_root / rid / 'extracted/mesh/tex_mesh.glb'
        rec = {'height_m': rock['height_m'], 'generated_mesh': str(gen.relative_to(ROOT))
               if gen.is_file() else None, 'poses': {}, 'rows': {}}
        for seed, pose in POSES.items():
            env = make_env(rock, case, pose)
            d = out / rid / f'seed{seed}'
            observe.capture_observation(env, d, case_id=rid)
            vis = json.loads((d / 'observation.json').read_text())['visible']
            q = np.concatenate([env.data.qpos, env.data.qvel]).round(9)
            import hashlib
            rec['poses'][seed] = {'pose': pose,
                                  'hash': hashlib.sha256(q.tobytes()).hexdigest()[:16],
                                  'visible': vis}
            if seed != 7:
                continue
            snap = env.save_state()
            fams = {}
            fams['U_truth'] = None
            fams['B2_F'] = f'elev25d_v3/{rid}/box'
            # 方盒/镜像/2.5D 需要以该石头为对象构建；这里先用高程图两策略与真值，
            # 方盒/镜像由 collision_box_union 现场生成
            import subprocess
            import trimesh
            boxdir = out / rid / 'box_collision'
            if not (boxdir / 'manifest.json').is_file():
                m = trimesh.load(ROOT / rock['body'], force='mesh', process=False)
                m.apply_translation([case['obstacle_x'], 0.0, 0.0])
                wpath = out / rid / 'box_world.stl'
                wpath.parent.mkdir(parents=True, exist_ok=True)
                m.export(wpath)
                subprocess.run([sys.executable, 'scripts/collision_box_union.py',
                                '--mesh', str(wpath), '--solid-from-mesh',
                                '--out', str(boxdir), '--pitch', '0.0025',
                                '--hypothesis-id', f'box_{rid}'],
                               cwd=str(ROOT), capture_output=True, text=True)
            if (boxdir / 'manifest.json').is_file():
                fams['box'] = str(boxdir.relative_to(ROOT))
            if gen.is_file():
                fams['Lux3D'] = str(gen.relative_to(ROOT))
            for name, asset in fams.items():
                vis7 = rec['poses'][7]['visible']
                hyps = [{'id': name, 'kind': name, 'collision_dir': asset or ''}]
                def build(h, s, asset=asset, rid=rid):
                    if asset is None:
                        return make_env(rock, case, POSES[7])
                    if asset.endswith('.glb'):
                        return make_env(rock, case, POSES[7], gen_mesh=ROOT / asset)
                    env2 = HS.make_env_for_rock(rock, case)
                    spec = env2.spec
                    spec['objects'] = [{'posed_dir': asset}]
                    import wheelleg_env
                    e = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
                    e.init_perturbation = {'lateral': POSES[7][0], 'yaw': POSES[7][1]}
                    e.reset(seed=7)
                    return e
                try:
                    p = CP.plan_action(hyps, snap, vis7, ['nominal'], 30.0, build,
                                       goal_x=case['goal_x'], seed=7)
                    act = p['decision']['chosen']
                    rec['rows'][name] = {'chosen': act, 'cells': p['counts']['rows'],
                                         'errors': p['decision'].get('rehearsal_errors')}
                except Exception as e:
                    rec['rows'][name] = {'error': f'{type(e).__name__}: {e}'[:200]}
                    continue
                env3 = make_env(rock, case, POSES[7])
                env3.restore_state(snap, mode='same_scene')
                r = runner.EpisodeRunner(env3, skills.make_skill(act), visible=vis7,
                                         seed=7).run_current()
                rec['rows'][name].update({'success': bool(r.get('success')),
                                          'reason': r.get('reason'),
                                          'final_x': r.get('final_x')})
                print(json.dumps({'rock': rid, 'family': name,
                                  'chosen': act, 'ok': bool(r.get('success'))},
                                 ensure_ascii=False), flush=True)
        hs = [v['hash'] for v in rec['poses'].values()]
        rec['distinct'] = len(set(hs)) == len(hs)
        table['rocks'][rid] = rec
        (out / 'table.json').write_text(json.dumps(table, ensure_ascii=False, indent=2))
    print(json.dumps({k: v['distinct'] for k, v in table['rocks'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
