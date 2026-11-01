"""S0–S4 已知答案自检：验证「表示链」自身自洽，而不是候选质量。

用途（任务书 §3.3）：在 R01/R02 的真实观测包上，用**该配置的真值实体**走一遍
导出、占据、自由空间、观测壳四层，定位误差首次出现的位置。

  S0 原实体          案例定义的真值网格（未经过本工程任何转换）
  S1 正式导出加载    STL 往返（float32）后重新加载
  S2 占据与表面提取  占据化 + 等值面提取
  S3 自由空间约束    S2 占据再按观测自由空间 carve
  S4 观测壳与完整融合 完整 fuse（壳层 + 带约束 + 洞填充）

每一层都用**同一相机、同一观测、同一评价器**测量 mask_iou / vis_pt_p95 /
freespace_violation，并给出是否通过冻结阈值。

  python scripts/v7_stage_fixture.py --observation <obs_dir> --entity <truth mesh> \
      --out <dir> [--pitch 0.0025]
"""
import argparse
import json
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np
import trimesh

import align
import camera_io
import fuse_observed as FO
import meshdist

THRESH = {'mask_iou_min': 0.85, 'vis_pt_p95_mm_base': 5.0,
          'vis_pt_p95_h_frac': 0.03, 'freespace_max': 0.05}



def _jsonable(o):
    """把评价器返回里的 Path / numpy 标量转成可序列化形式。"""
    if isinstance(o, pathlib.Path):
        return str(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o


def measure(mesh, obs_dir, cfg, pitch, out_dir, tag):
    """用与正式融合完全相同的评价器测量任意网格。"""
    obs_dir = pathlib.Path(obs_dir)
    obsd = json.loads((obs_dir / 'observation.json').read_text())
    h_vis = float(obsd['visible']['H_vis'])
    p95_limit = max(THRESH['vis_pt_p95_mm_base'], THRESH['vis_pt_p95_h_frac'] * h_vis * 1000)
    tmp = out_dir / f'_{tag}.stl'
    mesh.export(tmp)
    m = {}
    posed = None
    try:
        import v7_multimesh as _MM
        if len(mesh.faces) > _MM.MAX_FACES_DEFAULT:
            _pd = out_dir / f'_visual_parts_{tag}'
            _parts, _meta = _MM.split_mesh(mesh, _MM.MAX_FACES_DEFAULT)
            _MM.write_world(_parts, _pd, FO.sha_file(tmp), len(mesh.faces), {'split': _meta})
            posed = str(_pd)
            m['visual_parts'] = _meta
    except Exception as _e:
        m['visual_parts_error'] = f'{type(_e).__name__}: {_e}'
    try:
        m.update(align.render_eval(mesh, str(obs_dir), tmpdir=str(tmp),
                                   W=None, H=None, want_vis_pt=False,
                                   posed_dir=posed))
    except Exception as e:
        m['error'] = f'{type(e).__name__}: {e}'
    vis = np.load(obs_dir / 'visible_points.npy')
    if len(vis) > 1200:
        vis = vis[np.random.default_rng(0).choice(len(vis), 1200, replace=False)]
    try:
        d = meshdist.point_to_mesh_distance(mesh, vis, chunk=64)
        m['vis_pt_p95_mm'] = round(float(np.percentile(d, 95)) * 1000, 3)
        m['vis_pt_med_mm'] = round(float(np.median(d)) * 1000, 3)
    except Exception as e:
        m['vis_pt_error'] = f'{type(e).__name__}: {e}'
    tmp.unlink(missing_ok=True)
    iou = m.get('mask_iou')
    p95 = m.get('vis_pt_p95_mm')
    free = m.get('freespace_violation')
    ok = (iou is not None and iou >= THRESH['mask_iou_min']
          and p95 is not None and p95 <= p95_limit
          and free is not None and free <= THRESH['freespace_max'])
    return {'tag': tag, 'mask_iou': iou, 'vis_pt_p95_mm': p95,
            'freespace_violation': free,
            'watertight': bool(mesh.is_watertight),
            'n_faces': int(len(mesh.faces)),
            'volume_m3': (round(abs(float(mesh.volume)), 9)
                          if mesh.is_watertight else None),
            'p95_limit_mm': round(p95_limit, 3),
            'pass': bool(ok), 'metrics_raw': _jsonable(m)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--observation', required=True)
    ap.add_argument('--entity', required=True, help='该配置的真值实体网格')
    ap.add_argument('--out', required=True)
    ap.add_argument('--pitch', type=float, default=0.0025)
    ap.add_argument('--config', default='configs/unseen_v7_r1_fusion_offset1.json')
    ap.add_argument('--levels', default='S0,S1,S2,S3,S4',
                    help='要跑的层，逗号分隔；扫参数时只跑 S4')
    ap.add_argument('--shell-offset', type=float, default=None,
                    help='覆盖 shell_offset_voxels（有界单因素对照）')
    a = ap.parse_args()

    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    obs_dir = ROOT / a.observation
    entity = ROOT / a.entity
    # 必须传字符串：load_effective_config 会把 base_path 原样写进 cfg，
    # 传 Path 会让下游 json.dumps(cfg) 抛 PosixPath 不可序列化。
    eff = FO.load_effective_config(a.config, {'pitch_m': a.pitch})
    cfg = dict(eff)
    cfg['_sha'] = eff['sha256']

    want = set(x.strip().upper() for x in a.levels.split(',') if x.strip())
    if a.shell_offset is not None:
        cfg['shell_offset_voxels'] = float(a.shell_offset)
    levels = []
    t0 = time.time()

    # S0 原实体
    s0 = FO._load_mesh(entity)
    if 'S0' in want:
        levels.append(measure(s0, obs_dir, cfg, a.pitch, out, 'S0_entity'))

    # S1 STL 往返（float32）
    p1 = out / 'S1_roundtrip.stl'
    s0.export(p1)
    s1 = FO._load_mesh(p1)
    if 'S1' in want:
        levels.append(measure(s1, obs_dir, cfg, a.pitch, out, 'S1_export'))

    # 共同栅格（以 S1 为父，保证后面几层可比）
    vis = np.load(obs_dir / 'visible_points.npy')
    grid = FO.make_grid(s1, vis, a.pitch, int(cfg['margin_cells']))
    space, space_stats = FO.classify_space(obs_dir, grid, float(cfg['free_epsilon_m']),
                                           float(cfg['band_m']),
                                           (float(cfg['depth_edge_threshold_m'])
                                            if cfg.get('use_depth_edge_exclusion') else 0.0))

    # S2 占据 + 表面提取
    inside, pstats = FO.parent_solid(s1, grid, 0)
    occ2, _n2 = FO.largest_component(inside)
    m2 = FO.marching_tets(occ2, grid)
    if len(m2.faces) and not m2.is_watertight:
        trimesh.repair.fill_holes(m2); trimesh.repair.fix_normals(m2)
    if 'S2' in want:
        levels.append(measure(m2, obs_dir, cfg, a.pitch, out, 'S2_occupancy'))

    # S3 自由空间约束
    occ3, _n3 = FO.largest_component(occ2 & (space != 2))
    m3 = FO.marching_tets(occ3, grid)
    if len(m3.faces) and not m3.is_watertight:
        trimesh.repair.fill_holes(m3); trimesh.repair.fix_normals(m3)
    if 'S3' in want:
        levels.append(measure(m3, obs_dir, cfg, a.pitch, out, 'S3_freespace'))

    # S4 完整融合（壳层 + 带 + 洞填充），复用正式 fuse()
    s4_dir = out / 'S4_full_fusion'
    parent_dir = out / '_s4_parent'
    parent_dir.mkdir(parents=True, exist_ok=True)
    s1.export(parent_dir / 'body.stl')
    man4 = FO.fuse(obs_dir, parent_dir, 'fixture_truth', s4_dir, cfg,
                   method='H5_F', seed=0)
    if 'S4' in want:
      levels.append({'tag': 'S4_shell_full', 'mask_iou': man4['metrics'].get('mask_iou'),
                   'vis_pt_p95_mm': man4['metrics'].get('vis_pt_p95_mm'),
                   'freespace_violation': man4['metrics'].get('freespace_violation'),
                   'watertight': man4.get('watertight'),
                   'n_faces': None, 'volume_m3': man4.get('volume_m3'),
                   'p95_limit_mm': man4['strict']['p95_mm_threshold'],
                   'pass': bool(man4['strict']['pass']),
                   'metrics_raw': _jsonable(man4['metrics']),
                   'shell_offset_voxels': cfg.get('shell_offset_voxels')})

    first_fail = next((l['tag'] for l in levels if not l['pass']), None)
    rep = {
        'schema': 'stage-fixture/v1',
        'observation': a.observation,
        'observation_sha': FO.sha_file(obs_dir / 'observation.json'),
        'entity': a.entity,
        'entity_sha': FO.sha_file(entity),
        'pitch_m': a.pitch,
        'effective_config_sha': cfg['_sha'],
        'thresholds': THRESH,
        'grid': {'dims': [int(x) for x in grid['dims']],
                 'pitch_m': float(grid['pitch']),
                 'n_voxels': int(np.prod(grid['dims']))},
        'space': space_stats,
        'levels': levels,
        'first_failing_level': first_fail,
        'verdict': ('PASS' if first_fail is None else f'FAIL_AT_{first_fail}'),
        'note': ('fixture 只用该配置真值实体验证表示链自洽，不作为生成候选；'
                 'S0/S1 失败先查输入与相机，不进入融合调参。'),
        'seconds': round(time.time() - t0, 2),
    }
    (out / 'fixture_report.json').write_text(
        json.dumps(_jsonable(rep), ensure_ascii=False, indent=2))
    print(json.dumps({k: rep[k] for k in ('verdict', 'first_failing_level', 'seconds')},
                     ensure_ascii=False))
    for l in levels:
        print(f"  {l['tag']:<18} iou={l['mask_iou']} p95={l['vis_pt_p95_mm']} "
              f"free={l['freespace_violation']} pass={l['pass']}")


if __name__ == '__main__':
    main()
