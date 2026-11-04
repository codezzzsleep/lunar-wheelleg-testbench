"""G1 有限核对：U 外一致性、加载几何/初态/计划对比、预演 vs 执行。"""
import json, pathlib, sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_fuse, wheelleg_env, stage8_matrix2 as M
from stage10_g1 import variant_mesh, SCEN, XSPLIT


def occ_bbox(occ, o, p):
    idx = np.argwhere(occ)
    if not len(idx):
        return None
    lo = o + idx.min(0) * p; hi = o + (idx.max(0) + 1) * p
    return [round(float(x), 3) for x in np.r_[lo, hi]]


def main():
    out = ROOT / 'runs/v3/stage010/verify'; out.mkdir(parents=True, exist_ok=True)
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    tm = json.loads((truth / 'truth_manifest.json').read_text())
    snap = json.loads((truth / 'state_snapshot.json').read_text())
    z = np.load(truth / 'fusion/V.npz')
    V = z['shell']; space = z['space']; o = np.asarray(z['origin'], float); p = float(z['pitch'])
    dims = tuple(int(x) for x in z['dims'])
    xs = o[0] + (np.arange(dims[0]) + 0.5) * p
    ys = o[1] + (np.arange(dims[1]) + 0.5) * p
    zs = o[2] + (np.arange(dims[2]) + 0.5) * p
    grid = {'origin': o, 'pitch': p, 'dims': np.array(dims), 'xs': xs, 'ys': ys, 'zs': zs}
    U = (space == 0); FREE = (space == 2); BAND = (space == 1)
    base = trimesh.load(str(truth / 'truth/body_world.stl'), force='mesh', process=False)
    P_old, _ = v3_fuse.voxelize_columns(base, grid)
    ts = json.loads((truth / 'scene_spec.json').read_text())
    ref_env = wheelleg_env.WheelLegEnv(ts, max_seconds=120.0); ref_env.reset(seed=0)
    ref_env.restore_state(snap, mode='same_scene')
    ref_qpos = np.asarray(ref_env.data.qpos, float).copy()
    ref_qvel = np.asarray(ref_env.data.qvel, float).copy()
    report = {'schema': 'g1-verification/v1', 'x_split_used_for_variants': XSPLIT,
              'u_definition': 'space==0 from V artifact (not x split)', 'configs': {}}
    for name in ('rear_high', 'rear_short'):
        kind, param = SCEN[name]
        vm = variant_mesh(base, kind, param)
        P_new, _ = v3_fuse.voxelize_columns(vm, grid)
        diff_out = (P_old ^ P_new) & ~U
        diff_in = (P_old ^ P_new) & U
        # 观测壳与新真值的相容性
        shell_pts = np.argwhere(V)
        new_pts = np.argwhere(P_new)
        tree = cKDTree((new_pts + 0.5) * p + o)
        d_shell, _ = tree.query((shell_pts + 0.5) * p + o, k=1)
        free_viol = int((P_new & FREE).sum())
        obs = {'outside_U_diff_voxels': int(diff_out.sum()),
               'inside_U_diff_voxels': int(diff_in.sum()),
               'outside_U_diff_bbox_old_or_new': occ_bbox(diff_out, o, p),
               'shell_to_new_truth_max_mm': round(float(d_shell.max()) * 1000, 2),
               'shell_to_new_truth_p99_mm': round(float(np.percentile(d_shell, 99)) * 1000, 2),
               'shell_fraction_within_6mm': round(float((d_shell <= 0.006).mean()), 4),
               'new_truth_in_known_free_voxels': free_viol,
               'band_voxels': int(BAND.sum()), 'free_voxels': int(FREE.sum())}
        d = ROOT / 'runs/v3/stage010/g1' / name
        zf = np.load(next((d / 'full').glob('occ_*.npz'))); zt = np.load(next((d / 'truth').glob('occ_*.npz')))
        full_occ = zf['occupied']; truth_occ = zt['occupied']
        diff_scene = full_occ ^ truth_occ
        scene = {'full_voxels': int(full_occ.sum()), 'truth_voxels': int(truth_occ.sum()),
                 'diff_voxels': int(diff_scene.sum()),
                 'diff_bbox_m': occ_bbox(diff_scene, np.array([0.60, -0.80, 0.0]), 0.004)}
        # 场景 spec 未随运行落盘：用同一 make_scene 从实际 occ 重建（仅用于对比，不改动原目录）
        scenes = {}
        for arm, occ in (('full', full_occ), ('truth', truth_occ)):
            tmp = pathlib.Path('/tmp') / f'verify_{name}_{arm}'
            tmp.mkdir(parents=True, exist_ok=True)
            sp, _env, sha = M.make_scene(occ, tmp, f'verify_{name}_{arm}')
            scenes[arm] = {'spec': sp, 'scene_sha': sha,
                           'coll_manifest': json.loads(next((d / arm).glob('coll_*/manifest.json')).read_text())}
        # 初态：full / truth 两个场景按 project 恢复 S0，与参考 qpos 比较
        state = {}
        for arm in ('full', 'truth'):
            spec = scenes[arm]['spec']
            env = wheelleg_env.WheelLegEnv(spec, max_seconds=120.0); env.reset(seed=0)
            M.restore_common(env, snap, tm['s0_state_hash'], mode='project', ref=(ref_qpos, ref_qvel))
            state[arm] = {'qpos_max_abs_diff_vs_ref': float(np.abs(np.asarray(env.data.qpos) - ref_qpos).max()),
                          'restored_state_hash': env.save_state().get('state_hash')}
        # 计划与控制参数
        df = json.loads((d / 'full' / 'decision_FULL.json').read_text())
        do = json.loads((d / 'obs' / 'decision_OBS.json').read_text())
        plans = {'full': df.get('plan'), 'obs': do.get('plan')}
        # 预演 vs 执行轨迹
        def traj(p):
            idx = p / 'index.json'
            if not idx.exists():
                return None
            j = json.loads(idx.read_text())
            chunks = sorted(p.glob('chunk_*.npz'))
            q = np.concatenate([np.load(c)['qpos'] for c in chunks]) if chunks else None
            t = np.concatenate([np.load(c)['t'] for c in chunks]) if chunks else None
            return {'frames': int(j.get('frame_count', 0)), 'contacts_n': int(j.get('contacts_n', 0)),
                    't_end': round(float(t[-1]), 3) if t is not None else None,
                    'final_x': round(float(q[-1, 0]), 3) if q is not None else None}
        reh = {arm: traj(d / arm / 'record' / 'BODY_CLEARANCE') for arm in ('full', 'obs')}
        exe = {arm: traj(d / 'exec' / 'record' / arm.upper()) for arm in ('full', 'obs')}
        report['configs'][name] = {'observation_compat': obs, 'scene_diff': scene,
                                   'loaded_geometry': {k: {'scene_sha': v['scene_sha'],
                                                           'coll_manifest': v['coll_manifest']}
                                                       for k, v in scenes.items()},
                                   'loaded_state': state, 'plans': plans,
                                   'rehearsal_BODY': reh, 'execution_BODY': exe}
        print(json.dumps({name: {'outside_U_diff': obs['outside_U_diff_voxels'],
                                 'free_viol': obs['new_truth_in_known_free_voxels'],
                                 'shell_6mm_frac': obs['shell_fraction_within_6mm'],
                                 'scene_diff': scene['diff_voxels'],
                                 'state': state,
                                 'reh': reh, 'exec': exe}}, ensure_ascii=False))
    (out / 'g1_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
