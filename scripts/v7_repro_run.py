"""可复现运行（下一批任务书 §8）：从包内缓存数据走完 重建→预演→决策→真值执行→连续回放。

包内只有缓存输入（观测图像/深度/相机、案例、真值、状态快照、配置），不读原 runs 历史树，
不触发生成。任何一步缺失或播放器生成失败 → 非零退出，不打印完成。

  python scripts/v7_repro_run.py --pack demo/r1_r02_25d --out /tmp/repro
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

PY = sys.executable


def sha(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def fail(msg, out_dir=None):
    rec = {'schema': 'repro-run/v1', 'ok': False, 'error': msg, 'ts': time.time()}
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'result.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps(rec, ensure_ascii=False))
    sys.exit(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--strategy', default='fill')
    a = ap.parse_args()
    pack = (ROOT / a.pack) if not pathlib.Path(a.pack).is_absolute() else pathlib.Path(a.pack)
    out = (ROOT / a.out) if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    man = json.loads((pack / 'MANIFEST.json').read_text())

    # 1 输入身份
    for it in man.get('items', []):
        p = pack / it['path']
        if not p.exists():
            fail(f"缺输入 {it['path']}", out)
        if p.is_file() and it.get('sha256') and sha(p) != it['sha256']:
            fail(f"哈希不符 {it['path']}", out)
    rec = {'schema': 'repro-run/v1', 'pack': a.pack, 'strategy': a.strategy,
           'inputs_verified': len(man.get('items', [])), 'stages': {}}

    # 2 从缓存观测重建 2.5D 高程资产
    import v7_elev25d as E
    case = json.loads((pack / 'inputs/case.json').read_text())
    H, OBS, meta = E.build_elevation(pack / 'inputs/observation', case, E.CELL_M)
    ground = E.ground_reference(H, OBS, meta)
    boxes, info = E.to_boxes(H, OBS, meta, a.strategy, ground, E.CELL_M)
    asset_dir = out / 'elev25d' / a.strategy
    E.write_asset(asset_dir, boxes, meta, info, a.strategy, E.CELL_M)
    rec['stages']['rebuild'] = {'n_boxes': len(boxes),
                                'unknown_frac': round(1.0 - OBS.mean(), 4),
                                'asset': str(asset_dir.relative_to(ROOT))
                                if asset_dir.is_relative_to(ROOT) else str(asset_dir)}

    # 3 共同规划
    import common_planner as CP
    import v7_common_matrix as MX
    snap = json.loads((pack / 'inputs/state_snapshot.json').read_text())
    vis = json.loads((pack / 'inputs/observation/observation.json').read_text())['visible']
    cfg = {'config_id': man['case_id'], 'case_config': str((pack / 'inputs/case.json').relative_to(ROOT))
           if (pack / 'inputs/case.json').is_relative_to(ROOT) else str(pack / 'inputs/case.json'),
           'mesh': str((pack / 'inputs/truth/body.stl').relative_to(ROOT))
           if (pack / 'inputs/truth/body.stl').is_relative_to(ROOT) else str(pack / 'inputs/truth/body.stl'),
           'budget_s': float(man.get('budget_s', 30.0)),
           'truth_collision': None}
    asset_rel = (str(asset_dir.relative_to(ROOT)) if asset_dir.is_relative_to(ROOT)
                 else str(asset_dir))
    hyps = [{'id': f'E25D_{a.strategy}', 'kind': 'elev25d', 'collision_dir': asset_rel}]
    plan = CP.plan_action(hyps, snap, vis, [man.get('soil', 'nominal')], cfg['budget_s'],
                          (lambda h, s: MX.build_env(cfg, s, collision_dir=asset_rel)),
                          goal_x=case['goal_x'], seed=int(man.get('seed', 7)))
    CP.write_plan(plan, out / 'plan')
    act = plan['decision']['chosen']
    (out / 'decision.json').write_text(json.dumps(plan['decision'], ensure_ascii=False, indent=2))
    rec['stages']['plan'] = {'chosen': act, 'cells': plan['counts']['rows'],
                             'safe_set': plan['decision'].get('safe_set')}

    # 4 独立真值执行
    import runner
    import skills
    env = MX.build_env(cfg, man.get('soil', 'nominal'), collision_dir=None)
    env.reset(seed=int(man.get('seed', 7)))
    # 包内快照的签名可能是在原路径下写入的（网格换目录）；只有包显式声明
    # allow_scene_rebind 时才允许按同一物理状态重绑，并在结果里如实记录。
    rebind = False
    try:
        env.restore_state(snap, mode='same_scene')
    except ValueError as e:
        if not man.get('allow_scene_rebind'):
            fail(f'同场景恢复被拒且包未允许重绑：{e}', out)
        env.restore_state(snap, mode='project')
        rebind = True
    r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis,
                             seed=int(man.get('seed', 7)), record_trajectory=True).run_current()
    frames = r.get('trajectory') or []
    traj = out / 'trajectory.jsonl'
    if not frames:
        fail('执行未产生轨迹：拒绝报告成功', out)
    traj.write_text('\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
    with traj.open('a') as f:
        f.write(json.dumps({'terminal': True, 't': round(float(env.t), 5),
                            'reason': r.get('reason'), 'success': bool(r.get('success')),
                            'final_x': round(float(env.data.qpos[0]), 6)},
                           ensure_ascii=False) + '\n')
    rec['stages']['execute'] = {'scene_rebind': rebind,
                                'success': bool(r.get('success')), 'reason': r.get('reason'),
                                'final_x': r.get('final_x'), 'frames': len(frames),
                                'sim_time_s': round(float(env.t), 4)}

    # 5 连续回放
    pr = subprocess.run([PY, 'scripts/v7_player.py', '--traj', str(traj),
                         '--out', str(out / 'player.html'),
                         '--title', f"{man['case_id']} {a.strategy} 可复现运行"],
                        cwd=str(ROOT), capture_output=True, text=True)
    if pr.returncode != 0 or not (out / 'player.html').is_file():
        fail('播放器生成失败：整包不算完成', out)
    rec['stages']['replay'] = {'player': str(out / 'player.html'), 'frames': len(frames)}

    # 6 五画面页（数据全部来自本次运行）
    rec['ok'] = True
    rec['finished'] = time.time()
    (out / 'result.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: rec['stages'][k] for k in rec['stages']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
