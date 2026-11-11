#!/usr/bin/env bash
# 在**没有 root、没有 GPU、没有 DISPLAY** 的机器上给 MuJoCo 装上软件渲染（OSMesa）。
#
# 为什么需要：本仓库的观测/回放要建 MuJoCo Renderer。没有 GL 上下文时 mujoco 不是
# 抛异常而是直接 SIGABRT（core dump），会把整个 unittest discover 杀掉。
# 2026-11-11 在本机实测：用一个 conda 环境装 `osmesa` 不可行（conda-forge 无该包），
# 但可以直接下载 Ubuntu 的 .deb 解包到本地前缀——不需要 root、不需要改系统。
#
# 用法：
#   ./scripts/setup_local_gl.sh              # 默认装到 /tmp/glroot
#   GLROOT=$HOME/.local/gl ./scripts/setup_local_gl.sh
#   source <(./scripts/setup_local_gl.sh --print-env)   # 只打印环境变量
#
# 装好后这样跑仿真：
#   source ./scripts/setup_local_gl.sh --export
#   MUJOCO_GL=osmesa python3 scripts/v8/v8_run.py --policy conservative --out runs/v8/main
#
# 注意：OSMesa（软件渲染）与 EGL（沙箱 GPU 路径）渲染出的像素**不保证逐位相同**。
# v8_lux 的复用判据是逐字节比对，因此跨后端重放会以退出码 11 停下——这是设计行为，
# 详见 docs/v8/STATUS.md 的 §3.3 与 scripts/v8/v8_replay_diff.py。

set -euo pipefail

GLROOT="${GLROOT:-/tmp/glroot}"
# libosmesa6 依赖 libLLVM.so.20.1；libglvnd/libglapi/libglx 提供 EGL/GLX 装载器；
# libgl1-mesa-dri 提供软件驱动（llvmpipe / swrast）。
PKGS=(libosmesa6 libglvnd0 libglapi-mesa libglx-mesa0 libgl1-mesa-dri libllvm20)
LIBDIR="$GLROOT/usr/lib/x86_64-linux-gnu"

print_env() {
  echo "export LD_LIBRARY_PATH=\"$LIBDIR\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}\""
  echo "export MUJOCO_GL=osmesa"
}

case "${1:-}" in
  --print-env) print_env; exit 0 ;;
  --export)    print_env; exit 0 ;;
esac

if [ -f "$LIBDIR/libOSMesa.so.8" ]; then
  echo "已存在：$LIBDIR/libOSMesa.so.8（跳过下载）。如需重装，先删 $GLROOT。"
  print_env
  exit 0
fi

command -v apt-get >/dev/null 2>&1 || { echo "错误：需要 apt-get 才能下载 .deb（不需要 root）。" >&2; exit 1; }
command -v dpkg    >/dev/null 2>&1 || { echo "错误：需要 dpkg 才能解包。" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$GLROOT"

echo "== 1/3 下载 .deb 到临时目录（不需要 root）=="
( cd "$TMP" && apt-get download "${PKGS[@]}" )

echo "== 2/3 解包到 $GLROOT =="
for d in "$TMP"/*.deb; do dpkg -x "$d" "$GLROOT"; done

echo "== 3/3 自检：建一个 64x64 的 Renderer 并渲染一帧 =="
# 解释器：优先仓库 venv（mujoco 装在那里），否则退回系统 python3。可用 PY=... 覆盖。
PY="${PY:-}"
if [ -z "$PY" ]; then
  here="$(cd "$(dirname "$0")" && pwd)"
  if [ -x "$here/../.venv/bin/python" ]; then PY="$here/../.venv/bin/python"; else PY="python3"; fi
fi
echo "   解释器：$PY"
LD_LIBRARY_PATH="$LIBDIR" MUJOCO_GL=osmesa "$PY" - <<'PY'
import mujoco
m = mujoco.MjModel.from_xml_string(
    '<mujoco><worldbody><geom type="box" size=".1 .1 .1"/></worldbody></mujoco>')
d = mujoco.MjData(m); mujoco.mj_forward(m, d)
r = mujoco.Renderer(m, 64, 64); r.update_scene(d)
img = r.render()
assert img.shape == (64, 64, 3), img.shape
print('OSMesa 渲染自检通过：', img.shape, img.dtype)
PY

echo
echo "装好了。用下面两行激活（或 source --export）："
print_env
