#!/bin/bash
# 可复现运行：缓存输入 → 2.5D 重建 → 共同规划 → 决策 → 独立真值执行 → 连续回放
# 任何一步缺失即非零退出。
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PACK="$REPO/demo/r1_r02_25d"
OUT="${1:-$PACK/run}"
PY="${PY:-python3}"
export MUJOCO_GL="${MUJOCO_GL:-osmesa}"
ROBOT="$REPO/vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml"
[ -f "$ROBOT" ] || { echo "缺机器人模型 $ROBOT" >&2; exit 2; }
cd "$REPO"
"$PY" scripts/v7_repro_run.py --pack "$PACK" --out "$OUT"
echo "== 完成：$OUT"
