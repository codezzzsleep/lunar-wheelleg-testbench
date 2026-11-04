"""Stage009：外部追溯清单（不重写轨迹；事后关联明确标注，缺失字段保留 null）。"""
import json, hashlib, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
FV = ROOT / 'runs/v3/stage008/formal_v2'
TRUTH = json.loads((ROOT / 'runs/v3/stage008/truth_v2/truth_manifest.json').read_text())
FUS = json.loads((ROOT / 'runs/v3/stage008/fusion_v2/fusion_summary.json').read_text())


def sha(p):
    h = hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()


def cell(tag, action, arm):
    d = FV / tag / action
    idx = d / 'index.json'; sh = d / 'index.sha256'
    idx_sha = sh.read_text().strip() if sh.exists() else (sha(idx) if idx.exists() else None)
    dec = json.loads((FV / f'decision_{arm}.json').read_text())
    rec = {'action': action, 'arm': arm, 'trajectory_index_sha256': idx_sha,
           'decision_sha': dec['decision_sha'], 'truth_occ_sha256': TRUTH['truth_occ_sha256'],
           's0_state_hash': TRUTH['s0_state_hash'],
           'plan_id': (FUS['plans']['full']['plan_id'] if arm == 'FULL' else FUS['plans']['obs']['plan_id']),
           'post_hoc_links': True,
           'missing_fields': ['trajectory_meta.truth_sha256', 'trajectory_meta.decision_sha']}
    return rec


def main():
    out = {'schema': 'stage9-traceability/v1',
           'note': 'links were assembled after the runs; trajectory files were not rewritten',
           'truth': {'occ_sha256': TRUTH['truth_occ_sha256'], 's0_state_hash': TRUTH['s0_state_hash']},
           'cells': []}
    for t in ['4632564','4632603','4632618','4632621','4632624','4632627']:
        for a in ['R1','R2','D1','D2','L1','L2','BODY_CLEARANCE','A0']:
            if (FV / f'record_full_{t}' / a / 'index.json').exists():
                out['cells'].append(cell(f'record_full_{t}', a, 'FULL'))
    for a in ['R1','R2','D1','D2','L1','L2','BODY_CLEARANCE','A0']:
        if (FV / 'record_obs' / a / 'index.json').exists():
            out['cells'].append(cell('record_obs', a, 'OBS'))
    for arm, tag in (('FULL', 'exec_full/record/TRUTH_FULL'), ('OBS', 'exec_obs/record/TRUTH_OBS')):
        d = FV / tag; idx = d / 'index.json'
        if idx.exists():
            out[f'exec_{arm}'] = {'trajectory_index_sha256': sha(idx),
                                  'truth_occ_sha256': TRUTH['truth_occ_sha256'],
                                  's0_state_hash': TRUTH['s0_state_hash'],
                                  'decision_sha': json.loads((FV / f'decision_{arm}.json').read_text())['decision_sha'],
                                  'post_hoc_links': True,
                                  'missing_fields': ['trajectory_meta.truth_sha256']}
    (ROOT / 'runs/v3/stage008/traceability.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'cells': len(out['cells']), 'exec': [k for k in out if k.startswith('exec_')]}))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
