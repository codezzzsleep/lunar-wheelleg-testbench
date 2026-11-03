"""v3 决策与执行核心：候选预演矩阵、多数/最坏聚合、真值执行。

口径（与 SPEC §8 一致）：
  · 预演：同一个 S0 快照投射到**独立候选环境**（restore mode='project'，标注 projected），
    每个候选 × 每个适用动作跑一次；success 记 safe_j(a)=1。
  · 聚合：votes(a)=Σ_j safe_j(a)，过票阈值 floor(n/2)+1；最坏规则要求 n/n。
    归一化到相同几何内容（full_occ_sha 相同）的任务只算一个独立几何票，任务分母保留。
  · 代价：每候选成功成本=真实执行秒数，失败=60；对候选取均值；破平局先票数后固定动作序。
  · 执行：两臂各自从同一个 S0 恢复到同一真值场景（mode='same_scene'），独立执行，
    不 reset、不重新出生、不多给 30 s；决策先原子落盘并记 SHA，再执行。

  python scripts/v3_core.py --state runs/v3/states/<sid> --arm FULL --decide
  python scripts/v3_core.py --state runs/v3/states/<sid> --arm FULL --execute
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import actions as ACT
import runner
import skills
import v7_soil
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 'v3-decision/v1'


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def sha_obj(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False)
                          .encode()).hexdigest()[:32]


def load_state(state_dir):
    state_dir = pathlib.Path(state_dir)
    st = json.loads((state_dir / 'state.json').read_text())
    spec = json.loads((state_dir / 'scene_spec.json').read_text())
    snap = json.loads((state_dir / 'state_snapshot.json').read_text())
    obs = json.loads((state_dir / 'observation' / 'observation.json').read_text())
    return {'dir': state_dir, 'state': st, 'spec': spec, 'snapshot': snap,
            'visible': obs['visible'], 'obs': obs}


def make_env(spec, proto, budget=None):
    sc = proto['scene']
    return wheelleg_env.WheelLegEnv(spec, control_hz=float(sc['control_hz']),
                                    max_seconds=float(budget or sc['budget_s']),
                                    v_ref=1.0, tip_deg=float(sc['tip_deg']))


def spec_with_geometry(spec, posed_dir):
    s = json.loads(json.dumps(spec))
    s['objects'] = [{'posed_dir': str(pathlib.Path(posed_dir).resolve())}]
    s.pop('object_material', None)
    return s


def geometry_dirs(cand_dir):
    """候选目录 -> (FULL posed_dir, OBS_ONLY posed_dir)。"""
    d = pathlib.Path(cand_dir)
    return {'FULL': d / 'coll', 'OBS_ONLY': None}


def classify(action, reason):
    if reason == 'success':
        return 'pass'
    if action == 'A0' and reason == 'abort':
        return 'safe_stop'
    return 'physical_failure'


def env_guard(env):
    """保存/恢复"跨动作复用同一个 env 会串味"的可变状态。

    实测：同一个 env 连续跑 R1(倾覆) 之后，L2 从 success 变成 time_limit。
    原因是土壤模块的 _soil_prev_force / _soil_limits / geom_friction 在
    restore_state(mode='project') 下**不会**恢复（跨场景不搬材质），上一回合的
    残余摩擦与反力会带进下一回合。预演矩阵必须在同一初始条件下比较动作。
    """
    return {'friction': env.model.geom_friction.copy(),
            'xfrc': env.data.xfrc_applied.copy(),
            'soil_limits': dict(getattr(env, '_soil_limits', None) or {}),
            'soil_prev': {k: np.asarray(v).copy()
                          for k, v in (getattr(env, '_soil_prev_force', None) or {}).items()},
            'soil_mu': dict(getattr(env, '_soil_ground_mu', None) or {}),
            'soil_stats': dict(getattr(env, '_soil_stats', None) or {})}


def env_unguard(env, g):
    env.model.geom_friction[:] = g['friction']
    env.data.xfrc_applied[:] = g['xfrc']
    env._soil_limits = dict(g['soil_limits'])
    env._soil_prev_force = {k: v.copy() for k, v in g['soil_prev'].items()}
    env._soil_ground_mu = dict(g['soil_mu'])
    env._soil_stats = dict(g['soil_stats'])


def run_action(env, snapshot, action, visible, *, mode='project', seed=0,
               record=False, record_dir=None, record_meta=None):
    sk = skills.make_skill(action)
    rec = None
    if record_dir is not None:
        import v3_record
        meta = dict(record_meta or {})
        meta.update({'action': action, 'mode': mode, 'seed': int(seed),
                     'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')})
        rec = v3_record.Recorder(record_dir, meta, hz=50.0)
    ep = runner.EpisodeRunner(env, sk, visible=visible, seed=seed,
                              record_trajectory=record, recorder=rec)
    t0 = time.time()
    out = ep.run_from_state(snapshot, mode=mode)
    wall = time.time() - t0
    t_start = out.get('t_start')
    t_end = out.get('t_end')
    cost = (float(t_end) - float(t_start)) if (out['success'] and t_start is not None
                                               and t_end is not None) else 60.0
    row = {'action': action, 'ok': True, 'success': bool(out['success']),
           'abort': bool(out['abort']), 'reason': out['reason'],
           'outcome': classify(action, out['reason']),
           'final_x': out['final_x'], 'displacement_x': out['displacement_x'],
           't_start': t_start, 't_end': t_end, 'cost': cost,
           'max_tilt': out['max_tilt'], 'contact': out['contact'],
           'triggered': out['triggered'], 'state_mode': out.get('state_mode', mode),
           'wall_s': round(wall, 3), 'steps': out['steps'],
           'n_actions': out['n_actions'],
           'action_fingerprint': out['action_fingerprint'],
           'initial_full_hash': out.get('initial_full_hash'),
           'phases': out.get('phases'), 'trajectory': out.get('trajectory')}
    if rec is not None:
        row['trajectory_ref'] = rec.close()
    return row


def truth_spec(state):
    spec = json.loads(json.dumps(state['spec']))
    spec.pop('object_material', None)
    return spec


def rehearse_on_spec(state, spec, snapshot, proto, seed=0, mode='same_scene'):
    """在给定场景 spec（可以是真值网格）上跑完整动作矩阵。"""
    visible = state['visible']
    ch = float(proto['scene']['channel_half_m'])
    opts = [a for a in ACT.OPTIONS if a != ACT.FALLBACK]
    applic = {a: ACT.applicable(a, visible, ch) for a in opts}
    rows = []
    for a in [x for x in opts if applic[x][0]] + [ACT.FALLBACK]:
        try:
            env = make_env(spec, proto)
            r = run_action(env, snapshot, a, visible, mode=mode, seed=seed)
            del env
        except Exception as e:  # noqa: BLE001
            r = {'action': a, 'ok': False, 'error_class': 'episode',
                 'error': f'{type(e).__name__}: {e}', 'success': False,
                 'outcome': 'rehearsal_error', 'cost': 60.0}
        r['candidate'] = 'truth' if mode == 'same_scene' else 'scene'
        r['applicable'] = True if a not in applic else bool(applic[a][0])
        rows.append(r)
    return rows, {a: (bool(applic[a][0]), applic[a][1]) for a in opts}


def rehearse(state, geom, snapshot, proto, seed=0, record_cells=False,
             record_root=None):
    """对一组几何候选跑完整预演矩阵。geom: {candidate_id: posed_dir}

    record_cells=True 时每个矩阵格写一条 >=50Hz 全状态轨迹到
    record_root/<candidate>/<action>/，矩阵行里只放 trajectory_ref。
    """
    visible = state['visible']
    ch = float(proto['scene']['channel_half_m'])
    opts = [a for a in ACT.OPTIONS if a != ACT.FALLBACK]
    applic = {a: ACT.applicable(a, visible, ch) for a in opts}
    rows = []
    for cid, pd in geom.items():
        spec = spec_with_geometry(state['spec'], pd)
        for a in [x for x in opts if applic[x][0]] + [ACT.FALLBACK]:
            try:
                # 每个动作一个全新 env：复用 env 会把上一回合的土壤/摩擦残余带进来
                # （实测同一 env 里 R1 倾覆后 L2 从 success 变 time_limit）
                env = make_env(spec, proto)
                rdir = None
                if record_cells:
                    base = pathlib.Path(record_root or (pathlib.Path(state['state_dir'])
                                                        / 'matrix'))
                    rdir = base / str(cid) / str(a)
                r = run_action(env, snapshot, a, visible, mode='project', seed=seed,
                               record_dir=rdir,
                               record_meta={'scenario': state.get('state_id'),
                                            'candidate': cid, 'method': 'rehearsal',
                                            'state_mode': 'project'})
                del env
            except Exception as e:  # noqa: BLE001
                r = {'action': a, 'ok': False, 'error_class': 'episode',
                     'error': f'{type(e).__name__}: {e}', 'success': False,
                     'outcome': 'rehearsal_error', 'cost': 60.0}
            r['candidate'] = cid
            r['applicable'] = True if a not in applic else bool(applic[a][0])
            rows.append(r)
    return rows, {a: (bool(applic[a][0]), applic[a][1]) for a in opts}


def aggregate(rows, cand_ids, geom_sha, rule, proto, threshold_mode='majority',
              applic=None):
    """把逐候选矩阵聚合成一个决策。"""
    opts = [a for a in ACT.OPTIONS if a != ACT.FALLBACK]
    by_c = {}
    errors = []
    for r in rows:
        if not r.get('ok', True):
            errors.append({'candidate': r.get('candidate'), 'error_class': r.get('error_class'),
                           'error': r.get('error')})
            continue
        by_c.setdefault(r['candidate'], {})[r['action']] = r
    required = [a for a in opts if (applic is None or applic.get(a, (True, None))[0])]
    required = required + [ACT.FALLBACK]
    valid = [c for c in cand_ids if c in by_c
             and all(a in by_c[c] for a in required)]
    # 相同几何内容只算一个独立票
    groups = {}
    for c in valid:
        g = geom_sha.get(c) or c
        groups.setdefault(g, []).append(c)
    unique_rep = [v[0] for v in groups.values()]
    n = len(valid)
    n_unique = len(unique_rep)
    need = (n_unique // 2 + 1) if threshold_mode == 'majority' else n_unique
    votes, costs = {}, {}
    for a in opts:
        if a not in required:
            votes[a], costs[a] = 0, 60.0
            continue
        v = sum(1 for c in unique_rep if by_c[c][a]['success'])
        cs = [by_c[c][a]['cost'] if by_c[c][a]['success'] else 60.0 for c in valid]
        votes[a] = v
        costs[a] = round(float(np.mean(cs)), 4) if cs else 60.0
    passing = [a for a in opts if a in required and votes[a] >= need and need > 0]
    order = {a: i for i, a in enumerate(ACT.OPTIONS)}
    if passing:
        chosen = sorted(passing, key=lambda a: (costs[a], -votes[a], order[a]))[0]
        reason = 'majority_traversal' if threshold_mode == 'majority' else 'worst_case_traversal'
    else:
        chosen, reason = ACT.FALLBACK, 'no_safe_traversal'
    return {'rule': f'{threshold_mode}/v1', 'version': VERSION,
            'n_tasks': len(cand_ids), 'n_valid': n, 'n_unique_geometries': n_unique,
            'threshold': need, 'votes': votes, 'mean_cost_s': costs,
            'chosen': chosen, 'safe_set': passing, 'reason': reason,
            'errors': errors,
            'per_candidate': {c: {a: {'success': by_c[c][a]['success'],
                                      'reason': by_c[c][a]['reason'],
                                      'cost': by_c[c][a]['cost'],
                                      't_end': by_c[c][a]['t_end'],
                                      'final_x': by_c[c][a]['final_x']}
                                  for a in required if a in by_c[c]}
                              for c in valid}}


def write_decision(out_dir, state, arm, rows, dec, extra=None):
    d = pathlib.Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    with (d / f'matrix_{arm}.jsonl').open('w') as f:
        for r in rows:
            rr = {k: v for k, v in r.items() if k not in ('trajectory', 'trajectory_arrays')}
            f.write(json.dumps(rr, ensure_ascii=False) + '\n')
    matrix_sha = sha256_file(d / f'matrix_{arm}.jsonl')
    rec = {'schema': 'v3-decision/v1', 'state_id': state['state']['state_id'],
           'arm': arm, 'decided_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
           'state_hash': state['state'].get('state_hash'),
           'visible': state['visible'],
           'matrix_sha256': matrix_sha,
           'decision': dec,
           **(extra or {})}
    rec['decision_sha'] = sha_obj({k: v for k, v in rec.items() if k != 'decided_at'})
    (d / f'decision_{arm}.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def truth_execute(state, action, proto, out_dir, arm, seed=0, mode='same_scene'):
    """在真值场景从同一个 S0 续行执行。"""
    spec = json.loads(json.dumps(state['spec']))
    spec.pop('object_material', None)
    env = make_env(spec, proto)
    try:
        r = run_action(env, state['snapshot'], action, state['visible'],
                       mode=mode, seed=seed, record=True,
                       record_dir=pathlib.Path(out_dir) / 'record' / str(arm),
                       record_meta={'scenario': state['state'].get('state_id'),
                                    'method': arm, 'state_mode': mode,
                                    'action': action})
    except Exception as e:  # noqa: BLE001
        r = {'action': action, 'ok': False, 'error_class': 'episode',
             'error': f'{type(e).__name__}: {e}', 'outcome': 'pipeline_failure',
             'success': False, 'cost': 60.0}
    r['arm'] = arm
    r['state_mode'] = mode
    r['run_id'] = f"{state['state']['state_id']}_{arm}_{int(time.time())}"
    traj = r.pop('trajectory', None)
    traj_ref = r.pop('trajectory_ref', None)
    if traj_ref:
        r['trajectory_ref'] = traj_ref
        r['record_hz'] = traj_ref.get('record_hz')
        r['trajectory_frames'] = traj_ref.get('frame_count')
    d = pathlib.Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    if traj:
        with (d / f'trajectory_{arm}.jsonl').open('w') as f:
            for fr in traj:
                f.write(json.dumps(fr, ensure_ascii=False) + '\n')
    with (d / f'execution_{arm}.jsonl').open('a') as f:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
    (d / f'execution_{arm}.json').write_text(json.dumps(r, ensure_ascii=False, indent=2))
    return r


def downsample_occ(occ_npz, out_npz, factor):
    """占据按 factor 块降采样（any），写一个新的 occ.npz（pitch×factor）。"""
    d = np.load(occ_npz)
    occ = np.asarray(d['occupied'], dtype=bool)
    origin = np.asarray(d['origin'], float)
    pitch = float(d['pitch'])
    if int(factor) <= 1:
        return str(occ_npz), pitch
    f = int(factor)
    nx, ny, nz = occ.shape
    occ = occ[:nx // f * f, :ny // f * f, :nz // f * f]
    occ = occ.reshape(nx // f, f, ny // f, f, nz // f, f).any(axis=(1, 3, 5))
    p2 = pitch * f
    import hashlib
    np.savez_compressed(out_npz, occupied=occ, origin=origin, pitch=np.float64(p2),
                        dims=np.asarray(occ.shape, int),
                        content_sha=np.array(hashlib.sha256(
                            np.ascontiguousarray(occ).tobytes()).hexdigest()[:32]),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    return str(out_npz), p2


COLLISION_ALGO_VERSION = 'v3-collision/2'


def occ_identity(occ_npz):
    """源占据的内容身份：内容 SHA + 栅格参数 + 占据数。跨网格不能直接比较。"""
    import hashlib
    z = np.load(occ_npz)
    occ = np.asarray(z['occupied'])
    origin = [float(x) for x in np.asarray(z['origin']).tolist()]
    pitch = float(z['pitch'])
    dims = [int(x) for x in np.asarray(z['dims']).tolist()]
    h = hashlib.sha256(np.ascontiguousarray(occ).tobytes()).hexdigest()
    return {'occ_sha256': h, 'origin': origin, 'pitch': pitch, 'dims': dims,
            'n_occ': int(occ.sum()), 'shape': list(occ.shape),
            'convention': str(z['convention']) if 'convention' in z else None}


def build_collision(occ_npz, out_dir, pitch=0.002, downsample=1,
                    algo=COLLISION_ALGO_VERSION, force=False):
    """占据 -> box union 碰撞件；缓存 key 覆盖源内容/栅格/降采样/盒尺寸/算法版本。

    读取缓存时逐项验证（key、算法、盒文件实际存在且数量一致、_occ_ds 内容），
    缺源、半截 manifest、源或参数不一致一律拒绝并重建，绝不返回 cached=True。
    """
    import hashlib
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ident = occ_identity(occ_npz)
    params = {'downsample': int(downsample), 'box_pitch': float(pitch) * int(downsample),
              'algo': algo}
    key = hashlib.sha256(json.dumps({'src': ident, 'params': params},
                                    sort_keys=True).encode()).hexdigest()
    man_p = out / 'manifest.json'
    stale_reason = None
    if not force and man_p.is_file():
        try:
            man = json.loads(man_p.read_text())
            if man.get('cache_key') != key:
                stale_reason = 'cache_key_mismatch'
            elif man.get('algo') != algo:
                stale_reason = 'algo_mismatch'
            elif not man.get('boxes'):
                stale_reason = 'empty_boxes'
            else:
                parts = sorted((out / 'parts').glob('box_*.stl')) if (out / 'parts').is_dir() else []
                n_boxes = int(man.get('n_boxes') or len(man['boxes']))
                if len(parts) != n_boxes:
                    stale_reason = f'parts_count_mismatch:{len(parts)}!={n_boxes}'
                elif not (out / '_occ_ds.npz').is_file():
                    stale_reason = 'missing_downsampled_occ'
        except Exception as e:  # noqa: BLE001
            stale_reason = f'manifest_unreadable:{type(e).__name__}'
        if stale_reason is None:
            return {'ok': True, 'cached': True, 'manifest': man,
                    'n_boxes': man.get('n_boxes'), 'collision_sha': man.get('collision_sha'),
                    'cache_key': key, 'source': ident}
        # 明确记下为什么重建，不静默复用
        (out / 'cache_invalidated.json').write_text(json.dumps(
            {'schema': 'v3-collision-cache/v1', 'reason': stale_reason,
             'expected_key': key, 'algo': algo, 'source': ident,
             'at': time.strftime('%Y-%m-%dT%H:%M:%S%z')},
            ensure_ascii=False, indent=2))
        for f in (out / 'manifest.json',):
            if f.exists():
                f.unlink()
    src, eff_pitch = downsample_occ(occ_npz, out / '_occ_ds.npz', downsample)
    cmd = [sys.executable, str(ROOT / 'scripts/collision_box_union.py'),
           '--occ', str(src), '--out', str(out), '--pitch', str(eff_pitch)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {'ok': False, 'error': (r.stderr or r.stdout)[-800:]}
    man = json.loads((out / 'manifest.json').read_text())
    man.update({'cache_key': key, 'algo': algo, 'source': ident, 'params': params,
                'cache_rebuilt_reason': stale_reason,
                'rebuilt_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')})
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    return {'ok': True, 'cached': False, 'n_boxes': man.get('n_boxes'),
            'collision_sha': man.get('collision_sha'), 'cache_key': key,
            'source': ident, 'cache_rebuilt_reason': stale_reason}


def downsample_occ(occ_npz, out_npz, factor):
    """占据按 factor 块降采样（any），写一个新的 occ.npz（pitch×factor）。"""
    d = np.load(occ_npz)
    occ = np.asarray(d['occupied'], dtype=bool)
    origin = np.asarray(d['origin'], float)
    pitch = float(d['pitch'])
    if int(factor) <= 1:
        return str(occ_npz), pitch
    f = int(factor)
    nx, ny, nz = occ.shape
    occ = occ[:nx // f * f, :ny // f * f, :nz // f * f]
    occ = occ.reshape(nx // f, f, ny // f, f, nz // f, f).any(axis=(1, 3, 5))
    p2 = pitch * f
    import hashlib
    np.savez_compressed(out_npz, occupied=occ, origin=origin, pitch=np.float64(p2),
                        dims=np.asarray(occ.shape, int),
                        content_sha=np.array(hashlib.sha256(
                            np.ascontiguousarray(occ).tobytes()).hexdigest()[:32]),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    return str(out_npz), p2


def build_collision(occ_npz, out_dir, pitch=0.002, downsample=1):
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if int(downsample) > 1 and (out / 'manifest.json').is_file():
        return {'ok': True, 'cached': True,
                'manifest': json.loads((out / 'manifest.json').read_text()),
                'n_boxes': json.loads((out / 'manifest.json').read_text()).get('n_boxes'),
                'collision_sha': json.loads((out / 'manifest.json').read_text()).get('collision_sha')}
    src, eff_pitch = downsample_occ(occ_npz, out / '_occ_ds.npz', downsample)
    cmd = [sys.executable, str(ROOT / 'scripts/collision_box_union.py'),
           '--occupancy', str(src), '--out', str(out), '--pitch', str(eff_pitch)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        return {'ok': False, 'error': (r.stderr or r.stdout)[-400:]}
    man = json.loads((out / 'manifest.json').read_text())
    return {'ok': True, 'manifest': man, 'n_boxes': man.get('n_boxes'),
            'collision_sha': man.get('collision_sha'), 'pitch_m': eff_pitch,
            'downsample': int(downsample)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--arm', default='FULL')
    ap.add_argument('--candidates', nargs='*', default=None,
                    help='candidate_id=posed_dir 形式；缺省自动发现')
    ap.add_argument('--out', default=None)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--decide', action='store_true')
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--rule', default='majority')
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    st = load_state(ROOT / a.state)
    out = pathlib.Path(a.out or (ROOT / a.state / 'decision'))
    if a.decide:
        if a.candidates:
            geom = dict(x.split('=', 1) for x in a.candidates)
        else:
            base = pathlib.Path(a.state) / 'candidates'
            geom = {p.name: str(p / 'coll') for p in sorted(base.glob('*/'))
                    if (p / 'coll' / 'manifest.json').is_file()}
        geom_sha = {}
        for cid in geom:
            p = pathlib.Path(a.state) / 'candidates' / cid / 'fused' / 'manifest.json'
            if p.is_file():
                geom_sha[cid] = json.loads(p.read_text()).get('full_occ_sha')
        rows, applic = rehearse(st, geom, st['snapshot'], proto, seed=a.seed)
        dec = aggregate(rows, list(geom), geom_sha, a.rule, proto,
                        threshold_mode=a.rule)
        rec = write_decision(out, st, a.arm, rows, dec,
                             extra={'applicability': {k: list(v) for k, v in applic.items()},
                                    'geometry': geom})
        print(json.dumps({'arm': a.arm, 'chosen': dec['chosen'], 'reason': dec['reason'],
                          'votes': dec['votes'], 'n_valid': dec['n_valid'],
                          'decision_sha': rec['decision_sha']}, ensure_ascii=False))
        return
    if a.execute:
        dec = json.loads((out / f'decision_{a.arm}.json').read_text())
        action = dec['decision']['chosen']
        r = truth_execute(st, action, proto, out, a.arm, seed=a.seed)
        print(json.dumps({'arm': a.arm, 'action': action, 'outcome': r.get('outcome'),
                          'reason': r.get('reason'), 'final_x': r.get('final_x'),
                          't_end': r.get('t_end')}, ensure_ascii=False))
        return
    raise SystemExit('需要 --decide 或 --execute')


if __name__ == '__main__':
    main()
