"""Stage009：矩阵缓存身份与适用性（回归修复）。"""
import hashlib
import json
import pathlib


class CacheMismatch(RuntimeError):
    pass


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def protocol_sha(proto_path='plans/v3_protocol.json',
                 cfg_path='configs/stage6_protocol.json', root=None):
    root = pathlib.Path(root or pathlib.Path(__file__).resolve().parent.parent)
    h = hashlib.sha256()
    for p in (proto_path, cfg_path):
        h.update((root / p).read_bytes())
    return h.hexdigest()


def make_identity(*, s0_hash, scene_sha, plan_id, actions, applic, protocol):
    return {'schema': 'stage8-cache-identity/v1', 's0_state_hash': s0_hash,
            'scene_sha256': scene_sha, 'plan_id': plan_id, 'actions': list(actions),
            'applicability': {a: bool(v) for a, v in applic.items()},
            'protocol_sha256': protocol}


def write_cache(path, identity, rows):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        f.write(json.dumps({'kind': 'cache_header', 'identity': identity}, ensure_ascii=False) + '\n')
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return path


def read_cache(path, expected):
    path = pathlib.Path(path)
    lines = path.read_text().splitlines()
    if not lines:
        raise CacheMismatch('empty cache')
    head = json.loads(lines[0])
    if head.get('kind') != 'cache_header':
        raise CacheMismatch('cache has no header')
    got = head.get('identity', {})
    for k in ('s0_state_hash', 'scene_sha256', 'plan_id', 'protocol_sha256'):
        if got.get(k) != expected.get(k):
            raise CacheMismatch(f'identity mismatch on {k}: {got.get(k)} != {expected.get(k)}')
    if got.get('actions') != expected.get('actions'):
        raise CacheMismatch('actions mismatch')
    if got.get('applicability') != expected.get('applicability'):
        raise CacheMismatch('applicability mismatch')
    rows = [json.loads(l) for l in lines[1:] if l.strip()]
    return rows, got['applicability']
