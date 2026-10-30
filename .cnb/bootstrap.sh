#!/bin/sh
# 幂等 bootstrap：建 venv、装锁定依赖、校验版本。CNB 的 script 用 sh 执行。
set -e
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; else PATH="$PWD/.venv/bin:$PATH"; export PATH; fi

# 依赖在镜像里已装好；venv 里补一份，保证仓库自带环境可独立运行
python -m pip install -q --upgrade pip
if [ -f requirements.txt ]; then
  python -m pip install -q -r requirements.txt
fi
python - <<'PY'
import json, pathlib, sys
from importlib import metadata

req = {}
for line in pathlib.Path('requirements.txt').read_text().splitlines():
    line = line.split('#')[0].strip()
    if '==' in line:
        k, v = line.split('==')
        req[k.strip()] = v.strip()

bad = []
for name, want in req.items():
    try:
        got = metadata.version(name)
    except metadata.PackageNotFoundError:
        bad.append(f'{name}: 未安装（期望 {want}）')
        continue
    if got != want:
        bad.append(f'{name}: 期望 {want} 实际 {got}')
print(json.dumps({'checked': len(req), 'mismatch': bad}, ensure_ascii=False))
sys.exit(1 if bad else 0)
PY

echo "bootstrap ok"
