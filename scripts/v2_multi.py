"""v2 多候选：同一观测组的 6 个候选 → 融合/碰撞/预演 → 单候选 vs 多候选。

  python scripts/v2_multi.py --rock P06 --state S1 --obs <obs dir> --cands <dir> --out <dir>

v3 改动（2026-11-02，融合缺陷修复后）：
  * 只接受 manifest.json + artifact_status=complete + 输入身份匹配的融合产物；
    不再仅凭 occ.npz 存在就继续碰撞/预演；
  * 复用已通过身份校验的资产（可断点续跑），--force 才重建；
  * --ablate 生成“同一候选的生成贡献消融”资产（只删未知区父先验），并跑
    first_ablation / multi_ablation 两行。
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import collision_asset as CA
import common_planner as CP
import runner
import skills
import v7_holdout_scan as HS
import v7_soil
import wheelleg_env

PY_ = sys.executable
SOILS_CURRENT = ('nominal',)          # 当前土壤（单点诊断）
SOILS_ABLATION = ('nominal', 'low_traction', 'high_drag')  # 三档敏感性，不混入主比较
SOIL_POINTS_PATH = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1/soil_c/soil_c.json'


def _load_soil_points():
    try:
        d = json.loads(SOIL_POINTS_PATH.read_text())
        pts = d['points'][:5]
        return {f'p{i}': p for i, p in enumerate(pts)}
    except Exception:
        return {}


SOIL_POINTS = _load_soil_points()     # 冻结的 5 点规划集（区间四角+中心）
SOILS_POINTS = tuple(sorted(SOIL_POINTS))
FUSE_VERSION = 'fuse-observed/v3'
FUSE_SCHEMA = 'fused-asset/v3'
FUSE_CONFIG = 'configs/unseen_v7_r1_fusion_gapfill.json'
FUSE_CODE = ROOT / 'scripts' / 'fuse_observed.py'


def build_env(rock, case, seed, pose, soil, objects=None):
    env = HS.make_env_for_rock(rock, case)
    spec = dict(env.spec)
    if soil in SOIL_POINTS:                 # 冻结 5 点集：标签 p0..p4
        spec['soil'] = {'mode': 'soil', 'label': soil,
                        'params': SOIL_POINTS[soil]}
    else:
        r = v7_soil.resolve(soil)
        spec['soil'] = ({'mode': 'rigid', 'label': soil} if r.get('mode') == 'rigid'
                        else {'mode': 'soil', 'label': r.get('label'),
                              'params': r['params']})
    if objects is not None:
        spec['objects'] = objects
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
    env.init_perturbation = {'lateral': abs(pose[0]), 'yaw': abs(pose[1])}
    env.reset(seed=seed)
    return env


def _sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _sha_dir(d):
    d = pathlib.Path(d)
    h = hashlib.sha256()
    for f in sorted(d.rglob('*')):
        if not f.is_file():
            continue
        h.update(str(f.relative_to(d)).encode())
        if f.stat().st_size < 8 << 20:
            h.update(f.read_bytes())
        else:
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def validate_fused(fus, obs_dir, parent_dir, need_ablation=False):
    """正式资产的唯一准入：完整清单 + 本次输入身份 + 产物哈希一致。"""
    fus = pathlib.Path(fus)
    if (fus / 'failed.json').exists():
        return False, 'failed_marker', None
    if (fus / 'partial.json').exists():
        return False, 'partial_present', None
    man_p = fus / 'manifest.json'
    if not man_p.is_file():
        return False, 'manifest_missing', None
    try:
        man = json.loads(man_p.read_text())
    except Exception as e:
        return False, f'manifest_unreadable:{type(e).__name__}', None
    if man.get('schema') != FUSE_SCHEMA or man.get('version') != FUSE_VERSION:
        return False, f"version_mismatch:{man.get('schema')}/{man.get('version')}", man
    if man.get('artifact_status') != 'complete':
        return False, 'artifact_incomplete', man
    body, occ = fus / 'body.stl', fus / 'occ.npz'
    if not body.is_file() or not occ.is_file():
        return False, 'artifact_missing_file', man
    if man.get('world_sha') != _sha_file(body):
        return False, 'world_sha_mismatch', man
    try:
        z = np_load(occ)
        arr = z['occupied'].astype(bool)
        content = hashlib.sha256(arr.tobytes()).hexdigest()
        if str(z['content_sha']) != content:
            return False, 'occ_content_sha_mismatch', man
        if man.get('content_sha') != content:
            return False, 'manifest_content_sha_mismatch', man
    except Exception as e:
        return False, f'occ_unreadable:{type(e).__name__}', man
    inputs = man.get('inputs') or {}
    if inputs.get('observation_sha') != _sha_dir(obs_dir):
        return False, 'observation_sha_mismatch', man
    psha = (inputs.get('parent_mesh_sha') or [None])[0]
    if psha != _sha_file(pathlib.Path(parent_dir) / 'body.stl'):
        return False, 'parent_sha_mismatch', man
    if inputs.get('code_sha256') != _sha_file(FUSE_CODE):
        return False, 'fusion_code_sha_mismatch', man
    if need_ablation and not man.get('ablation'):
        return False, 'not_an_ablation_asset', man
    if (not need_ablation) and man.get('ablation'):
        return False, 'ablation_asset_in_full_slot', man
    return True, 'ok', man


def np_load(p):
    import numpy as np
    return np.load(p)


def validate_collision(coll, occ_sha, n_vox):
    coll = pathlib.Path(coll)
    man_p = coll / 'manifest.json'
    if not man_p.is_file():
        return False, 'collision_manifest_missing'
    try:
        man = json.loads(man_p.read_text())
    except Exception as e:
        return False, f'collision_manifest_unreadable:{type(e).__name__}'
    ci = man.get('cache_identity') or {}
    if ci.get('source_sha') != occ_sha:
        return False, 'collision_source_sha_mismatch'
    if int(man.get('n_source_voxels', -1)) != int(n_vox):
        return False, 'collision_voxel_count_mismatch'
    if not man.get('boxes') or int(man.get('n_boxes', 0)) < 1:
        return False, 'collision_no_boxes'
    for rel in man.get('parts') or []:
        if not (coll / rel).is_file():
            return False, f'collision_part_missing:{rel}'
    return True, 'ok'


def _write_error(d, stage, rc, stdout, stderr, extra=None):
    rec = {'stage': stage, 'returncode': rc,
           'stdout_tail': (stdout or '')[-2000:],
           'stderr_tail': (stderr or '')[-4000:]}
    if extra:
        rec.update(extra)
    (pathlib.Path(d) / 'prep_error.json').write_text(
        json.dumps(rec, ensure_ascii=False, indent=2))


def prep_raw(glb, rock, case, out, tag, vis):
    import trimesh
    d = out / tag
    d.mkdir(parents=True, exist_ok=True)
    m = trimesh.load(glb, force='mesh', process=True)
    Hv = float(vis['H_vis'])
    m.apply_scale(Hv / max(1e-6, float(m.bounds[1][2] - m.bounds[0][2])))
    m.apply_translation([0, 0, -m.bounds[0][2]])
    m.apply_translation([case['obstacle_x'], 0.0, 0.0])
    pw = d / 'parent'
    pw.mkdir(exist_ok=True)
    m.export(pw / 'body.stl')
    return str((pw / 'body.stl').relative_to(ROOT))


def _build_collision(fus, coll, tag, d):
    r = subprocess.run([PY_, 'scripts/collision_box_union.py', '--occupancy',
                        str(fus / 'occ.npz'), '--out', str(coll),
                        '--pitch', '0.0025', '--hypothesis-id', tag],
                       cwd=str(ROOT), capture_output=True, text=True)
    z = np_load(fus / 'occ.npz')
    ok2, why2 = validate_collision(coll, str(z['content_sha']),
                                   int(z['occupied'].sum()))
    if not ok2:
        _write_error(d, 'collision', r.returncode, r.stdout, r.stderr,
                     {'validation': why2})
        return None, why2
    return str(coll.relative_to(ROOT)), 'ok'


def prep(glb, rock, case, obs_dir, out, tag, vis, force=False):
    """正式入口：align24 配准（24 朝向/贴地/尺度）→ 融合 → 碰撞。

    融合产物按 manifest + 输入身份校验；通过则复用，缺碰撞时只补碰撞。
    返回 (碰撞资产相对路径 | None, 状态 dict)。
    """
    import numpy as np
    import trimesh
    d = out / tag
    d.mkdir(parents=True, exist_ok=True)
    fus, coll, pw = d / 'fused', d / 'coll', d / 'parent'
    man, reused_fused = None, False
    if not force and (fus / 'manifest.json').is_file() and (pw / 'body.stl').is_file():
        ok, why, m = validate_fused(fus, obs_dir, pw)
        if ok:
            man, reused_fused = m, True
        else:
            (d / 'reuse_rejected.txt').write_text(f'{why}\n')
    if man is None:
        # 1. 配准（已有 parent 时复用，不重复搜索）
        if force or not (pw / 'body.stl').is_file():
            aj = d / 'align.json'
            r = subprocess.run([PY_, 'scripts/align24.py', '--candidate', str(glb),
                                '--obs', str(obs_dir), '--out', str(aj),
                                '--time-budget-s', '240'], cwd=str(ROOT),
                               capture_output=True, text=True)
            # align24 在没有任何位姿过阈值时返回非零，但仍会写 best（候选可见面
            # 质量差，不是摆放错误）。允许进入融合并如实记录 pass；只有连
            # best/M 都没有才算配准失败。
            if not aj.is_file():
                _write_error(d, 'align24', r.returncode, r.stdout, r.stderr)
                return None, {'status': 'align_failed', 'returncode': r.returncode}
            arec = json.loads(aj.read_text())
            best = arec.get('best') or arec
            if best.get('M') is None:
                _write_error(d, 'align24_no_pose', r.returncode, r.stdout, r.stderr)
                return None, {'status': 'align_failed_no_pose',
                              'returncode': r.returncode}
            M = np.asarray(best['M'], dtype=float)
            m = trimesh.load(glb, force='mesh', process=True)
            m.apply_transform(M)
            pw.mkdir(exist_ok=True)
            m.export(pw / 'body.stl')
            (d / 'align_used.json').write_text(json.dumps(
                {k: best.get(k) for k in ('pass', 'scale', 'yaw',
                                          'z_min_world_m', 'native')}
                | {'align_returncode': r.returncode}, ensure_ascii=False, indent=1))
        # 2. 融合：失败必须被识别，不能凭残留 occ.npz 继续
        r = subprocess.run([PY_, 'scripts/fuse_observed.py', '--observation', str(obs_dir),
                            '--method', 'H5_F', '--parent-world', str(pw),
                            '--parent-id', tag, '--out', str(fus), '--pitch', '0.0025',
                            '--config', FUSE_CONFIG], cwd=str(ROOT),
                           capture_output=True, text=True)
        ok, why, man = validate_fused(fus, obs_dir, pw)
        if not ok:
            _write_error(d, 'fuse', r.returncode, r.stdout, r.stderr,
                         {'validation': why})
            return None, {'status': 'fusion_invalid', 'reason': why,
                          'returncode': r.returncode}
    # 3. 碰撞（独立复用/重建）
    if not force and (coll / 'manifest.json').is_file():
        z = np_load(fus / 'occ.npz')
        ok2, _ = validate_collision(coll, str(z['content_sha']),
                                    int(z['occupied'].sum()))
        if ok2:
            return str(coll.relative_to(ROOT)), {
                'status': 'reused' if reused_fused else 'fused_reused_collision_built',
                'fused': man}
    asset, why2 = _build_collision(fus, coll, tag, d)
    if not asset:
        return None, {'status': 'collision_invalid', 'reason': why2}
    return asset, {'status': 'reused_fused' if reused_fused else 'built', 'fused': man}


def prep_ablation(out, tag, obs_dir, force=False):
    """同一候选的生成贡献消融：复用同一 parent/可见部分，只删未知区父先验。"""
    import numpy as np
    d = out / tag
    fus_src, parent = d / 'fused', d / 'parent'
    ok, why, man = validate_fused(fus_src, obs_dir, parent)
    if not ok:
        return None, {'status': 'source_invalid', 'reason': why}
    abl = out / f'{tag}_abl'
    fus = abl / 'fused'
    coll = abl / 'coll'
    fus.mkdir(parents=True, exist_ok=True)
    if not force and (fus / 'manifest.json').is_file() and (coll / 'manifest.json').is_file():
        ok_ab, why_ab, man_ab = validate_fused(fus, obs_dir, parent, need_ablation=True)
        if ok_ab:
            z = np_load(fus / 'occ.npz')
            ok2, why2 = validate_collision(coll, str(z['content_sha']),
                                           int(z['occupied'].sum()))
            if ok2:
                return str(coll.relative_to(ROOT)), {'status': 'reused', 'fused': man_ab}
            why_ab = f'collision:{why2}'
        (abl / 'reuse_rejected.txt').write_text(f'{why_ab}\n')
    r = subprocess.run([PY_, 'scripts/fuse_observed.py', '--observation', str(obs_dir),
                        '--method', 'H5_F', '--parent-world', str(parent),
                        '--parent-id', f'{tag}_abl', '--out', str(fus),
                        '--pitch', '0.0025', '--config', FUSE_CONFIG,
                        '--ablate-generated-unknown'], cwd=str(ROOT),
                       capture_output=True, text=True)
    ok_ab, why_ab, man_ab = validate_fused(fus, obs_dir, parent, need_ablation=True)
    if not ok_ab:
        _write_error(abl, 'fuse_ablation', r.returncode, r.stdout, r.stderr,
                     {'validation': why_ab})
        return None, {'status': 'ablation_invalid', 'reason': why_ab}
    r = subprocess.run([PY_, 'scripts/collision_box_union.py', '--occupancy',
                        str(fus / 'occ.npz'), '--out', str(coll),
                        '--pitch', '0.0025', '--hypothesis-id', f'{tag}_abl'],
                       cwd=str(ROOT), capture_output=True, text=True)
    z = np_load(fus / 'occ.npz')
    ok2, why2 = validate_collision(coll, str(z['content_sha']),
                                   int(z['occupied'].sum()))
    if not ok2:
        _write_error(abl, 'collision_ablation', r.returncode, r.stdout, r.stderr,
                     {'validation': why2})
        return None, {'status': 'ablation_collision_invalid', 'reason': why2}
    return str(coll.relative_to(ROOT)), {'status': 'built', 'fused': man_ab}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rock', required=True)
    ap.add_argument('--state', default='S1')
    ap.add_argument('--obs', required=True)
    ap.add_argument('--cands', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--soils', default='points',
                    choices=('current', 'points', 'ablation'),
                    help='points=冻结 5 点规划集（主表）；current=nominal 单点诊断；ablation=三档敏感性')
    ap.add_argument('--no-fuse', action='store_true',
                    help='不做观测融合，直接用原始 GLB 世界网格作为几何')
    ap.add_argument('--ablate', action='store_true',
                    help='生成贡献消融：同一候选只删未知区父先验')
    ap.add_argument('--ablate-first-only', action='store_true',
                    help='只给首候选做消融（多候选消融另跑；用于 20 状态主表提速）')
    ap.add_argument('--force', action='store_true', help='重建配准/融合/碰撞')
    ap.add_argument('--tags', default=None, help='逗号分隔候选名，默认全部')
    ap.add_argument('--jobs', type=int, default=1,
                    help='候选配准/融合/碰撞的并行进程数（规划仍在主进程内顺序执行）')
    a = ap.parse_args()
    st = {s['id']: s for s in json.loads(
        (ROOT / 'plans/rock_initial_states.json').read_text())['states']}[a.state]
    rock = {r['id']: r for r in json.loads(
        (ROOT / 'assets/procedural_rocks/index.json').read_text())['rocks']}[a.rock]
    case = json.loads((ROOT / 'cases/unseen_v1/R02.json').read_text())
    obs_dir = (ROOT / a.obs).resolve()
    vis = json.loads((obs_dir / 'observation.json').read_text())['visible']
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    env = build_env(rock, case, st['seed'], (st['lateral_m'], st['yaw_rad']), 'nominal')
    snap = env.save_state()
    want = set(t.strip() for t in a.tags.split(',')) if a.tags else None
    glbs = sorted((ROOT / a.cands / 'raw').glob('*/results.zip'))
    cands, status, vq = {}, {}, {}

    def process(tag, ext):
        try:
            if a.no_fuse:
                return tag, prep_raw(ext, rock, case, out, tag, vis), {'status': 'raw'}
            return tag, *prep(ext, rock, case, obs_dir, out, tag, vis, force=a.force)
        except Exception as e:
            (out / tag).mkdir(parents=True, exist_ok=True)
            (out / tag / 'prep_error.json').write_text(json.dumps(
                {'stage': 'prep_exception', 'error_class': type(e).__name__,
                 'error': str(e)[:4000]}, ensure_ascii=False, indent=2))
            return tag, None, {'status': 'prep_exception',
                               'reason': f'{type(e).__name__}: {e}'[:400]}

    tasks = []
    for z in glbs:
        tag = z.parent.name
        if want and tag not in want:
            continue
        ext = z.parent / 'mesh' / 'tex_mesh.glb'
        if not ext.is_file() and z.is_file():
            with zipfile.ZipFile(z) as f:
                f.extractall(z.parent)
        if not ext.is_file():
            status[tag] = {'status': 'mesh_missing'}
            continue
        tasks.append((tag, ext))
    if a.jobs > 1 and len(tasks) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=int(a.jobs)) as ex:
            futs = [ex.submit(process, t, e) for t, e in tasks]
            results = [f.result() for f in as_completed(futs)]
    else:
        results = [process(t, e) for t, e in tasks]
    for tag, asset, stt in results:
        status[tag] = stt
        if asset:
            cands[tag] = asset
        if a.no_fuse:
            vq[tag] = {'raw_world': asset}
            continue
        fman = stt.get('fused') or {}
        fm = fman.get('metrics') or {}
        fr = fman.get('retention') or {}
        al = out / tag / 'align_used.json'
        aj = json.loads(al.read_text()) if al.is_file() else {}
        nv = aj.get('native') or {}
        vq[tag] = {'align_mask_iou': nv.get('mask_iou'),
                   'align_vis_p95_mm': nv.get('vis_pt_p95_mm'),
                   'align_pass': aj.get('pass'),
                   'fused_strict_pass': (fman.get('strict') or {}).get('pass'),
                   'fused_mask_iou': fm.get('mask_iou'),
                   'fused_vis_p95_mm': fm.get('vis_pt_p95_mm'),
                   'fused_freespace': fm.get('freespace_violation'),
                   'kept_ratio': fr.get('kept_ratio'),
                   'kept_voxels': fr.get('kept_voxels'),
                   'shell_voxels': (fman.get('growth') or {}).get('shell_voxels')}
    res = {'schema': 'v2-multi/v4', 'rock': a.rock, 'state': a.state,
           'candidates': cands, 'candidate_status': status, 'visible_quality': vq,
           'planning_soils': (list(SOILS_POINTS) if a.soils == 'points'
                              else (list(SOILS_CURRENT) if a.soils == 'current'
                                    else list(SOILS_ABLATION))),
           'soil_label': ({'points': 'frozen_five_point', 'current': 'current',
                           'ablation': 'three_level_ablation'}[a.soils]),
           'state_hash': snap.get('state_hash'), 'visible': vis, 'rows': {}}

    def run(tags, tag, cand_map):
        assets = {t: cand_map[t] for t in tags if cand_map.get(t)}
        if not assets:
            return None
        hyps = [{'id': t, 'kind': 'lux3d', 'collision_dir': assets[t]} for t in assets]
        raw = a.no_fuse

        def builder(h, soil):
            v = assets[h['id']]
            objs = ([{'mesh_file': str(ROOT / v), 'x': 0.0, 'y': 0.0, 'yaw_deg': 0.0}]
                    if raw else
                    [{'posed_dir': str(ROOT / CA.resolve(v)['collision_dir'])}])
            return build_env(rock, case, st['seed'],
                             (st['lateral_m'], st['yaw_rad']), soil, objects=objs)

        soils = (list(SOILS_POINTS) if a.soils == 'points'
                 else (list(SOILS_CURRENT) if a.soils == 'current'
                       else list(SOILS_ABLATION)))
        p = CP.plan_action(hyps, snap, vis, soils, 30.0, builder,
                           goal_x=case['goal_x'], seed=st['seed'])
        dd = out / tag
        dd.mkdir(exist_ok=True)
        CP.write_plan(p, dd)
        act = p['decision']['chosen']
        e2 = build_env(rock, case, st['seed'], (st['lateral_m'], st['yaw_rad']), 'nominal')
        e2.restore_state(snap, mode='same_scene')
        r = runner.EpisodeRunner(e2, skills.make_skill(act), visible=vis,
                                 seed=st['seed']).run_current()
        return {'chosen': act, 'cells': p['counts']['rows'], 'n_candidates': len(assets),
                'safe_set': p['decision'].get('safe_set'),
                'success': bool(r.get('success')), 'reason': r.get('reason'),
                'errors': p['decision'].get('rehearsal_errors')}

    first = 'A1' if 'A1' in cands else (sorted(cands)[0] if cands else None)
    if first:
        res['rows']['first'] = run([first], 'first', cands)
    res['rows']['multi'] = run(sorted(cands), 'multi', cands)
    if a.ablate:
        abl, abl_status = {}, {}
        abl_tags = ([first] if (a.ablate_first_only and first) else sorted(cands))
        for tag in abl_tags:
            asset, stt = prep_ablation(out, tag, obs_dir, force=a.force)
            abl_status[tag] = stt
            if asset:
                abl[tag] = asset
        res['ablation_candidates'] = abl
        res['ablation_status'] = abl_status
        if first and abl.get(first):
            res['rows']['first_ablation'] = run([first], 'first_ablation', abl)
        if not a.ablate_first_only:
            res['rows']['multi_ablation'] = run(sorted(abl), 'multi_ablation', abl)
    for k, row in res['rows'].items():
        if row:
            row['planning_usable'] = bool(row.get('safe_set'))
    (out / 'multi.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in res['rows'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
