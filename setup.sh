#!/usr/bin/env bash
# 干净环境安装入口。
#
# 约定：**后续所有命令都用 .venv/bin/python**，不依赖 source activate 传播到你的终端。
# 任何一步失败都以非零退出，不会"警告后继续"。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
VENV="$ROOT/.venv"
PY_BIN="$VENV/bin/python"
MUJOCO_COMMIT="1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d"

die() { echo "错误：$*" >&2; exit 1; }

echo "== 0/5 检查 Python =="
"$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' \
  || die "需要 Python 3.12，当前为 $("$PY" -V 2>&1)。可用 PYTHON=/path/to/python3.12 ./setup.sh 指定。"

echo "== 1/5 虚拟环境 =="
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
[ -x "$PY_BIN" ] || die "虚拟环境创建失败：找不到 $PY_BIN"
"$PY_BIN" -m pip install -q --upgrade pip

echo "== 2/5 Python 依赖（锁定版本） =="
"$PY_BIN" -m pip install -q -r requirements.txt
"$PY_BIN" - <<'PY'
import importlib.metadata as md, sys
want = {'mujoco': '3.17.0', 'numpy': '2.5.4', 'trimesh': '5.2.0',
        'coacd': '1.0.14', 'manifold3d': '3.5.4', 'pillow': '13.0.0'}
bad = [f'{k}: 期望 {v}, 实际 {md.version(k)}' for k, v in want.items() if md.version(k) != v]
if bad:
    print('依赖版本不符：', *bad, sep='\n  '); sys.exit(1)
print('依赖版本校验通过')
PY

echo "== 3/5 机器人模型（固定提交） =="
VENDOR="$ROOT/vendor/unitree_mujoco"
if [ ! -d "$VENDOR" ]; then
  mkdir -p "$ROOT/vendor"
  git clone -q https://github.com/unitreerobotics/unitree_mujoco "$VENDOR" \
    || die "克隆 unitree_mujoco 失败（网络？）"
fi
if [ -n "$(git -C "$VENDOR" status --porcelain 2>/dev/null)" ]; then
  die "vendor/unitree_mujoco 存在未提交修改，为避免覆盖已停止。
     请先提交或移走这些修改（git -C vendor/unitree_mujoco status 查看）。"
fi
if ! git -C "$VENDOR" cat-file -e "${MUJOCO_COMMIT}^{commit}" 2>/dev/null; then
  git -C "$VENDOR" fetch -q origin "$MUJOCO_COMMIT" \
    || die "无法获取固定提交 $MUJOCO_COMMIT（网络或仓库变更）"
fi
git -C "$VENDOR" checkout -q "$MUJOCO_COMMIT" \
  || die "无法切换到固定提交 $MUJOCO_COMMIT"
GOT="$(git -C "$VENDOR" rev-parse HEAD)"
[ "$GOT" = "$MUJOCO_COMMIT" ] || die "模型提交校验失败：期望 $MUJOCO_COMMIT，实际 $GOT"

echo "== 4/5 第 1 关验收 =="
STAMP="$(date +%Y%m%d_%H%M%S)"
"$PY_BIN" scripts/gate1.py --out "runs/gate1_$STAMP" \
  || die "第 1 关验收未通过，安装未完成"

echo "== 5/5 完成 =="
cat <<TIP

安装完成。请直接复制下面命令（不需要 source activate）：

  .venv/bin/python -m unittest discover -s tests -v
  .venv/bin/python scripts/demo.py --suite smoke     --out runs/smoke_$STAMP
  .venv/bin/python scripts/demo.py --suite canonical --out runs/canonical_$STAMP
  .venv/bin/python scripts/analyze.py --input runs/canonical_$STAMP/results.jsonl --out runs/canonical_$STAMP

离屏渲染（可选，仅出 GIF 时需要）：
  apt-get install -y libosmesa6
  MUJOCO_GL=osmesa .venv/bin/python scripts/replay.py --run runs/canonical_$STAMP --trial <trial_id>
TIP
