#!/bin/sh
# 幂等 bootstrap：建 venv、装锁定依赖、校验版本。CNB 的 script 用 sh 执行。
set -e
cd "$(dirname "$0")/.."

# 沙箱里直接用镜像的 /opt/lunar 解释器（venv-of-venv 的 --system-site-packages 不会链到它）
if [ -x /opt/lunar/bin/python ]; then
  PATH="/opt/lunar/bin:$PATH"; export PATH
fi
python3 -c "import mujoco" 2>/dev/null || {
  echo "镜像解释器没有 mujoco：尝试在仓库内装依赖"
  python3 -m venv .venv
  if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi
  python -m pip install -q -r requirements.txt
}

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
