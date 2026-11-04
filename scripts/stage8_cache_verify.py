"""Stage009：用已有矩阵验证“首次聚合 == 缓存聚合”，并验证身份不匹配会拒绝。"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core, stage8_cache as C

FV = ROOT / 'runs/v3/stage008/formal_v2'
FUS = ROOT / 'runs/v3/stage008/fusion_v2/fusion_summary.json'
TASKS = ['4632564','4632603','4632618','4632621','4632624','4632627']
OPTS = ['R1','R2','D1','D2','L1','L2','CLIMB','BODY_CLEARANCE','A0']


def main():
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    fus = json.loads(FUS.read_text())
    truth = json.loads((ROOT / 'runs/v3/stage008/truth_v2/truth_manifest.json').read_text())
    s0 = truth['s0_state_hash']; psha = C.protocol_sha(root=ROOT)
    applic = {a: True for a in OPTS}; applic['CLIMB'] = False
    out = {}
    # FULL：逐候选一个缓存，几何 sha 各不同
    rows_all = []
    first_dec = None
    for t in TASKS:
        rows = [json.loads(l) for l in open(FV / 'pack_matrices' / f'matrix_full_{t}.jsonl')]
        rows_all += rows
        ident = C.make_identity(s0_hash=s0, scene_sha=fus['candidates'][t]['full_sha'],
                                plan_id=fus['plans']['full']['plan_id'], actions=OPTS,
                                applic=applic, protocol=psha)
        C.write_cache(FV / 'cache' / f'full_{t}.jsonl', ident, rows)
    geom = {t: fus['candidates'][t]['full_sha'] for t in TASKS}
    first = v3_core.aggregate(rows_all, TASKS, geom, 'majority', proto, threshold_mode='majority',
                              applic={a: (applic[a], None) for a in OPTS}, options=OPTS)
    cached_rows = []; cached_app = None
    for t in TASKS:
        ident = C.make_identity(s0_hash=s0, scene_sha=geom[t], plan_id=fus['plans']['full']['plan_id'],
                                actions=OPTS, applic=applic, protocol=psha)
        rows, app = C.read_cache(FV / 'cache' / f'full_{t}.jsonl', ident)
        cached_rows += rows; cached_app = app
    second = v3_core.aggregate(cached_rows, TASKS, geom, 'majority', proto, threshold_mode='majority',
                               applic={a: (cached_app[a], None) for a in OPTS}, options=OPTS)
    mismatch = None
    try:
        bad = dict(C.make_identity(s0_hash=s0, scene_sha=geom[TASKS[0]], plan_id='WRONG',
                                   actions=OPTS, applic=applic, protocol=psha))
        C.read_cache(FV / 'cache' / f'full_{TASKS[0]}.jsonl', bad)
    except C.CacheMismatch as e:
        mismatch = str(e)
    out['FULL'] = {'first': {'chosen': first['chosen'], 'votes': first['votes'], 'costs': first['mean_cost_s']},
                   'cached': {'chosen': second['chosen'], 'votes': second['votes'], 'costs': second['mean_cost_s']},
                   'equal': (first['chosen'] == second['chosen'] and first['votes'] == second['votes']),
                   'mismatch_refused': mismatch is not None, 'mismatch_msg': mismatch}
    # OBS：单缓存
    rows_obs = [json.loads(l) for l in open(FV / 'pack_matrices' / 'matrix_OBS.jsonl')]
    vsha = truth['v_sha']
    ident_o = C.make_identity(s0_hash=s0, scene_sha=vsha, plan_id=fus['plans']['obs']['plan_id'],
                              actions=OPTS, applic=applic, protocol=psha)
    C.write_cache(FV / 'cache' / 'obs.jsonl', ident_o, rows_obs)
    obs_first = v3_core.aggregate(rows_obs, ['OBS'], {}, 'majority', proto, threshold_mode='majority',
                                  applic={a: (applic[a], None) for a in OPTS}, options=OPTS)
    rows2, app2 = C.read_cache(FV / 'cache' / 'obs.jsonl', ident_o)
    obs_second = v3_core.aggregate(rows2, ['OBS'], {}, 'majority', proto, threshold_mode='majority',
                                   applic={a: (app2[a], None) for a in OPTS}, options=OPTS)
    out['OBS'] = {'first': {'chosen': obs_first['chosen'], 'votes': obs_first['votes']},
                  'cached': {'chosen': obs_second['chosen'], 'votes': obs_second['votes']},
                  'equal': (obs_first['chosen'] == obs_second['chosen'] and obs_first['votes'] == obs_second['votes'])}
    out['protocol_sha256'] = psha; out['s0_state_hash'] = s0
    out['note'] = 'no physics rerun; the same existing matrices were re-aggregated from cache'
    (FV / 'cache_verification.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'FULL_equal': out['FULL']['equal'], 'chosen': first['chosen'],
                      'votes': first['votes'], 'mismatch_refused': mismatch is not None,
                      'OBS_equal': out['OBS']['equal'], 'obs_votes': obs_first['votes']},
                     ensure_ascii=False))
    return 0 if (out['FULL']['equal'] and out['OBS']['equal'] and mismatch) else 1


if __name__ == '__main__':
    sys.exit(main())
