"""v3 唯一入口：按阶段串起流水线（SPEC §13）。

  python scripts/run_v3.py --protocol plans/v3_protocol.json --stage assets
  python scripts/run_v3.py --protocol plans/v3_protocol.json --stage screen --resume
  ... stage ∈ assets / screen / inputs / generate / register / fuse / evaluate /
              observe / media / package

断点有效性由内容身份决定：每个阶段自己检查输入 SHA 与产物 manifest，
--resume 只跳过身份匹配的单元，不重跑已确认的产物，也不重复付费生成。
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
STAGES = ['assets', 'screen', 'inputs', 'generate', 'register', 'fuse', 'evaluate',
          'observe', 'media', 'package']


def run(cmd, **kw):
    print('$', ' '.join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], cwd=str(ROOT), **kw)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--stage', required=True, choices=STAGES + ['all'])
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--states', default='all')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--extra', nargs=argparse.REMAINDER, default=[])
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    if a.stage in ('assets', 'all'):
        rc = run([PY, 'scripts/v3_fetch_rocks.py', '--plan', proto['assets']['source_pool']])
        if rc != 0:
            return rc
        rc = run([PY, 'scripts/v3_assets.py', '--sources', proto['assets']['source_pool'],
                  '--targets', ','.join(str(x) for x in proto['assets']['levels_hr']),
                  '--wheel-radius', str(proto['assets']['wheel_radius_m'])])
        if rc != 0:
            return rc
    if a.stage in ('inputs', 'all'):
        rc = run([PY, 'scripts/v3_obs.py', '--protocol', a.protocol,
                  '--states', 'all', '--out', 'runs/v3'])
        if rc != 0:
            return rc
    if a.stage in ('screen', 'all'):
        rc = run([PY, 'scripts/v3_screen.py', '--protocol', a.protocol,
                  '--states', 'all', '--workers', str(a.workers)])
        if rc != 0:
            return rc
    if a.stage in ('generate', 'all'):
        rc = run([PY, 'scripts/v3_make_tasks.py', '--protocol', a.protocol,
                  '--out', 'runs/v3/generation/tasks.json'])
        if rc != 0:
            return rc
        rc = run([PY, 'scripts/v3_generate.py', '--tasks', 'runs/v3/generation/tasks.json',
                  '--submit', '--workers', str(a.workers)])
        if rc != 0:
            return rc
    if a.stage in ('register', 'fuse', 'evaluate', 'all'):
        stage = 'all' if a.stage == 'all' else a.stage
        rc = run([PY, 'scripts/v3_state.py', '--state' if False else '--states', 'all',
                  '--protocol', a.protocol, '--tasks', 'runs/v3/generation/tasks.json',
                  '--stage', stage, '--workers', str(a.workers)])
        if rc != 0:
            return rc
    if a.stage in ('observe', 'all'):
        rc = run([PY, 'scripts/v3_look_again.py', '--protocol', a.protocol,
                  '--workers', str(a.workers)])
        if rc != 0:
            return rc
    if a.stage in ('media', 'all'):
        rc = run([PY, 'scripts/v3_media.py', '--protocol', a.protocol])
        if rc != 0:
            return rc
    if a.stage in ('package', 'all'):
        rc = run([PY, 'scripts/v3_package.py', '--protocol', a.protocol])
        if rc != 0:
            return rc
    return 0


if __name__ == '__main__':
    sys.exit(main())
