"""Stage005 冒烟：CLIMB 走真实候选预演入口（project）+ 真值执行（same_scene）。"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402
import terrain  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import stage4_config as S4C  # noqa: E402
import stage4_geometry as S4G  # noqa: E402
import v3_climb as VC  # noqa: E402


def dev_scene(out):
    ledges = [{'face': 0.95, 'len': 1.40, 'y': -0.115}, {'face': 1.13, 'len': 1.22, 'y': 0.185}]
    # 复合碰撞表示：占据 -> box union（MuJoCo mesh 碰撞是凸的，不能直接用合并网格）
    pitch = 0.004
    nx, ny, nz = int(3.2 / pitch), int(1.2 / pitch), int(0.16 / pitch)
    occ = np.zeros((nx, ny, nz), dtype=bool)
    xs = np.arange(nx) * pitch + pitch / 2; ys = np.arange(ny) * pitch - 0.6 + pitch / 2
    zs = np.arange(nz) * pitch + pitch / 2
    X = xs[:, None, None]; Y = ys[None, :, None]; Z = zs[None, None, :]
    for l in ledges:
        x0, x1 = l['face'], l['face'] + l['len']; y0, y1 = l['y'] - 0.225, l['y'] + 0.225
        occ |= (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1) & (Z <= 0.05)
    grid = out / 'occ.npz'
    np.savez_compressed(grid, occupied=occ, origin=np.array([0.0, -0.6, 0.0]),
                        pitch=np.float64(pitch), dims=np.array([nx, ny, nz], int),
                        content_sha=np.array('stage5-smoke'),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    cand = out / 'cand_C1'
    r = v3_core.build_collision(grid, cand, pitch=0.002, downsample=2)
    if not r.get('ok'):
        raise SystemExit(f'collision build failed: {r.get("error")}')
    far = min(l['face'] + l['len'] for l in ledges)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=far + 0.6, name='stage5_smoke',
                             objects=[{'posed_dir': str(cand)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    return spec, far, cand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = S4C.load()
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    spec, far, cand = dev_scene(out)
    spec['soil'] = v7_soil.resolve('nominal')
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s']))
    env.reset(seed=0)
    snap = env.save_state()
    visible = {'x_front': 0.95, 'W_vis': 0.45, 'H_vis': 0.05,
               'x_front_m': 0.95, 'W_vis_m': 0.45, 'H_vis_m': 0.05}
    core = {'spec': spec, 'snapshot': snap, 'visible': visible,
            'state': {'state_id': 'stage5_smoke', 'state_hash': snap.get('state_hash')}}
    gp = S4G.derive_skill_params({'face_FR': 0.95, 'face_FL': 1.13, 'top_z': 0.05,
                                  'far_x': far, 'landing': None, 'source': 'dev_wiring'})
    plan = {'action': 'CLIMB', 'params': gp['params'], 'applicable': True,
            'plan_id': 'stage5_smoke_plan', 'source': 'dev_wiring'}
    rows, app = v3_core.rehearse(core, {'C1': str(cand)}, snap, proto,
                                 record_cells=True, record_root=out / 'record',
                                 options=cfg['actions'], climb_plan=plan,
                                 climb_budget=float(cfg['budget_s']))
    dec = v3_core.aggregate(rows, ['C1'], {'C1': 'synthetic'}, 'majority', proto,
                            threshold_mode='majority', applic=app,
                            options=cfg['actions'])
    v3_core.write_decision(out, core, 'FULL', rows, dec, {'candidates': ['C1'], 'climb_plan': plan})
    ex = v3_core.truth_execute(core, dec['chosen'], proto, out / 'truth_exec', 'FULL',
                               climb_plan=plan, climb_budget=float(cfg['budget_s']))
    ex_climb = v3_core.truth_execute(core, 'CLIMB', proto, out / 'truth_exec', 'TRUTH',
                                     climb_plan=plan, climb_budget=float(cfg['budget_s']))
    climb_rows = [r for r in rows if r['action'] == 'CLIMB']
    res = {'schema': 'stage5-smoke/v1', 'climb_rows': [
        {k: r.get(k) for k in ('action', 'success', 'outcome', 'cost', 't_end',
                               'plan_id', 'geometry_id', 'state_mode')} for r in climb_rows],
        'votes': dec['votes'], 'chosen': dec['chosen'], 'reason': dec['reason'],
        'exec': {'action': dec['chosen'], 'outcome': ex.get('outcome'),
                 't_end': ex.get('t_end')},
        'truth_climb': {'success': ex_climb.get('success'),
                        'outcome': ex_climb.get('outcome'),
                        't_end': ex_climb.get('t_end')},
        'options': cfg['actions'], 'budget_s': cfg['budget_s']}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
