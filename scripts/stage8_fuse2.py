"""Stage008：配准后的父网格 -> FULL=V|(P&U)，并生成固定 BODY 方案（后缘来自首候选）。"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_fuse  # noqa: E402

TASKS = ['4632564', '4632603', '4632618', '4632621', '4632624', '4632627']


def plan_id(p):
    return hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default='runs/v3/stage008/truth_v2')
    ap.add_argument('--registered', default='runs/v3/stage008/registered')
    ap.add_argument('--out', default='runs/v3/stage008/fusion_v2')
    a = ap.parse_args()
    state = (ROOT / a.state).resolve(); reg = (ROOT / a.registered).resolve()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    art = v3_fuse.write_v_artifact(state, proto)
    res = {'schema': 'stage8-fusion-v2/v1', 'truth': a.state, 'v_sha': art['v_sha'],
           'v_stats': art['stats'], 'candidates': {}}
    rears = {}
    for tid in TASKS:
        mp = reg / f'task_{tid}' / 'world.stl'
        if not mp.exists():
            res['candidates'][tid] = {'error': 'no registered mesh'}; continue
        mesh = trimesh.load(str(mp), force='mesh', process=False)
        man, stats = v3_fuse.fuse_parent(art, mesh, out / f'task_{tid}',
                                         {'id': f'lux_{tid}',
                                          'mesh_sha256': v3_fuse.sha256_file(mp)}, proto)
        d = np.load(out / f'task_{tid}' / 'occ_full.npz')
        full = d['occupied']; origin = np.asarray(d['origin'], float); pitch = float(d['pitch'])
        xs = origin[0] + (np.arange(full.shape[0]) + 0.5) * pitch
        added = full & ~art['shell']
        ax = added.any(axis=(1, 2))
        far = float(xs[ax].max()) if ax.any() else float(xs[full.any(axis=(1, 2))].max())
        rears[tid] = far
        res['candidates'][tid] = {'full_sha': man['full_occ_sha'], 'obs_sha': man['obs_only_occ_sha'],
                                  'stats': stats, 'hidden_rear_x': round(far, 4)}
    first = '4632564'
    full_plan_params = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
                        'lower_at_x': round(rears.get(first, 1.20) + 0.10, 4),
                        'end_x': 2.6, 'stop_tilt_deg': 12.0,
                        'far_edge_source': f'candidate_{first}_hidden_rear'}
    full_plan = dict(full_plan_params, plan_id=plan_id(full_plan_params))
    obs_plan_params = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
                       'lower_at_x': 2.45, 'end_x': 2.6, 'stop_tilt_deg': 12.0,
                       'far_edge_source': 'unknown_hold'}
    obs_plan = dict(obs_plan_params, plan_id=plan_id(obs_plan_params))
    res['plans'] = {'full': full_plan, 'obs': obs_plan}
    res['plan_source_note'] = ('BODY plan is fixed across candidates; its hidden rear comes from the '
                               'first generated candidate (creation order), never from truth geometry')
    (out / 'fusion_summary.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'v': art['v_sha'][:12], 'rears': rears,
                      'full_plan': full_plan, 'obs_plan': obs_plan}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
