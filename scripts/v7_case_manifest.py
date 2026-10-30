"""
V7：独立对象清单与独立性证据。

清单口径：
  · 对象 = 一块真实几何（真值网格），身份由**网格几何**决定；
  · 同一网格的缩放/旋转/多初态**不算**新对象；
  · 独立的判据：把两块石头各自缩放到同一高度、按包围盒中心对齐后，
    占据 IoU < 0.90 视为不同形状；否则记为同源变体。

同时登记每个对象的真实 Lux3D 候选（world 目录）与生成任务 ID（来自账本）。

  .venv/bin/python scripts/v7_case_manifest.py --out <json>
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import fuse_observed as FZ


def load(p):
    return FZ._load_mesh(ROOT / p if not pathlib.Path(p).is_absolute() else p)


def normalized_occupancy(mesh, target=44):
    """缩放到统一高度、包围盒中心对齐，再按最大边长映射到固定体素数。"""
    m = mesh.copy()
    e = np.asarray(m.extents, dtype=float)
    s = 1.0 / max(float(e[2]), 1e-9)          # 高度归一
    m.apply_scale([s, s, s])
    c = m.bounds.mean(axis=0)
    m.apply_translation(-c)
    ext = np.asarray(m.extents, dtype=float)
    pitch = float(max(ext.max(), 1e-9) / target)
    nb = np.maximum(np.ceil(ext / pitch).astype(int) + 2, 6)
    nb = np.full(3, int(target) + 2, dtype=int)      # 固定网格，保证可逐体素比较
    lo = -np.asarray(nb // 2, dtype=float) * pitch
    xs = lo[0] + (np.arange(nb[0]) + 0.5) * pitch
    ys = lo[1] + (np.arange(nb[1]) + 0.5) * pitch
    zs = lo[2] + (np.arange(nb[2]) + 0.5) * pitch
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    grid = {'origin': lo, 'pitch': pitch, 'dims': nb, 'xs': xs, 'ys': ys, 'zs': zs,
            'X': X, 'Y': Y, 'Z': Z}
    try:
        occ = FZ.ray_parity_occupancy(m, grid)
    except Exception:
        occ = FZ.parent_solid(m, grid, 1)[0]
    return occ


def iou(a, b):
    inter = int((a & b).sum()); uni = int((a | b).sum())
    return inter / uni if uni else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stones', default='runs/unseen/recovery_r3/stone_materials/stones.json')
    ap.add_argument('--out', default='runs/unseen/delivery_v7/v7_20261030/cases/independence.json')
    a = ap.parse_args()
    stones = json.loads((ROOT / a.stones).read_text())
    rows = stones['rows']
    meshes = {r['id']: load(r['file']) for r in rows}
    occs = {k: normalized_occupancy(m) for k, m in meshes.items()}
    ids = sorted(meshes)
    matrix = {}
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            matrix[f'{x}|{y}'] = round(iou(occs[x], occs[y]), 4)
    # 候选：world 目录 → 对象
    cand_map = {}
    for p in sorted((ROOT / 'runs/unseen').glob('*/*/world/*/body.stl')):
        cid = p.parent.name
        obj = None
        for key in ids:
            if f'_{key}' in cid or cid.endswith(key):
                obj = key
                break
        if obj:
            cand_map.setdefault(obj, []).append(str(p.parent.relative_to(ROOT)))
    ledger = ROOT / 'runs/unseen/generation/ledger.jsonl'
    tasks = 0
    if ledger.exists():
        tasks = sum(1 for l in ledger.read_text().splitlines() if l.strip())
    indep = {}
    for i, x in enumerate(ids):
        best = max((matrix.get(f'{min(x, y)}|{max(x, y)}', matrix.get(f'{x}|{y}', 0.0)), y)
                   for y in ids if y != x)
        indep[x] = {'max_normalized_iou_with_other': best[0], 'closest': best[1],
                    'independent': best[0] < 0.90}
    out = {
        'schema': 'case-manifest/v7',
        'independence_rule': 'scale-normalized occupancy IoU < 0.90 (same mesh scaled/rotated is NOT a new object)',
        'n_objects': len(ids),
        'n_independent': sum(1 for v in indep.values() if v['independent']),
        'objects': [{'id': r['id'], 'source_stone': r.get('source_stone'),
                     'file': r['file'], 'extents_m': r.get('extents_m'),
                     'volume_m3': r.get('volume_m3'),
                     'n_candidates': len(cand_map.get(r['id'], [])),
                     'candidates': cand_map.get(r['id'], []),
                     **indep[r['id']]} for r in rows],
        'pairwise_normalized_iou': matrix,
        'history_tasks_in_ledger': tasks,
        'note': ('对象只按几何独立；R01 是开发诊断、不计作留出对象。'
                 '同一网格的缩放/旋转/多初态不算新对象。'),
    }
    op = ROOT / a.out
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'n_objects': out['n_objects'], 'n_independent': out['n_independent'],
                      'pairwise': matrix}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
