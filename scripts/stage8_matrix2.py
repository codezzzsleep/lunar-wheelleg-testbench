"""Stage008 修正：六候选 FULL 矩阵多数聚合 + OBS 单矩阵；决策先落盘；同一真实场景执行。"""
import argparse
import hashlib
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
import stage6_matrix as S6M  # noqa: E402
import stage8_cache as C  # noqa: E402

TASKS = ['4632564', '4632603', '4632618', '4632621', '4632624', '4632627']
PITCH = 0.004
ORIGIN = np.array([0.60, -0.80, 0.0])
DIMS = np.array([200, 400, 105])


def resample_walls(occ, origin, pitch):
    """融合占据 -> 固定 4 mm 场景栅格，并补两侧墙。"""
    scene = np.zeros(tuple(DIMS), bool)
    origin = np.asarray(origin, float); pitch = float(pitch)
    ii, jj, kk = np.nonzero(occ)
    wx = origin[0] + (ii + 0.5) * pitch
    wy = origin[1] + (jj + 0.5) * pitch
    wz = origin[2] + (kk + 0.5) * pitch
    ci = np.floor((wx - ORIGIN[0]) / PITCH).astype(int)
    cj = np.floor((wy - ORIGIN[1]) / PITCH).astype(int)
    ck = np.floor((wz - ORIGIN[2]) / PITCH).astype(int)
    ok = ((ci >= 0) & (ci < DIMS[0]) & (cj >= 0) & (cj < DIMS[1]) & (ck >= 0) & (ck < DIMS[2]))
    scene[ci[ok], cj[ok], ck[ok]] = True
    for y in (-0.55, 0.55):
        i0 = max(0, int((0.75 - ORIGIN[0]) / PITCH)); i1 = min(DIMS[0], int((1.25 - ORIGIN[0]) / PITCH))
        j0 = max(0, int((y - 0.25 - ORIGIN[1]) / PITCH)); j1 = min(DIMS[1], int((y + 0.25 - ORIGIN[1]) / PITCH))
        k1 = min(DIMS[2], int(0.32 / PITCH))
        scene[i0:i1, j0:j1, :k1] = True
    return scene


def rows_cache(path):
    return pathlib.Path(path)


def load_rows(path):
    """旧的无身份缓存：只用于探测，不再作为可复用输入。"""
    if not pathlib.Path(path).exists():
        return None
    return [json.loads(l) for l in open(path)]


def save_rows(path, rows):
    with open(path, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def make_scene(occ, out, tag, budget=120.0):
    grid = out / f'occ_{tag}.npz'
    sha = hashlib.sha256(np.ascontiguousarray(occ).tobytes()).hexdigest()[:32]
    np.savez_compressed(grid, occupied=occ, origin=ORIGIN, pitch=np.float64(PITCH),
                        dims=DIMS, content_sha=np.array(sha),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    coll = out / f'coll_{tag}'
    r = v3_core.build_collision(grid, coll, pitch=PITCH, downsample=1)
    if not r.get('ok'):
        raise SystemExit(f'collision {tag}: {r.get("error")}')
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=2.6, objects=[{'posed_dir': str(coll)}],
                             name=f'stage8_{tag}')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=budget); env.reset(seed=0)
    return spec, env, sha


def restore_common(env, snap, s0_hash, mode='project', ref=None):
    env.restore_state(snap, mode=mode)
    cur = env.save_state()
    if mode == 'same_scene':
        got = cur.get('state_hash')
        if got != s0_hash:
            raise SystemExit(f'S0 hash mismatch after same_scene restore: {got} != {s0_hash}')
        return got
    # project：跨几何恢复不要求整包 state_hash 相同（warmstart 等模型量会变）；
    # 核对运动学内容与真值场景恢复出的 S0 完全一致。
    if ref is not None:
        rq, rv = ref
        cq = np.asarray(env.data.qpos, float); cv = np.asarray(env.data.qvel, float)
        if cq.shape != rq.shape or not np.allclose(cq, rq, atol=1e-9, rtol=0):
            raise SystemExit('projected S0 qpos mismatch')
        if cv.shape != rv.shape or not np.allclose(cv, rv, atol=1e-9, rtol=0):
            raise SystemExit('projected S0 qvel mismatch')
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify-only', action='store_true',
                    help='只经本入口读取身份缓存并重聚合，与已有 decision 对比，不重跑物理')
    ap.add_argument('--truth', default='runs/v3/stage008/truth_v2')
    ap.add_argument('--fusion', default='runs/v3/stage008/fusion_v2')
    ap.add_argument('--out', default='runs/v3/stage008/formal_v2')
    a = ap.parse_args()
    truth = (ROOT / a.truth).resolve(); fus = (ROOT / a.fusion).resolve()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / 'configs/stage6_protocol.json').read_text())
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    tm = json.loads((truth / 'truth_manifest.json').read_text())
    snap = json.loads((truth / 'state_snapshot.json').read_text())
    s0 = tm['s0_state_hash']
    art = np.load(truth / 'fusion' / 'V.npz')
    V = art['shell']; v_sha = str(art['v_sha'])
    obs_occ = resample_walls(V, art['origin'], float(art['pitch']))
    truth_spec0 = json.loads((truth / 'scene_spec.json').read_text())
    tenv0 = wheelleg_env.WheelLegEnv(truth_spec0, max_seconds=float(cfg['budget_s'])); tenv0.reset(seed=0)
    restore_common(tenv0, snap, s0, mode='same_scene')
    s0_ref = (np.asarray(tenv0.data.qpos, float).copy(), np.asarray(tenv0.data.qvel, float).copy())
    obs_spec, obs_env, obs_sha = make_scene(obs_occ, out, 'obs')
    restore_common(obs_env, snap, s0, ref=s0_ref)
    fsum = json.loads((fus / 'fusion_summary.json').read_text())
    plans = fsum['plans']
    actions = cfg['actions']
    vis = {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30}
    applic_all = {}
    for act in actions:
        if act in ('CLIMB', 'BODY_CLEARANCE', 'A0'):
            applic_all[act] = True if act != 'CLIMB' else False
        else:
            applic_all[act] = bool(v3_core.ACT.applicable(act, vis, float(proto['scene']['channel_half_m']))[0])
    psha = C.protocol_sha(root=ROOT)
    def app_from(applic):
        return {a: (bool(applic[a]), None) for a in actions}
    obs_core = {'spec': obs_spec, 'snapshot': snap,
                'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
                'state': {'state_id': 'stage8_obs_v2', 'state_hash': s0}}
    ident_obs = C.make_identity(s0_hash=s0, scene_sha=tm['v_sha'],
                                plan_id=plans['obs']['plan_id'], actions=actions,
                                applic=applic_all, protocol=psha)
    cache_obs = out / 'cache' / 'obs.jsonl'
    rows_obs = None; app = None
    if cache_obs.exists() and not a.verify_only:
        rows_obs, applic = C.read_cache(cache_obs, ident_obs)
        app = app_from(applic)
    elif a.verify_only:
        if not cache_obs.exists():
            legacy = (out / 'rows_obs.jsonl').exists()
            print(json.dumps({'refused': 'identity-less legacy cache' if legacy else 'missing identity cache',
                              'arm': 'OBS', 'exit': 2}, ensure_ascii=False))
            return 2
        rows_obs, applic = C.read_cache(cache_obs, ident_obs)
        app = app_from(applic)
    if rows_obs is None:
        if (out / 'rows_obs.jsonl').exists():
            print('refusing identity-less legacy cache rows_obs.jsonl')
        rows_obs, app = v3_core.rehearse_on_spec(obs_core, obs_spec, snap, proto, mode='project',
                                                 options=actions, body_plan=plans['obs'],
                                                 budget=float(cfg['budget_s']),
                                                 record_cells=True, record_root=out / 'record_obs')
        C.write_cache(cache_obs, ident_obs, rows_obs)
    for r in rows_obs:
        tref = r.get('trajectory_ref')
        if tref:
            c = S6M.chassis_contacts_from_record(tref)
            r['chassis_contacts'] = c
            if c > 0 and r.get('success'):
                r['success'] = False; r['outcome'] = 'chassis_contact'; r['reason'] = 'chassis_obstacle_contact'
        r['candidate'] = 'OBS'
    dec_obs = v3_core.aggregate(rows_obs, ['OBS'], {}, 'majority', proto,
                                threshold_mode='majority', applic=app, options=actions)
    drec_obs = v3_core.write_decision(out, obs_core, 'OBS', rows_obs, dec_obs, {'plan': plans['obs']})
    dec_obs['decision_sha'] = drec_obs['decision_sha']
    rows_all = []
    for tid in TASKS:
        d = fus / f'task_{tid}'
        if not (d / 'occ_full.npz').exists():
            continue
        z = np.load(d / 'occ_full.npz')
        occ = resample_walls(z['occupied'], z['origin'], float(z['pitch']))
        spec, env, sha = make_scene(occ, out, f'full_{tid}')
        restore_common(env, snap, s0, ref=s0_ref)
        core = {'spec': spec, 'snapshot': snap,
                'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
                'state': {'state_id': f'stage8_full_{tid}', 'state_hash': s0}}
        ident_i = C.make_identity(s0_hash=s0, scene_sha=fsum['candidates'][tid]['full_sha'],
                                  plan_id=plans['full']['plan_id'], actions=actions,
                                  applic=applic_all, protocol=psha)
        cache_i = out / 'cache' / f'full_{tid}.jsonl'
        rr = None
        if not a.verify_only:
            if cache_i.exists():
                rr, applic_i = C.read_cache(cache_i, ident_i)
                if app is None:
                    app = app_from(applic_i)
            else:
                if (out / f'rows_full_{tid}.jsonl').exists():
                    print(f'refusing identity-less legacy cache rows_full_{tid}.jsonl')
        if rr is None and a.verify_only:
            if not cache_i.exists():
                legacy = (out / f'rows_full_{tid}.jsonl').exists()
                print(json.dumps({'refused': 'identity-less legacy cache' if legacy else 'missing identity cache',
                                  'candidate': tid, 'exit': 2}, ensure_ascii=False))
                return 2
            rr, applic_i = C.read_cache(cache_i, ident_i)
            if app is None:
                app = app_from(applic_i)
        if rr is None:
            rr, _ = v3_core.rehearse_on_spec(core, spec, snap, proto, mode='project',
                                             options=actions, body_plan=plans['full'],
                                             budget=float(cfg['budget_s']),
                                             record_cells=True, record_root=out / f'record_full_{tid}')
            C.write_cache(cache_i, ident_i, rr)
        for r in rr:
            tref = r.get('trajectory_ref')
            if tref:
                c = S6M.chassis_contacts_from_record(tref)
                r['chassis_contacts'] = c
                if c > 0 and r.get('success'):
                    r['success'] = False; r['outcome'] = 'chassis_contact'; r['reason'] = 'chassis_obstacle_contact'
            r['candidate'] = tid
        save_rows(cache_i, rr)
        rows_all += rr
    geom = {t: fsum['candidates'][t]['full_sha'] for t in TASKS if t in fsum['candidates']}
    dec_full = v3_core.aggregate(rows_all, list(geom.keys()), geom, 'majority', proto,
                                 threshold_mode='majority', applic=app, options=actions)
    if a.verify_only:
        prev_full = json.loads((out / 'decision_FULL.json').read_text()) if (out / 'decision_FULL.json').exists() else None
        prev_obs = json.loads((out / 'decision_OBS.json').read_text()) if (out / 'decision_OBS.json').exists() else None
        ok = bool(prev_full and prev_obs
                  and dec_full['chosen'] == prev_full['decision']['chosen']
                  and dec_full['votes'] == prev_full['decision']['votes']
                  and dec_obs['chosen'] == prev_obs['decision']['chosen']
                  and dec_obs['votes'] == prev_obs['decision']['votes'])
        rep = {'schema': 'stage8-cache-entry-verification/v1', 'entry': 'stage8_matrix2.py --verify-only',
               'FULL': {'chosen': dec_full['chosen'], 'votes': dec_full['votes'],
                        'cached_chosen': prev_full['decision']['chosen'] if prev_full else None},
               'OBS': {'chosen': dec_obs['chosen'], 'votes': dec_obs['votes'],
                       'cached_chosen': prev_obs['decision']['chosen'] if prev_obs else None},
               'equal': ok, 'physics_rerun': False}
        (out / 'cache_entry_verification.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(json.dumps(rep, ensure_ascii=False))
        return 0 if ok else 1
    drec_full = v3_core.write_decision(out, {'state': {'state_id': 'stage8_full_aggregate'},
                                             'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30}},
                                       'FULL', rows_all, dec_full, {'plan': plans['full']})
    dec_full['decision_sha'] = drec_full['decision_sha']
    # 同一真实场景执行
    truth_spec = json.loads((truth / 'scene_spec.json').read_text())
    tcore = {'spec': truth_spec, 'snapshot': snap,
             'visible': {'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
             'state': {'state_id': 'stage8_truth_v2', 'state_hash': s0}}
    tenv = wheelleg_env.WheelLegEnv(truth_spec, max_seconds=float(cfg['budget_s'])); tenv.reset(seed=0)
    restored = restore_common(tenv, snap, s0, mode='same_scene')
    ex_full = v3_core.truth_execute(tcore, dec_full['chosen'], proto, out / 'exec_full', 'TRUTH_FULL',
                                    body_plan=plans['full'], budget=float(cfg['budget_s']))
    ex_obs = v3_core.truth_execute(tcore, dec_obs['chosen'], proto, out / 'exec_obs', 'TRUTH_OBS',
                                   body_plan=plans['obs'], budget=float(cfg['budget_s']))
    # OBS 决策确定性：重复一次
    ex_obs2 = v3_core.truth_execute(tcore, dec_obs['chosen'], proto, out / 'exec_obs_repeat', 'TRUTH_OBS',
                                    body_plan=plans['obs'], budget=float(cfg['budget_s']))
    res = {'schema': 'stage8-formal-v2/v1', 'truth': {'occ_sha256': tm['truth_occ_sha256'],
                                                     'v_sha': v_sha, 's0_state_hash': s0,
                                                     'restored_state_hash': restored},
           'plans': plans, 'full': {'votes': dec_full['votes'], 'chosen': dec_full['chosen'],
                                    'decision_sha': dec_full.get('decision_sha'),
                                    'exec': {k: ex_full.get(k) for k in
                                             ('action', 'outcome', 't_end', 'chassis_contacts',
                                              'safe_pass', 'reached', 'plan_id')}},
           'obs': {'votes': dec_obs['votes'], 'chosen': dec_obs['chosen'],
                   'decision_sha': dec_obs.get('decision_sha'),
                   'exec': {k: ex_obs.get(k) for k in
                            ('action', 'outcome', 't_end', 'chassis_contacts',
                             'safe_pass', 'reached', 'plan_id')},
                   'exec_repeat': {k: ex_obs2.get(k) for k in
                                   ('action', 'outcome', 't_end', 'chassis_contacts')}}}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False)[:1500])
    return 0


if __name__ == '__main__':
    sys.exit(main())
