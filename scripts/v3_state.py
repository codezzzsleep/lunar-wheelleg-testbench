"""单个状态的全链：候选配准 → 融合 → 碰撞 → FULL/OBS_ONLY 决策 → 真值执行。

  python scripts/v3_state.py --state runs/v3/states/<sid> --protocol plans/v3_protocol.json
  python scripts/v3_state.py --state ... --stage register|fuse|collision|decide|execute|all
  python scripts/v3_state.py --states all --workers 4      # 批量（每进程一个状态）
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

import trimesh

import v3_core
import v3_fuse
import v3_generate
import v3_register

ROOT = pathlib.Path(__file__).resolve().parent.parent
VARIANTS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_tasks(tasks_path):
    p = ROOT / tasks_path
    if not p.is_file():
        return []
    return json.loads(p.read_text())['tasks']


def candidate_glb(task):
    ident = v3_generate.identity_of(task)
    hit = v3_generate.cache_valid(ident)
    return (hit['glb'] if hit else None), ident


def stage_register(state_dir, proto, tasks):
    st = json.loads((state_dir / 'state.json').read_text())
    sid = st['state_id']
    obs = state_dir / 'observation'
    done = []
    for t in tasks:
        if t.get('state_id') != sid:
            continue
        cid = t['variant']
        glb, ident = candidate_glb(t)
        out = state_dir / 'candidates' / cid
        rec = {'candidate_id': cid, 'task_id': None, 'identity': ident,
               'state_id': sid, 'variant': cid, 'repeat_idx': t.get('repeat_idx', 0),
               'input_shas': [t['image_sha256']],
               'provider_version': t['model'].get('version'),
               'raw_sha': None, 'artifact_status': 'pending'}
        if glb is None:
            rec['artifact_status'] = 'missing_generation'
            out.mkdir(parents=True, exist_ok=True)
            (out / 'candidate.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
            continue
        rec['raw_sha'] = sha256_file(glb)
        if (out / 'align.json').is_file() and (out / 'candidate.json').is_file():
            old = json.loads((out / 'candidate.json').read_text())
            if old.get('raw_sha') == rec['raw_sha'] and old.get('artifact_status') == 'complete':
                done.append(cid)
                continue
        out.mkdir(parents=True, exist_ok=True)
        try:
            reg = v3_register.register(glb, obs, proto, out)
        except Exception as e:  # noqa: BLE001
            rec['artifact_status'] = 'registration_error'
            rec['error'] = f'{type(e).__name__}: {e}'[:400]
            (out / 'candidate.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
            continue
        M = np.asarray(reg['M'], float)
        mesh = v3_register.load_mesh(glb)
        mesh.apply_transform(M)
        pw = out / 'parent_world'
        pw.mkdir(parents=True, exist_ok=True)
        mesh.export(pw / 'body.stl')
        (pw / 'manifest.json').write_text(json.dumps({
            'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
            'parts': ['body.stl'], 'world_sha': sha256_file(pw / 'body.stl'),
            'T_world_from_asset': M.tolist(),
        }, ensure_ascii=False, indent=2))
        rec.update({'artifact_status': 'complete',
                    'registration_matrix': M.tolist(),
                    'registration_diagnostics': reg['diagnostics'],
                    'obs_sha': sha256_file(obs / 'observation.json'),
                    'parent_sha': sha256_file(pw / 'body.stl'),
                    'n_refined': reg.get('n_refined')})
        (out / 'candidate.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        done.append(cid)
    return done


def stage_fuse(state_dir, proto, tasks):
    st = json.loads((state_dir / 'state.json').read_text())
    sid = st['state_id']
    art = v3_fuse.write_v_artifact(state_dir, proto)
    rows = []
    for t in tasks:
        if t.get('state_id') != sid:
            continue
        cid = t['variant']
        out = state_dir / 'candidates' / cid
        cand = json.loads((out / 'candidate.json').read_text()) if (out / 'candidate.json').is_file() else {}
        if cand.get('artifact_status') != 'complete':
            rows.append({'candidate': cid, 'status': 'skipped_no_registration'})
            continue
        try:
            pm = trimesh.load(out / 'parent_world' / 'body.stl', force='mesh', process=False)
            t0 = time.time()
            man, stats = v3_fuse.fuse_parent(
                art, pm, out / 'fused', {'id': cid, 'mesh_sha256': cand['parent_sha']},
                proto, with_mesh=False)
            man['seconds'] = round(time.time() - t0, 2)
            (out / 'fused' / 'manifest.json').write_text(
                json.dumps(man, ensure_ascii=False, indent=2))
            cand.update({'fusion_version': man['version'],
                         'V_sha': man['v_sha'], 'U_sha': man['space_sha'],
                         'generated_unknown_count': stats['n_generated_unknown'],
                         'kept_ratio': stats['kept_ratio_of_generated'],
                         'full_occ_sha': man['full_occ_sha'],
                         'obs_only_occ_sha': man['obs_only_occ_sha'],
                         'observation_compatible': bool(stats['free_violations_full'] == 0)})
            (out / 'candidate.json').write_text(json.dumps(cand, ensure_ascii=False, indent=2))
            rows.append({'candidate': cid, 'status': 'complete',
                         'full_occ_sha': man['full_occ_sha'],
                         'n_generated': stats['n_generated_unknown'],
                         'seconds': man['seconds']})
        except Exception as e:  # noqa: BLE001
            cand['artifact_status'] = 'fusion_error'
            cand['error'] = f'{type(e).__name__}: {e}'[:400]
            (out / 'candidate.json').write_text(json.dumps(cand, ensure_ascii=False, indent=2))
            rows.append({'candidate': cid, 'status': 'error', 'error': cand['error']})
    return rows


def stage_collision(state_dir, proto, tasks):
    st = json.loads((state_dir / 'state.json').read_text())
    sid = st['state_id']
    rows = []
    obs_only_built = False
    for t in tasks:
        if t.get('state_id') != sid:
            continue
        cid = t['variant']
        out = state_dir / 'candidates' / cid
        man_p = out / 'fused' / 'manifest.json'
        if not man_p.is_file():
            continue
        try:
            man = json.loads(man_p.read_text())
            r = v3_core.build_collision(out / 'fused' / 'occ_full.npz', out / 'coll',
                                        pitch=proto['collision']['pitch_m'],
                                        downsample=int(proto['collision'].get('box_downsample', 1)))
            rows.append({'candidate': cid, 'kind': 'FULL', 'ok': r['ok'],
                         'n_boxes': r.get('n_boxes')})
            if not obs_only_built:
                r2 = v3_core.build_collision(out / 'fused' / 'occ_obs_only.npz',
                                             state_dir / 'obs_only' / 'coll',
                                             pitch=proto['collision']['pitch_m'],
                                             downsample=int(proto['collision'].get('box_downsample', 1)))
                rows.append({'candidate': cid, 'kind': 'OBS_ONLY', 'ok': r2['ok'],
                             'n_boxes': r2.get('n_boxes')})
                obs_only_built = True
            cand = json.loads((out / 'candidate.json').read_text())
            cand['collision_sha'] = r.get('collision_sha')
            cand['collision_boxes'] = r.get('n_boxes')
            (out / 'candidate.json').write_text(json.dumps(cand, ensure_ascii=False, indent=2))
        except Exception as e:  # noqa: BLE001
            rows.append({'candidate': cid, 'ok': False, 'error': f'{type(e).__name__}: {e}'[:300]})
    return rows


def _geom_map(state_dir, tasks, kind):
    st = json.loads((state_dir / 'state.json').read_text())
    sid = st['state_id']
    geom = {}
    for t in tasks:
        if t.get('state_id') != sid:
            continue
        cid = t['variant']
        out = state_dir / 'candidates' / cid
        if kind == 'FULL':
            if (out / 'coll' / 'manifest.json').is_file():
                geom[cid] = str(out / 'coll')
        else:
            p = state_dir / 'obs_only' / 'coll'
            if (p / 'manifest.json').is_file():
                geom[cid] = str(p)
    return geom


def _geom_identity(state_dir, geom, kind, tasks):
    """实际几何内容 ID（用于候选去重）：碰撞清单里的源占据 SHA，并与融合产物核对。

    不能只看 manifest 存在：源 SHA 与 fused/occ_*.npz 不一致就拒绝该几何（返回 None），
    由调用方记录 pipeline_failure，而不是拿旧碰撞件预演。
    """
    ids, bad = {}, []
    for cid, coll_dir in geom.items():
        man = json.loads((pathlib.Path(coll_dir) / 'manifest.json').read_text())
        src = (man.get('source') or {}).get('occ_sha256')
        if kind == 'FULL':
            occ_p = state_dir / 'candidates' / cid / 'fused' / 'occ_full.npz'
        else:
            occ_p = state_dir / 'candidates' / next(iter(
                [t['variant'] for t in tasks if t.get('state_id') == state_dir.name])) \
                / 'fused' / 'occ_obs_only.npz'
        cur = None
        if occ_p.is_file():
            import numpy as _np
            cur = hashlib.sha256(_np.ascontiguousarray(
                _np.load(occ_p)['occupied']).tobytes()).hexdigest()
        if src and cur and src == cur:
            ids[cid] = src
        else:
            bad.append({'candidate': cid, 'kind': kind,
                        'reason': 'collision_source_mismatch',
                        'coll_source': src, 'current': cur})
    return ids, bad


def stage_decide(state_dir, proto, tasks):
    st = v3_core.load_state(state_dir)
    out = state_dir / 'decision'
    res = {}
    geom_full = _geom_map(state_dir, tasks, 'FULL')
    if geom_full:
        ids_full, bad_full = _geom_identity(state_dir, geom_full, 'FULL', tasks)
        rows, applic = v3_core.rehearse(st, geom_full, st['snapshot'], proto)
        dec = v3_core.aggregate(rows, list(geom_full), ids_full, 'majority', proto,
                                threshold_mode='majority',
                                applic={k: tuple(v) for k, v in applic.items()})
        v3_core.write_decision(out, st, 'FULL', rows, dec,
                               extra={'applicability': {k: list(v) for k, v in applic.items()},
                                      'geometry': geom_full,
                                      'geometry_ids': ids_full,
                                      'rejected_geometry': bad_full})
        res['FULL'] = {'chosen': dec['chosen'], 'votes': dec['votes'],
                       'n_valid': dec['n_valid'], 'reason': dec['reason']}
    geom_obs = _geom_map(state_dir, tasks, 'OBS_ONLY')
    if geom_obs:
        ids_obs, bad_obs = _geom_identity(state_dir, geom_obs, 'OBS_ONLY', tasks)
        first = next(iter(geom_obs))
        rows1, applic = v3_core.rehearse(st, {first: geom_obs[first]}, st['snapshot'], proto)
        rows = []
        for cid in geom_obs:
            for r in rows1:
                rr = dict(r); rr['candidate'] = cid; rows.append(rr)
        dec = v3_core.aggregate(rows, list(geom_obs), ids_obs, 'majority', proto,
                                threshold_mode='majority',
                                applic={k: tuple(v) for k, v in applic.items()})
        v3_core.write_decision(out, st, 'OBS_ONLY', rows, dec,
                               extra={'applicability': {k: list(v) for k, v in applic.items()},
                                      'geometry': geom_obs,
                                      'geometry_ids': ids_obs,
                                      'rejected_geometry': bad_obs,
                                      'note': 'OBS_ONLY 的六个候选几何完全相同，预演只算一次，'
                                              '按候选 ID 复制票映射（不伪称多次独立试验）'})
        res['OBS_ONLY'] = {'chosen': dec['chosen'], 'votes': dec['votes'],
                           'n_valid': dec['n_valid'], 'reason': dec['reason']}
    return res


def stage_execute(state_dir, proto, tasks):
    st = v3_core.load_state(state_dir)
    out = state_dir / 'decision'
    res = {}
    for arm in ('FULL', 'OBS_ONLY'):
        p = out / f'decision_{arm}.json'
        if not p.is_file():
            continue
        dec = json.loads(p.read_text())
        action = dec['decision']['chosen']
        r = v3_core.truth_execute(st, action, proto, out, arm)
        res[arm] = {'action': action, 'outcome': r.get('outcome'), 'reason': r.get('reason'),
                    'final_x': r.get('final_x'), 't_end': r.get('t_end'),
                    'wall_s': r.get('wall_s')}
    return res


def process_state(state_dir, proto, tasks, stages):
    state_dir = pathlib.Path(state_dir)
    out = {'state_id': state_dir.name}
    if 'register' in stages:
        out['register'] = stage_register(state_dir, proto, tasks)
    if 'fuse' in stages:
        out['fuse'] = stage_fuse(state_dir, proto, tasks)
    if 'collision' in stages:
        out['collision'] = stage_collision(state_dir, proto, tasks)
    if 'decide' in stages:
        out['decide'] = stage_decide(state_dir, proto, tasks)
    if 'execute' in stages:
        out['execute'] = stage_execute(state_dir, proto, tasks)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default=None)
    ap.add_argument('--states', default=None)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--tasks', default='runs/v3/generation/tasks.json')
    ap.add_argument('--stage', default='all')
    ap.add_argument('--workers', type=int, default=1)
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    tasks = load_tasks(a.tasks)
    stages = ['register', 'fuse', 'collision', 'decide', 'execute'] if a.stage == 'all' \
        else [a.stage]
    if a.state:
        r = process_state(ROOT / a.state, proto, tasks, stages)
        print(json.dumps(r, ensure_ascii=False))
        return
    if a.states != 'all':
        raise SystemExit('需要 --state 或 --states all')
    dirs = [p.parent for p in sorted((ROOT / 'runs/v3/states').glob('*/state.json'))]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = [ex.submit(process_state, d, proto, tasks, stages) for d in dirs]
        for f in futs:
            try:
                print(json.dumps(f.result(), ensure_ascii=False), flush=True)
            except Exception as e:  # noqa: BLE001
                print(json.dumps({'error': f'{type(e).__name__}: {e}'}, ensure_ascii=False),
                      flush=True)


if __name__ == '__main__':
    main()
