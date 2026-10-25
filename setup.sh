#!/usr/bin/env bash
# 干净环境安装入口。只用这里列出的步骤，不依赖作者机器上的临时目录。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
MUJOCO_COMMIT="1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d"

echo "== 1/4 虚拟环境 =="
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip

echo "== 2/4 Python 依赖（锁定版本） =="
python -m pip install -q -r requirements.txt

echo "== 3/4 机器人模型（固定提交） =="
if [ ! -d vendor/unitree_mujoco ]; then
  mkdir -p vendor
  git clone -q https://github.com/unitreerobotics/unitree_mujoco vendor/unitree_mujoco
fi
git -C vendor/unitree_mujoco fetch -q --depth 1 origin "$MUJOCO_COMMIT" || true
git -C vendor/unitree_mujoco checkout -q "$MUJOCO_COMMIT" 2>/dev/null || \
  echo "警告：无法切到固定提交，当前为 $(git -C vendor/unitree_mujoco rev-parse --short HEAD)"

echo "== 4/4 验收 =="
python scripts/gate1.py --out "runs/gate1_$(date +%Y%m%d_%H%M%S)"

cat <<'TIP'

安装完成。常用命令：
  python scripts/demo.py --suite smoke --out runs/smoke     # 冒烟（约 20 trial）
  python scripts/demo.py --suite canonical --out runs/canonical
  python scripts/analyze.py --input runs/canonical/results.jsonl --out runs/canonical

离屏渲染（可选）：
  apt-get install -y libosmesa6
  export MUJOCO_GL=osmesa
  python scripts/replay.py --run runs/canonical --trial <trial_id>
TIP
