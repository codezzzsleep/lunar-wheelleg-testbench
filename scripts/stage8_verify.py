"""Stage008：逐分块/接触/碰撞文件校验（不只校验 index.sha256）。"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def verify_index(idx):
    recs = json.loads(idx.read_text())
    parent = idx.parent
    errs = []
    frames = 0
    ncon = 0
    for c in recs.get('chunks', []):
        ap = parent / c['arrays']
        cp = parent / c.get('contacts', '')
        if not ap.exists():
            errs.append(f"missing {ap.name}"); continue
        if sha(ap) != c.get('arrays_sha256'):
            errs.append(f"sha {ap.name}")
        try:
            z = np.load(ap)
            n = int(z['qpos'].shape[0])
            if n != int(c.get('frames', -1)):
                errs.append(f"frames {ap.name}: {n}!={c.get('frames')}")
            frames += n
        except Exception as e:  # noqa: BLE001
            errs.append(f"read {ap.name}: {e}")
        if c.get('contacts'):
            if not cp.exists():
                errs.append(f"missing {cp.name}")
            elif sha(cp) != c.get('contacts_sha256'):
                errs.append(f"sha {cp.name}")
            else:
                ncon += int(c.get('contacts_n', 0))
    if recs.get('frame_count') is not None and frames != int(recs['frame_count']):
        errs.append(f"frame_count {frames}!={recs['frame_count']}")
    if recs.get('contacts_n') is not None and ncon != int(recs['contacts_n']):
        errs.append(f"contacts_n {ncon}!={recs['contacts_n']}")
    return {'index': str(idx.relative_to(ROOT)), 'schema': recs.get('schema'),
            'frames': frames, 'contacts_n': ncon, 'ok': not errs, 'errors': errs}


def verify_coll(man):
    m = json.loads(man.read_text())
    parent = man.parent
    errs = []
    n = len(m.get('boxes') or [])
    if m.get('n_boxes') is not None and int(m['n_boxes']) != n:
        errs.append(f"n_boxes {n}!={m['n_boxes']}")
    parts = m.get('parts') or []
    if len(parts) != n:
        errs.append(f"parts {len(parts)}!=boxes {n}")
    for p in parts:
        if not (parent / p).exists():
            errs.append(f"missing {p}")
            break
    agg = hashlib.sha256()
    for p in parts:
        fp = parent / p
        if fp.exists():
            agg.update(fp.read_bytes())
    return {'manifest': str(man.relative_to(ROOT)), 'n_boxes': n, 'parts': len(parts),
            'parts_sha256_aggregate': agg.hexdigest(), 'ok': not errs, 'errors': errs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--roots', nargs='+', default=['runs/v3/stage007/cand_small',
                                                   'runs/v3/stage006/fix'])
    ap.add_argument('--out', default='runs/v3/stage008/verification.json')
    a = ap.parse_args()
    out = ROOT / a.out; out.parent.mkdir(parents=True, exist_ok=True)
    idxs, colls = [], []
    for r in a.roots:
        base = ROOT / r
        idxs += sorted(base.rglob('index.json'))
        colls += sorted(base.rglob('manifest.json'))
    idx_res = [verify_index(p) for p in idxs]
    coll_res = [verify_coll(p) for p in colls if 'record' not in str(p.parent)]
    bad = [x for x in idx_res + coll_res if not x['ok']]
    summary = {'schema': 'stage8-verification/v1', 'indexes': len(idx_res),
               'collisions': len(coll_res), 'failures': len(bad),
               'indexes_ok': sum(x['ok'] for x in idx_res),
               'collisions_ok': sum(x['ok'] for x in coll_res),
               'details': {'indexes': idx_res, 'collisions': coll_res}}
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({'indexes': len(idx_res), 'ok': summary['indexes_ok'],
                      'collisions': len(coll_res), 'coll_ok': summary['collisions_ok'],
                      'failures': len(bad), 'examples': [x for x in bad[:3]]},
                     ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
