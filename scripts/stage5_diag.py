"""Stage005 诊断：同一场景下 project 预演 vs same_scene 执行的 CLIMB 分歧。"""
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


def build(out):
    ledges = [{'face': 0.95, 'len': 1.40, 'y': -0.115}, {'face': 1.13, 'len': 1.22, 'y': 0.185}]
    pitch = 0.004
    nx, ny, nz = int(3.2 / pitch), int(1.2 / pitch), int(0.16 / pitch)
    xs = np.arange(nx) * pitch + pitch / 2
    ys = np.arange(ny) * pitch - 0.6 + pitch / 2
    zs = np.arange(nz) * pitch + pitch / 2
    X = xs[:, None, None]; Y = ys[None, :, None]; Z = zs[None, None, :]
    occ = np.zeros((nx, ny, nz), dtype=bool)
    for l in ledges:
        x0, x1 = l['face'], l['face'] + l['len']; y0, y1 = l['y'] - 0.225, l['y'] + 0.225
        occ |= (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1) & (Z <= 0.05)
    grid = out / 'occ.npz'
    np.savez_compressed(grid, occupied=occ, origin=np.array([0.0, -0.6, 0.0]),
                        pitch=np.float64(pitch), dims=np.array([nx, ny, nz], int),
                        content_sha=np.array('stage5-diag'),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    cand = out / 'cand'
    r = v3_core.build_collision(grid, cand, pitch=0.002, downsample=2)
    far = min(l['face'] + l['len'] for l in ledges)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=far + 0.6, name='stage5_diag',
                             objects=[{'posed_dir': str(cand)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    return spec, far, cand


def main():
    out = (ROOT / 'runs/v3/stage005/diag').resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = S4C.load()
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    spec, far, cand = build(out)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg['budget_s']))
    env.reset(seed=0)
    snap = env.save_state()
    gp = S4G.derive_skill_params({'face_FR': 0.95, 'face_FL': 1.13, 'top_z': 0.05,
                                  'far_x': far, 'landing': None, 'source': 'diag'})
    plan = {'action': 'CLIMB', 'params': gp['params'], 'applicable': True,
            'plan_id': 'diag_plan'}
    r_same = v3_core.run_climb_cell(spec, snap, plan, proto, mode='same_scene',
                                    record_dir=out / 'rec_same', budget=float(cfg['budget_s']))
    r_proj = v3_core.run_climb_cell(spec, snap, plan, proto, mode='project',
                                    record_dir=out / 'rec_proj', budget=float(cfg['budget_s']))
    res = {'same_scene': {k: r_same.get(k) for k in
                          ('success', 'outcome', 'reason', 't_end', 'env_t_end',
                           'max_seconds', 'termination', 'checks')},
           'project': {k: r_proj.get(k) for k in
                       ('success', 'outcome', 'reason', 't_end', 'env_t_end',
                        'max_seconds', 'termination', 'checks')},
           'snapshot_hash': snap.get('state_hash'),
           'snapshot_time': snap.get('env_t')}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
