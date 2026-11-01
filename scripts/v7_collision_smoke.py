"""碰撞资产加载小规模实跑（不扩展实验）。

对四类资产各跑**一个适用动作**，检查：
  1. 解析到的碰撞目录与预期一致，loaded_kind / n_boxes 落盘；
  2. 环境里确实有碰撞体（object 数、box 数）；
  3. 产生真实物理结果（有轨迹帧、有结束时模拟时间）；
  4. 加载异常记 rehearsal_error，与物理失败分开。
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import actions as ACT, collision_asset as CA, common_planner as CP, runner, skills
import v7_common_matrix as MX

BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'


def one(name, asset, cfg, soil, seed, snap, vis, action, goal_x, budget, out):
    d = out / name; d.mkdir(parents=True, exist_ok=True)
    rec = {'asset': name, 'asset_root': asset, 'action': action}
    try:
        info = CA.resolve(asset)
    except CA.CollisionAssetError as e:
        rec.update({'outcome': 'rehearsal_error', 'error_class': 'collision_asset',
                    'error': str(e)[:600]})
        (d / 'smoke.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        return rec
    rec['resolved'] = {k: info[k] for k in ('collision_dir', 'kind', 'n_boxes', 'n_parts',
                                            'pitch_m', 'coordinate_frame', 'manifest_sha')}
    try:
        env = MX.build_env(cfg, soil, collision_dir=asset)
    except Exception as e:
        rec.update({'outcome': 'rehearsal_error', 'error_class': 'environment',
                    'error': f'{type(e).__name__}: {e}'[:600]})
        (d / 'smoke.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        return rec
    # 环境里是否真的加载了碰撞体
    import mujoco
    n_geom = int(env.model.ngeom)
    rec['env'] = {'n_geom': n_geom, 'n_objects': len(env.spec.get('objects') or []),
                  'obj_keys': [k for k in (env.spec.get('objects') or [{}])[0]]}
    env.reset(seed=seed)
    # 候选场景与采集场景不同：按 project 投射状态（与共同规划器一致）
    env.restore_state(snap, mode='project')
    rec['state_mode'] = 'project'
    r = runner.EpisodeRunner(env, skills.make_skill(action), visible=vis, seed=seed,
                             record_trajectory=True).run_current()
    frames = r.get('trajectory') or []
    if frames:
        (d / 'trajectory.jsonl').write_text(
            '\n'.join(json.dumps(f, ensure_ascii=False) for f in frames) + '\n')
    rec['result'] = {'success': bool(r.get('success')), 'reason': r.get('reason'),
                     'final_x': r.get('final_x'), 'frames': len(frames),
                     'sim_time_s': round(float(env.t), 4),
                     'contact': r.get('contact'), 'max_tilt': r.get('max_tilt')}
    rec['outcome'] = ('physics_pass' if r.get('success') else
                      ('physics_fail' if frames else 'rehearsal_error'))
    if not frames:
        rec['error_class'] = 'no_trajectory'
    (d / 'smoke.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='R02_s0.9')
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--action', default=None, help='默认用可见量下第一个适用非 A0 动作')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = ROOT / a.out if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    plan = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
    cfg = next(c for c in plan['configs'] if c['config_id'] == a.config)
    unit = ROOT / BATCH / 'common_states' / a.config / a.soil / f'seed{a.seed}'
    acq = json.loads((unit / 'acquisition.json').read_text())
    snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
    vis = acq.get('visible') or {}
    goal_x = json.loads((ROOT / cfg['case_config']).read_text())['goal_x']
    budget = float(cfg.get('budget_s', 30.0))
    action = a.action
    if action is None:
        action = next(o for o in ('R1', 'L2', 'D1', 'D2', 'L1', 'R2')
                      if ACT.applicable(o, vis)[0])
    assets = {
        'box_B2F': f'{BATCH}/priors_{a.config}/B2F',
        'mirror_B3F': f'{BATCH}/priors_{a.config}/B3F',
        'lux3d_H5F': f'{BATCH}/refuse_{a.config}',
        'two_view': f'{BATCH}/fair_ablation/{a.config}_{a.soil}_seed{a.seed}/two_view',
    }
    rows = []
    for name, asset in assets.items():
        if not (ROOT / asset).exists():
            rows.append({'asset': name, 'outcome': 'asset_absent', 'asset_root': asset})
            continue
        rows.append(one(name, asset, cfg, a.soil, a.seed, snap, vis, action, goal_x,
                        budget, out))
    summary = {'schema': 'collision-smoke/v1', 'config': a.config, 'soil': a.soil,
               'seed': a.seed, 'action': action, 'state_hash': snap.get('state_hash'),
               'rows': rows,
               'counts': {k: sum(1 for r in rows if r.get('outcome') == k)
                          for k in ('physics_pass', 'physics_fail', 'rehearsal_error',
                                    'asset_absent')}}
    (out / 'smoke.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    for r in rows:
        print(json.dumps({'asset': r['asset'], 'outcome': r.get('outcome'),
                          'kind': (r.get('resolved') or {}).get('kind'),
                          'n_boxes': (r.get('resolved') or {}).get('n_boxes'),
                          'frames': (r.get('result') or {}).get('frames'),
                          'reason': (r.get('result') or {}).get('reason')},
                         ensure_ascii=False))
    print(json.dumps(summary['counts'], ensure_ascii=False))


if __name__ == '__main__':
    main()
