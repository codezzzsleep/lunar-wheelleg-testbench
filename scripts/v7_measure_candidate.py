"""对**任意一个已融合候选**跑双门槛测量（碰撞盒并集 + 保真指标），一条命令。

  .venv/bin/python scripts/v7_measure_candidate.py \
      --fusion runs/.../fusion_diagnostics/off1_R04_s2 --pitch 0.0025 --eval-pitch 0.004

输出：<fusion>/collision/{manifest.json,parts/} 与 <fusion>/collision/metrics_full.json，
并按冻结口径打印 PASS/ATTENTION（IoU>=0.95、s2c/c2s P95<=5 mm）。
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() \
     else sys.executable


def run(cmd):
    print('$ ' + ' '.join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def _mem_available_gb():
    try:
        for line in open('/proc/meminfo'):
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return None


def require_memory(min_gb=8.0, allow_local=False, what='占据/距离测量'):
    """内存不够就拒绝在本地跑，而不是把整机 OOM 掉。

    实测教训：本地 8 GB 机器上跑 0.026 m³ 对象的占据重建会到 7.2 GB，
    触发 global OOM，连 harness worker 一起被杀。重活应当在 CNB 沙箱（16 GB）跑。
    """
    avail = _mem_available_gb()
    if avail is None or allow_local or avail >= min_gb:
        return avail
    raise SystemExit(
        f'{what} 需要约 {min_gb:.0f} GB 可用内存，当前仅 {avail:.1f} GB：'
        '请到沙箱运行（ssh cnb-... 或 scripts/cnb_run.sh），'
        '确需本地跑请加 --allow-local')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fusion', required=True, help='含 body.stl 的融合输出目录')
    ap.add_argument('--pitch', type=float, default=0.0025, help='碰撞盒体素')
    ap.add_argument('--eval-pitch', type=float, default=0.004, help='评价网格')
    ap.add_argument('--parity', default='full', choices=['full', 'approx'])
    ap.add_argument('--label', default=None)
    ap.add_argument('--allow-local', action='store_true',
                    help='内存不足时仍允许在本机运行（可能 OOM）')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    require_memory(allow_local=getattr(a, 'allow_local', False))
    f = ROOT / a.fusion
    body = f / 'body.stl'
    if not body.exists():
        raise SystemExit(f'缺少 {body}（先跑 fuse_observed）')
    col = f / 'collision'
    metrics = col / 'metrics_full.json'
    label = a.label or f.name
    if col.exists() and metrics.exists() and not a.force:
        print(f'已有测量结果，跳过（--force 重跑）：{metrics.relative_to(ROOT)}')
    else:
        col.mkdir(parents=True, exist_ok=True)
        rc = run([PY, 'scripts/collision_box_union.py', '--mesh', str(body),
                  '--out', str(col), '--pitch', str(a.pitch),
                  '--hypothesis-id', label])
        if rc:
            return rc
        rc = run([PY, 'scripts/collision_occupancy_metrics.py', '--mesh', str(body),
                  '--collision', str(col), '--out', str(metrics),
                  '--label', label, '--eval-pitch', str(a.eval_pitch),
                  '--parity', a.parity])
        if rc:
            return rc
    d = json.loads(metrics.read_text())
    g = d.get('geometry') or {}
    s2c = (g.get('source_to_collision_mm') or {}).get('p95')
    c2s = (g.get('collision_to_source_mm') or {}).get('p95')
    ok = (g.get('occupancy_iou') is not None and g['occupancy_iou'] >= 0.95
          and s2c is not None and s2c <= 5.0 and c2s is not None and c2s <= 5.0)
    print(json.dumps({'candidate': label, 'collision_pass': bool(ok),
                      'iou': g.get('occupancy_iou'), 's2c_p95_mm': s2c, 'c2s_p95_mm': c2s,
                      'eval_pitch_m': g.get('eval_pitch_m'),
                      'parity': (d.get('parity_source') or {}).get('method'),
                      'peak_rss_mb': d.get('peak_rss_mb'),
                      'metrics': str(metrics.relative_to(ROOT))}, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
