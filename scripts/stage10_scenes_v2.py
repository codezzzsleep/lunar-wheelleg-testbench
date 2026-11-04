"""U-consistent 场景：只在 space==0 内修改真值占据；固定 V/S0。"""
import json, pathlib, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_fuse, trimesh

SCEN = {
    'ref':      ('none', None),
    'len_short':('cut_x', 1.02),
    'len_mid':  ('cut_x', 1.08),
    'len_long': ('cut_x', 1.14),
    'rear_low': ('low_z', 0.18),
    'rear_high':('high_z', 0.30),
}
RULE = {'schema': 'g1v2-screening-rule/v1',
        'denominator': len(SCEN),
        'arms': ['perfect_completion V | (truth & U)', 'obs_only V'],
        'execution': 'both chosen plans executed on the same complete truth scene (project S0)',
        'budget_s': 120, 'actions': 'configs/stage6_protocol.json',
        'decision_rule': 'single-candidate majority (threshold=1), unchanged',
        'primary': 'decision difference and outcome difference',
        'secondary': 'cost/time; OBS is never weakened',
        'families': {'backside_length': ['len_short','len_mid','len_long'],
                     'hidden_height': ['rear_low','rear_high']},
        'controls': ['ref']}


def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    z = np.load(truth / 'fusion/V.npz')
    V = z['shell']; space = z['space']; U = (space == 0)
    o = np.asarray(z['origin'], float); p = float(z['pitch'])
    dims = tuple(int(x) for x in z['dims'])
    xs = o[0] + (np.arange(dims[0]) + 0.5) * p
    ys = o[1] + (np.arange(dims[1]) + 0.5) * p
    zs = o[2] + (np.arange(dims[2]) + 0.5) * p
    grid = {'origin': o, 'pitch': p, 'dims': np.array(dims), 'xs': xs, 'ys': ys, 'zs': zs}
    base = trimesh.load(str(truth / 'truth/body_world.stl'), force='mesh', process=False)
    P_old, _ = v3_fuse.voxelize_columns(base, grid)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    out = ROOT / 'runs/v3/stage010/g1v2'; out.mkdir(parents=True, exist_ok=True)
    rep = {'schema': 'g1v2-scenes/v1', 'rule': RULE, 'scenarios': {}}
    for name, (kind, param) in SCEN.items():
        P = P_old.copy()
        if kind == 'cut_x':
            P &= ~(U & (X > param))
        elif kind == 'low_z':
            P &= ~(U & (X > 1.02) & (Z > param))
        elif kind == 'high_z':
            add = U & (X > 1.02) & (X < 1.16) & (Z <= param) & (np.abs(Y) < 0.14)
            P |= add
        outside = (P ^ P_old) & ~U
        free_hit = int((P & (space == 2)).sum())
        # V 壳支撑：到新占有体素中心的最近距离
        from scipy.spatial import cKDTree
        pts = np.argwhere(V); newp = np.argwhere(P)
        d, _ = cKDTree((newp + 0.5) * p + o).query((pts + 0.5) * p + o, k=1)
        rep['scenarios'][name] = {'kind': kind, 'param': param,
                                  'outside_U_xor': int(outside.sum()),
                                  'known_free_hits': free_hit,
                                  'n_voxels': int(P.sum()), 'delta_vs_old': int((P ^ P_old).sum()),
                                  'shell_max_mm': round(float(d.max()) * 1000, 2),
                                  'shell_p99_mm': round(float(np.percentile(d, 99)) * 1000, 2),
                                  'z_max': float(zs[P.any(axis=(0, 1))].max()) if P.any() else None}
        np.savez_compressed(out / f'occ2_{name}.npz', P=P, origin=o, pitch=p, dims=np.array(dims))
        print(name, rep['scenarios'][name])
    (out / 'scenes.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
