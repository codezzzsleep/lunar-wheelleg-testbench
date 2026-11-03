"""从状态目录生成 Lux3D 任务清单（身份、顺序、首候选固定 A1）。

  python scripts/v3_make_tasks.py --protocol plans/v3_protocol.json \
      --states all --out runs/v3/generation/tasks.json
"""
import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VARIANTS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--states', nargs='+', default=['all'])
    ap.add_argument('--only', nargs='+', default=None, help='限定 state_id')
    ap.add_argument('--out', default='runs/v3/generation/tasks.json')
    ap.add_argument('--per-state-limit', type=int, default=0)
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    gen = proto['generation']
    states_dir = ROOT / 'runs/v3/states'
    sids = []
    for d in sorted(states_dir.glob('*/state.json')):
        st = json.loads(d.read_text())
        sids.append(st['state_id'])
    if a.only:
        sids = [s for s in sids if s in set(a.only)]
    tasks = []
    order = 0
    for sid in sids:
        vj = json.loads((states_dir / sid / 'observation/gen/variants/variants.json').read_text())
        vlist = VARIANTS
        if a.per_state_limit:
            vlist = vlist[:int(a.per_state_limit)]
        for v in vlist:
            rec = vj['variants'][v]
            order += 1
            tasks.append({
                'id': f'{sid}_{v}',
                'state_id': sid,
                'variant': v,
                'repeat_idx': int(rec.get('repeat_idx', 0)),
                'image': str((ROOT / rec['path']).resolve()),
                'image_sha256': rec['sha256'],
                'model': {'version': gen['version'], 'face_count': int(gen['face_count'])},
                'create_order': order,
                'estimated_credits': float(gen.get('credits_upper_per_task', 20)),
            })
    out = {'schema': 'v3-generation-tasks/v1', 'protocol': a.protocol,
           'protocol_sha256': sha256_file(ROOT / a.protocol),
           'n': len(tasks), 'states': sids, 'variants': VARIANTS,
           'note': 'A1 固定为首候选；每状态 6 个候选（A/B/C 各两次独立生成）',
           'tasks': tasks}
    o = ROOT / a.out
    o.parent.mkdir(parents=True, exist_ok=True)
    o.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'n_tasks': len(tasks), 'n_states': len(sids), 'out': str(o)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
