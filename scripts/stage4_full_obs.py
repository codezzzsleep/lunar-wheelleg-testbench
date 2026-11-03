"""Stage004：FULL = V∪(P∩U) 与 OBS_ONLY = V 的同条件决策与真值执行。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/stage4_full_obs.py \
      --state runs/v3/states/moon_rock_04_h1v0 --out runs/v3/stage004/e2e_04_h1v0
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import hashlib  # noqa: E402
import numpy as np  # noqa: E402
import v3_core  # noqa: E402
import stage4_perturb as S4P  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--pitch', type=float, default=0.0,
                    help='0 表示用 protocol 的 collision.pitch_m（2 mm）')
    ap.add_argument('--max-candidates', type=int, default=6)
    ap.add_argument('--perturb', default='', help='dx,dy,dyaw_deg 冻结初态扰动')
    a = ap.parse_args()
    state_dir = (ROOT / a.state).resolve()
    out = (ROOT / a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((ROOT / a.protocol).read_text())
    if not a.pitch:
        a.pitch = float(proto['collision']['pitch_m'])
    core = v3_core.load_state(state_dir)
    dx = dy = dyaw = 0.0
    if a.perturb:
        parts = [float(x) for x in a.perturb.split(',')]
        while len(parts) < 3:
            parts.append(0.0)
        dx, dy, dyaw = parts[:3]
    perturb_diag = None
    if dx or dy or dyaw:
        snap_new, perturb_diag = S4P.env_perturb_snapshot(core, proto, dx, dy, dyaw)
        core['snapshot'] = snap_new
        core['state']['state_hash'] = snap_new.get('state_hash')
    import numpy as _np
    _env0 = v3_core.make_env(core['spec'], proto)
    _env0.restore_state(core['snapshot'], mode='same_scene')
    _q = _np.asarray(_env0.data.qpos, dtype=float).copy()
    init_qpos_sha = hashlib.sha256(_q.tobytes()).hexdigest()
    init_state_hash = core['snapshot'].get('state_hash')
    init_clock_s = round(float(_env0.t), 4)
    # 候选：fused 完整
    cands = []
    for d in sorted((state_dir / 'candidates').iterdir()):
        fm = d / 'fused' / 'manifest.json'
        if fm.is_file() and json.loads(fm.read_text()).get('artifact_status') == 'complete':
            cands.append(d)
    cands = cands[:a.max_candidates]
    if not cands:
        raise SystemExit('no complete fused candidates')
    cand_ids, geom_sha, full_coll = [], {}, {}
    for d in cands:
        fm = json.loads((d / 'fused' / 'manifest.json').read_text())
        occ = d / 'fused' / 'occ_full.npz'
        cd = out / 'coll_full' / d.name
        r = v3_core.build_collision(occ, cd, pitch=a.pitch,
                                    downsample=int(proto['collision'].get('box_downsample', 1)))
        if not r.get('ok'):
            raise SystemExit(f'collision failed for {d.name}: {r.get("error")}')
        cand_ids.append(d.name)
        geom_sha[d.name] = fm['full_occ_sha']
        full_coll[d.name] = str(cd)
    # OBS_ONLY：共享 V
    # OBS_ONLY 用候选共享的 V（与 FULL 同一数组），而不是状态级旧文件
    obs_occ = cands[0] / 'fused' / 'occ_obs_only.npz'
    vsha = json.loads((cands[0] / 'fused' / 'manifest.json').read_text())['v_sha']
    z = np.load(obs_occ)
    if str(z['content_sha']) != vsha:
        raise SystemExit(f'V sha mismatch: {z["content_sha"]} vs {vsha}')
    obs_cd = out / 'coll_obs'
    r = v3_core.build_collision(obs_occ, obs_cd, pitch=a.pitch,
                                downsample=int(proto['collision'].get('box_downsample', 1)))
    if not r.get('ok'):
        raise SystemExit(f'collision failed for V: {r.get("error")}')
    snap = core['snapshot']
    # FULL：逐候选预演（≥50Hz 记录）
    rows_f, app_f = v3_core.rehearse(core, full_coll, snap, proto, record_cells=True,
                                     record_root=out / 'record_full')
    dec_f = v3_core.aggregate(rows_f, cand_ids, geom_sha, 'majority', proto,
                              threshold_mode='majority', applic=app_f)
    v3_core.write_decision(out, core, 'FULL', rows_f, dec_f,
                           {'candidates': cand_ids, 'full_occ_sha': geom_sha})
    # OBS_ONLY
    rows_o, app_o = v3_core.rehearse(core, {'OBS': str(obs_cd)}, snap, proto,
                                     record_cells=True, record_root=out / 'record_obs')
    dec_o = v3_core.aggregate(rows_o, ['OBS'], {}, 'majority', proto,
                              threshold_mode='majority', applic=app_o)
    v3_core.write_decision(out, core, 'OBS', rows_o, dec_o, {'candidates': ['OBS']})
    # 决策落盘后再真值执行
    ex_f = v3_core.truth_execute(core, dec_f['chosen'], proto, out / 'truth_exec', 'FULL')
    ex_o = v3_core.truth_execute(core, dec_o['chosen'], proto, out / 'truth_exec', 'OBS')
    res = {'schema': 'stage4-full-obs/v1', 'state_id': core['state']['state_id'],
           'formula': 'FULL = V | (P & U); OBS_ONLY = V',
           'perturb': {'dx': dx, 'dy': dy, 'dyaw_deg': dyaw},
           'init_qpos_sha256': init_qpos_sha,
           'init_state_hash': init_state_hash,
           'init_clock_s': init_clock_s,
           'perturb_diag': perturb_diag,
           'candidates': cand_ids,
           'FULL': {'chosen': dec_f['chosen'], 'votes': dec_f['votes'],
                    'costs': dec_f['mean_cost_s'], 'reason': dec_f['reason'],
                    'threshold': dec_f['threshold'], 'n_unique': dec_f['n_unique_geometries'],
                    'exec': ex_f},
           'OBS': {'chosen': dec_o['chosen'], 'votes': dec_o['votes'],
                   'costs': dec_o['mean_cost_s'], 'reason': dec_o['reason'],
                   'exec': ex_o},
           'decision_differs': dec_f['chosen'] != dec_o['chosen'],
           'outcome_differs': ex_f.get('outcome') != ex_o.get('outcome'),
           'pipeline_errors': (dec_f.get('errors') or []) + (dec_o.get('errors') or [])}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'FULL': res['FULL']['chosen'], 'OBS': res['OBS']['chosen'],
                      'full_outcome': ex_f.get('outcome'), 'obs_outcome': ex_o.get('outcome'),
                      'diff': [res['decision_differs'], res['outcome_differs']]},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
