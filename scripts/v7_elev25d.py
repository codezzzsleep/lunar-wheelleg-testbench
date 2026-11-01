"""2.5D 高程图两策略（下一批任务书 §5）。

从**本次观测的完整有效深度**（含可见地面）构建世界坐标高程图，1 cm 格；
视野外、遮挡后与无效深度保留 unknown；补平区域标 imputed；
地图范围由公共任务区（goal_x、通道半宽、前沿）确定，不读真值包围盒。

两个策略共用同一张高程图，只在 unknown 的处理上不同：

  E25D_block_unknown  未知按禁入区域处理（未知格作为高障碍）
  E25D_fill_unknown   未知按可见地面延拓/补平（imputed，不读真实隐藏高度）

产物是 box 并集资产（posed_dir），可直接交给共同规划器做物理预演。

  python scripts/v7_elev25d.py --observation <obs> --case <case.json> \
      --strategy block|fill --out <dir>
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np

import camera_io

CELL_M = 0.01
UNKNOWN_BLOCK_HEIGHT_M = 0.60      # 禁入高度：高于任何可通行判据
SCHEMA = 'elev25d/v1'


def load_observation(obs_dir):
    obs_dir = pathlib.Path(obs_dir)
    obsd = json.loads((obs_dir / 'observation.json').read_text())
    depth = np.load(obs_dir / 'depth.npy').astype(np.float64)
    return obsd, depth


def build_elevation(obs_dir, case, cell=CELL_M):
    """世界高程图：observed 高度 + unknown 掩码。范围只用公共任务区。"""
    obsd, depth = load_observation(obs_dir)
    snap = obsd['camera']
    if 'intrinsics' not in snap:
        K = camera_io.intrinsics(depth.shape[1], depth.shape[0], obsd['camera'].get('fovy', 70.0))
        snap = dict(snap, intrinsics=K)
    pts, ys, xs = camera_io.unproject_depth(depth, snap)
    if len(pts) < 100:
        raise SystemExit('有效深度点过少：拒绝用坏观测构建高程图')

    x_front = float(obsd['visible']['x_front'])
    half = float(case.get('channel_half', 1.2))
    goal_x = float(case.get('goal_x', 2.6))
    # 网格原点必须落在格点lattice上：否则 box 索引与世界坐标错位（实测错过约 1 m）
    x0 = np.floor(max(0.0, x_front - 0.60) / cell) * cell
    x1 = np.ceil(goal_x / cell) * cell
    y0 = np.floor(-half / cell) * cell
    y1 = np.ceil(half / cell) * cell
    nx = int(np.ceil((x1 - x0) / cell))
    ny = int(np.ceil((y1 - y0) / cell))
    H = np.full((nx, ny), np.nan, dtype=np.float64)     # 高程（世界 z 上表面）
    OBS = np.zeros((nx, ny), dtype=bool)
    ix = np.clip(((pts[:, 0] - x0) / cell).astype(np.int64), 0, nx - 1)
    iy = np.clip(((pts[:, 1] - y0) / cell).astype(np.int64), 0, ny - 1)
    inside = (pts[:, 0] >= x0) & (pts[:, 0] < x1) & (pts[:, 1] >= y0) & (pts[:, 1] < y1)
    z = pts[:, 2]
    for a, b, zz in zip(ix[inside], iy[inside], z[inside]):
        if not OBS[a, b]:
            H[a, b] = zz
            OBS[a, b] = True
        else:
            H[a, b] = max(H[a, b], zz)
    meta = {'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1, 'cell': cell, 'nx': nx, 'ny': ny,
            'source': str(pathlib.Path(obs_dir)), 'x_front': x_front,
            'extent_rule': '公共任务区（前沿-0.6 m .. goal_x，±通道半宽），不读真值包围盒'}
    return H, OBS, meta


def ground_reference(H, OBS, meta):
    """可见地面的高程基准：取观测格的低分位数（地面），用于补平与箱体底面。"""
    vals = H[OBS]
    if vals.size == 0:
        return 0.0
    return float(np.percentile(vals, 20))


def to_boxes(H, OBS, meta, strategy, ground_z, cell=CELL_M):
    """高程图 → 轴对齐 box（每格一个），未知按策略处理。"""
    nx, ny = H.shape
    x0, y0 = meta['x0'], meta['y0']
    boxes, unknown_cells, imputed_cells = [], 0, 0
    for a in range(nx):
        for b in range(ny):
            h = H[a, b]
            observed = OBS[a, b]
            if not observed:
                unknown_cells += 1
                if strategy == 'block':
                    top = ground_z + UNKNOWN_BLOCK_HEIGHT_M
                else:
                    top = ground_z          # 补平：与可见地面同高（imputed）
                    imputed_cells += 1
            else:
                top = h
            base = ground_z
            if top <= base + 1e-4:
                continue                    # 平地不需要碰撞盒
            # 加载器的 box 索引是**闭区间**：单格写作 [a,a]、[b,b]，
            # 世界范围 = origin + [i0, i1+1] * pitch。这里必须按闭区间给索引。
            xa = a
            ya = b
            za = int(np.floor(base / cell))
            zb = int(np.ceil(top / cell)) - 1
            if zb <= za:
                zb = za + 1
            if zb < za:
                zb = za
            boxes.append([int(xa), int(xa), int(ya), int(ya), int(za), int(zb)])
    return boxes, {'unknown_cells': unknown_cells, 'imputed_cells': imputed_cells,
                   'n_boxes': len(boxes)}


def write_asset(out_dir, boxes, meta, info, strategy, cell=CELL_M):
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    origin = [meta['x0'], meta['y0'], 0.0]
    man = {
        'schema': 'asset-manifest/v1', 'asset_id': f'elev25d_{strategy}',
        'hypothesis_id': f'E25D_{strategy}', 'version': SCHEMA,
        'coordinate_frame': 'world', 'source_kind': 'elevation',
        'boxes': boxes, 'pitch_m': cell, 'grid_origin': origin,
        'grid_dims': [meta['nx'], meta['ny']],
        'n_boxes': len(boxes), 'n_source_voxels': info['unknown_cells'] + info['imputed_cells'],
        'parts': [], 'T_world_from_asset': [[1, 0, 0, 0], [0, 1, 0, 0],
                                            [0, 0, 1, 0], [0, 0, 0, 1]],
        'body_pose_expected': {'pos': [0.0, 0.0, 0.0], 'quat': [1.0, 0.0, 0.0, 0.0]},
        'rest_pose': False, 'pass': True,
        'cell_m': cell, 'strategy': strategy, 'extent': meta,
        'unknown_policy': ('blocked' if strategy == 'block' else 'imputed_from_visible_ground'),
        **info,
        'note': ('2.5D 高程图策略：观测高程进入同一物理预演；'
                 'unknown 不伪装成 observed，补平格标 imputed。'),
    }
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    return man


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--observation', required=True)
    ap.add_argument('--case', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cell', type=float, default=CELL_M)
    a = ap.parse_args()
    case = json.loads((ROOT / a.case).read_text())
    H, OBS, meta = build_elevation(ROOT / a.observation, case, a.cell)
    ground = ground_reference(H, OBS, meta)
    out_root = ROOT / a.out
    res = {'schema': 'elev25d-report/v1', 'observation': a.observation, 'case': a.case,
           'cell_m': a.cell, 'extent': meta, 'ground_z': round(ground, 4),
           'observed_cells': int(OBS.sum()), 'total_cells': int(OBS.size),
           'unknown_frac': round(1.0 - OBS.mean(), 4), 'strategies': {}}
    for strat in ('block', 'fill'):
        boxes, info = to_boxes(H, OBS, meta, strat, ground, a.cell)
        d = out_root / strat
        man = write_asset(d, boxes, meta, info, strat, a.cell)
        res['strategies'][strat] = {'dir': str(d.relative_to(ROOT)),
                                    'n_boxes': man['n_boxes'],
                                    'unknown_policy': man['unknown_policy'],
                                    **{k: info[k] for k in ('unknown_cells', 'imputed_cells')}}
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / 'elev25d.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'observed_cells': res['observed_cells'],
                      'unknown_frac': res['unknown_frac'],
                      'strategies': {k: {'n_boxes': v['n_boxes'],
                                         'imputed': v['imputed_cells']}
                                     for k, v in res['strategies'].items()}},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
