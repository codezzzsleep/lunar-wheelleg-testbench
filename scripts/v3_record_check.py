"""检查 record/ 的字段覆盖与缺口（50 Hz 全状态）。"""
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIRED = ['t', 'control_index', 'qpos', 'qvel', 'joint_target', 'joint_vel_target',
            'wheel_omega_target', 'wheel_brake', 'joint_torque', 'wheel_torque', 'tilt_deg']
rows = []
for rec in sys.argv[1:]:
    d = pathlib.Path(rec).resolve()
    chunks = sorted(d.glob('chunk_*.npz'))
    keys = set()
    n_frames = 0
    if chunks:
        z = np.load(chunks[0])
        keys = set(z.files)
        for c in chunks:
            n_frames += int(np.load(c)['t'].shape[0])
    contacts = sorted(d.glob('contacts_*.jsonl'))
    n_con = 0
    if contacts:
        for c in contacts:
            with c.open() as fh:
                for line in fh:
                    if '"geom1"' in line:
                        n_con += 1
    rows.append({'record': str(d.relative_to(ROOT)),
                 'chunks': len(chunks), 'frames': n_frames,
                 'keys': sorted(keys),
                 'missing': [k for k in REQUIRED if k not in keys],
                 'contacts_jsonl': len(contacts), 'contact_entries': n_con,
                 'notes': ['phase labels: only result.json boundaries, not per frame',
                           'wheel mode: brake flag present; velocity/coast not stored per frame',
                           'per-wheel load: derivable from contacts geom ids + model']})
out = ROOT / 'runs/v3/stage003/record_check.json'
out.write_text(json.dumps({'schema': 'v3-record-check/v1', 'records': rows},
                          ensure_ascii=False, indent=2))
print(json.dumps({'n': len(rows), 'frames': [r['frames'] for r in rows],
                  'missing': [r['missing'] for r in rows]}, ensure_ascii=False))
