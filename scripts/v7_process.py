"""
V7：候选处理链（清理后的世界资产 → 观测融合 → 碰撞 → 保真测量）。

一条命令跑完一个候选的处理，并把每步身份写进 `process.json`：
  source_world_sha / fusion_world_sha / collision_rep / collision_content_sha /
  collision_metrics_identity / physics_config_sha

  .venv/bin/python scripts/v7_process.py --candidate-dir <dir with align/world> \
      --observation <obs> --out <dir> [--pitch 0.004]
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def run(cmd, log):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    pathlib.Path(log).write_text(r.stdout + '\n' + r.stderr)
    if r.returncode != 0:
        raise SystemExit(f'失败 {cmd[1]}: {r.stderr[-400:]}')
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate-dir', required=True)
    ap.add_argument('--world', default=None, help='世界资产目录；缺省 <candidate>/world/align')
    ap.add_argument('--observation', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--pitch', type=float, default=0.004)
    ap.add_argument('--method', default='H5_F')
    a = ap.parse_args()
    cdir = ROOT / a.candidate_dir
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    world = pathlib.Path(a.world) if a.world else (cdir / 'world' / 'align')
    world = world if world.is_absolute() else (ROOT / world)
    if not (world / 'body.stl').exists():
        raise SystemExit(f'找不到世界资产：{world}/body.stl')
    fus = out / 'fusion'
    box = out / 'collision'
    pitches = [a.pitch] + [p for p in (0.006, 0.008, 0.010) if p > a.pitch]
    fm = None
    used_pitch = None
    for k, pitch in enumerate(pitches):
        run([sys.executable, 'scripts/fuse_observed.py', '--observation', a.observation,
             '--parent-world', str(world), '--parent-id', cdir.name, '--method', a.method,
             '--out', str(fus), '--pitch', str(pitch)], out / 'fusion.log')
        fm = json.loads((fus / 'manifest.json').read_text())
        err = str(((fm.get('metrics') or {}).get('error') or ''))
        used_pitch = pitch
        if 'number of faces' not in err and 'stl_decoder' not in err:
            break
        # 面数超 MuJoCo 上限：提高构建分辨率（更粗）后重来，并如实记录
        print(json.dumps({'pitch_retry': pitch, 'error': err[:120]}, ensure_ascii=False))
    fm['_pitch_used'] = used_pitch
    run([sys.executable, 'scripts/collision_box_union.py', '--mesh', str(fus / 'body.stl'),
         '--out', str(box), '--pitch', str(used_pitch), '--hypothesis-id', f'{cdir.name}_box'],
        out / 'collision.log')
    bm = json.loads((box / 'manifest.json').read_text())
    run([sys.executable, 'scripts/collision_occupancy_metrics.py', '--mesh',
         str(fus / 'body.stl'), '--collision', str(box), '--out', str(box / 'metrics.json'),
         '--label', f'{cdir.name}_box', '--eval-pitch', '0.0025'], out / 'metrics.log')
    cm = json.loads((box / 'metrics.json').read_text())
    rec = {
        'schema': 'v7-candidate-process/v1',
        'candidate': cdir.name,
        'observation': a.observation,
        'source_world_sha': json.loads((world / 'manifest.json').read_text()).get('world_sha'),
        'fusion_world_sha': fm.get('world_sha'),
        'fusion_metrics': {k: (fm.get('metrics') or {}).get(k) for k in
                           ('mask_iou', 'vis_pt_p95_mm', 'freespace_violation',
                            'depth_p95_mm')},
        'fusion_strict': fm.get('strict'),
        'collision_representation': 'box_union',
        'collision_content_sha': bm.get('collision_sha'),
        'n_boxes': bm.get('n_boxes'),
        'physics_config_sha': fm.get('inputs', {}).get('effective_config_sha'),
        'fusion_pitch_m': used_pitch,
        'collision_metrics_identity': {
            'label': cm.get('label'), 'eval_pitch_m': cm.get('geometry', {}).get('eval_pitch_m'),
            'source_sha': cm.get('source_sha'), 'collision_sha_manifest': cm.get('collision_sha_manifest')},
        'collision_verdict': cm.get('verdict'),
        'collision_geometry': {k: cm['geometry'][k] for k in
                               ('occupancy_iou', 'over_fill_frac_of_collision',
                                'under_fill_frac_of_source')},
        'collision_surface_mm': {
            's2c_p95': cm['geometry']['source_to_collision_mm']['p95'],
            'c2s_p95': cm['geometry']['collision_to_source_mm']['p95']},
        'qualified_visible': bool((fm.get('strict') or {}).get('pass')),
        'qualified_collision': cm.get('verdict') == 'PASS',
        'paths': {'fusion': str(fus), 'collision': str(box)},
    }
    rec['qualified'] = rec['qualified_visible'] and rec['qualified_collision']
    (out / 'process.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: rec[k] for k in ('candidate', 'qualified_visible',
                                          'qualified_collision', 'qualified')} |
                     {'iou': rec['fusion_metrics']['mask_iou'],
                      'free': rec['fusion_metrics']['freespace_violation'],
                      'coll_iou': rec['collision_geometry']['occupancy_iou']},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
