"""为一次已完成的运行补齐 run_manifest / effective_config / status（SPEC §11.3）。

不重跑、不改结果；只读取目录里已有的 result.json 与 frames.npz，写三个清单文件。
所有字段可核对：文件 SHA、代码 SHA、命令与沙箱地址。

  python scripts/v3_run_meta.py --dir runs/v3/basic_cycle/rigid_r1 \
      --run-id rigid_r1 --code-commit <sha> --command "..." \
      --sandbox "cnb-...@cnb.space" --status passed
"""
import argparse
import hashlib
import json
import pathlib
import time


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--code-commit', required=True)
    ap.add_argument('--command', required=True)
    ap.add_argument('--sandbox', default='')
    ap.add_argument('--status', choices=['passed', 'failed', 'partial'], required=True)
    ap.add_argument('--parent', default=None)
    a = ap.parse_args()
    d = pathlib.Path(a.dir)
    res_p = d / 'result.json'
    if not res_p.is_file():
        raise SystemExit(f'缺少 result.json：{res_p}')
    res = json.loads(res_p.read_text())
    files = {}
    for p in sorted(d.rglob('*')):
        if p.is_file() and p.name not in ('run_manifest.json', 'effective_config.json',
                                          'status.json'):
            files[str(p.relative_to(d))] = {
                'bytes': p.stat().st_size, 'sha256': sha256_file(p)}
    manifest = {
        'schema': 'v3-run-manifest/v1',
        'run_id': a.run_id,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'code_commit': a.code_commit,
        'sandbox': a.sandbox,
        'command': a.command,
        'parent_run': a.parent,
        'inputs': {'result_schema': res.get('schema'),
                   'soil': res.get('soil'), 'swing': res.get('swing'),
                   'cycles_requested': res.get('cycles_requested')},
        'outputs': files,
        'result_sha256': files.get('result.json', {}).get('sha256'),
    }
    (d / 'run_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    cfg = {
        'schema': 'v3-effective-config/v1',
        'run_id': a.run_id,
        'environment': {'sandbox': a.sandbox, 'code_commit': a.code_commit},
        'scene': {'kind': 'flat', 'goal_x': 5.0, 'channel_half_m': 1.2,
                  'soil': res.get('soil')},
        'robot': {'platform': 'go2w', 'total_mass_kg': res.get('total_mass_kg'),
                  'gravity_mps2': 1.62},
        'cycle': {'phases': ['stand', 'shift_support', 'small_lift', 'hold',
                             'lower_until_contact', 'load_transfer', 'return_body'],
                  'swing': res.get('swing'),
                  'hold_s': res.get('thresholds', {}).get('hold_s'),
                  'lift_target_m': 0.03,
                  'cycles': res.get('cycles_requested')},
        'thresholds': res.get('thresholds'),
        'note': '控制基础周期实验，不是 Lux3D 决策实验；payload/decision 不适用。',
    }
    (d / 'effective_config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    status = {
        'schema': 'v3-run-status/v1',
        'run_id': a.run_id,
        'status': a.status,
        'all_ok': bool(res.get('all_ok')),
        'cycles_completed': res.get('cycles_completed'),
        'terminated': res.get('terminated'),
        'errors': res.get('errors') or [],
        'finished_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    }
    (d / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2))
    print(json.dumps({'run_id': a.run_id, 'status': a.status,
                      'n_files': len(files), 'all_ok': status['all_ok']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
