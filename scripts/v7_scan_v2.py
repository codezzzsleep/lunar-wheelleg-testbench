"""扫描 v2：真值实体 × 三档尺寸 × 七动作 × 两初态（先预检，再展开）。

与 v1 的区别：碰撞体来自**案例真值网格**（缩放后重建），不是 Lux3D 候选；
可见量来自**该案例该尺寸真实采集的观测**；观测目录与碰撞目录是两个独立参数；
缺观测/缺字段/接口不存在时直接报错，不回退为空字典。

  # 预检（1 对象 1 尺寸 2 初态）
  /opt/lunar/bin/python scripts/v7_scan_v2.py --assets <dir> --obs <dir> --out <dir> --precheck
  # 全量
  /opt/lunar/bin/python scripts/v7_scan_v2.py --assets <dir> --obs <dir> --out <dir> --limit 168
"""
import argparse, hashlib, json, pathlib, sys, traceback
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np
import terrain, wheelleg_env, runner, skills, actions as ACT


def vis_of(obs_root, case, scale):
    p = pathlib.Path(obs_root) / f'{case}_s{scale:g}_visible.json'
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise SystemExit(f'缺可见量文件：{p}')
    v = json.loads(p.read_text())
    for k in ('x_front', 'W_vis', 'H_vis'):
        if v.get(k) is None:
            raise SystemExit(f'{p} 缺字段 {k}')
    return v


def asset_of(assets, case, scale):
    d = pathlib.Path(assets) / f'{case}_s{scale:g}'
    if not d.is_absolute():
        d = ROOT / d
    if not (d / 'collision' / 'manifest.json').exists():
        raise SystemExit(f'缺碰撞资产：{d}/collision')
    if not (d / 'body.stl').exists():
        raise SystemExit(f'缺显示网格：{d}/body.stl')
    return d


def build(asset_dir, goal_x, seconds, soil, state):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=goal_x,
                             name=asset_dir.name)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    # env 内部按 uniform(-m, +m) 抽样，m 必须非负；符号由 seed 决定
    spec['init_perturbation'] = {'lateral_m': abs(float(state['lateral_m'])),
                                 'yaw_rad': abs(float(state['yaw_rad']))}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(asset_dir / 'collision')}]
    return wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=seconds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--assets', required=True)
    ap.add_argument('--obs', required=True)
    ap.add_argument('--protocol', default='plans/unseen_r1_scan_protocol.json')
    ap.add_argument('--out', required=True)
    ap.add_argument('--limit', type=int, default=168)
    ap.add_argument('--seconds', type=float, default=30.0)
    ap.add_argument('--goal-x', type=float, default=2.6)
    ap.add_argument('--precheck', action='store_true')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    out = ROOT / a.out; out.mkdir(parents=True, exist_ok=True)
    objs = proto['objects'][:1] if a.precheck else proto['objects']
    scales = proto['size_levels']['scales'][1:2] if a.precheck else proto['size_levels']['scales']
    rows, n = [], 0
    for case in objs:
        for scale in scales:
            asset_dir = asset_of(a.assets, case, scale)
            vis = vis_of(a.obs, case, scale)
            import trimesh
            bb = trimesh.load(str(asset_dir / 'body.stl'), force='mesh', process=False).bounds
            for st in proto['initial_states']:
                for act in proto['actions']:
                    if n >= min(a.limit, proto['max_episodes']):
                        break
                    rec = {'case': case, 'scale': scale, 'action': act, 'seed': st['seed'],
                           'asset': str(asset_dir.relative_to(ROOT))
                           if asset_dir.is_relative_to(ROOT) else str(asset_dir),
                           'bbox': np.round(bb, 6).tolist(),
                           'visible': {k: vis[k] for k in ('x_front', 'W_vis', 'H_vis')}}
                    ok, why = ACT.applicable(act, vis)
                    if not ok:
                        rec.update({'outcome': 'not_applicable', 'reason': why,
                                    'rule_version': getattr(ACT, 'RULE_VERSION', None),
                                    'counted_as_episode': False})
                        rows.append(rec)
                        continue
                    try:
                        env = build(asset_dir, a.goal_x, a.seconds, proto['soil'], st)
                        obs, _ = env.reset(seed=st['seed'])
                        rec['initial_qpos_hash'] = hashlib.sha256(
                            np.asarray(env.data.qpos, dtype=np.float64).tobytes()).hexdigest()[:16]
                        rec['initial_qvel_hash'] = hashlib.sha256(
                            np.asarray(env.data.qvel, dtype=np.float64).tobytes()).hexdigest()[:16]
                        r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=st['seed'])
                        o = r.run()
                        reason = (o.get('reason') or '').lower()
                        if o.get('success'):
                            oc = 'success'
                        elif 'tip' in reason or (o.get('max_tilt') or 0) > 60:
                            oc = 'tipped'
                        elif 'bound' in reason:
                            oc = 'out_of_bounds'
                        elif 'time' in reason:
                            oc = 'timeout'
                        else:
                            oc = 'abort'
                        rec.update({'outcome': oc, 'reason': o.get('reason'),
                                    'final_x': o.get('final_x'),
                                    'displacement_x': o.get('displacement_x'),
                                    'max_tilt': o.get('max_tilt'),
                                    'action_fingerprint': o.get('action_fingerprint'),
                                    'phases': o.get('phases'),
                                    'counted_as_episode': True})
                    except Exception as e:
                        rec.update({'outcome': 'sim_error', 'error': f'{type(e).__name__}: {e}',
                                    'trace': traceback.format_exc().splitlines()[-3:],
                                    'counted_as_episode': True})
                    rows.append(rec); n += 1
                    (out / 'scan_v2.jsonl').write_text(
                        '\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n')
    summary = {'n_rows': len(rows),
               'n_episodes': sum(1 for r in rows if r.get('counted_as_episode')),
               'n_not_applicable': sum(1 for r in rows if r['outcome'] == 'not_applicable'),
               'by_outcome': {k: sum(1 for r in rows if r['outcome'] == k)
                              for k in sorted({r['outcome'] for r in rows})},
               'protocol': a.protocol, 'assets': a.assets, 'obs': a.obs}
    (out / 'scan_v2_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
