#!/bin/bash
# 最小演示包完整运行：校验 → 重建 → 验收 → 新预演 → 新决策 → 独立真值执行 → 回放
# 用法：在仓库根目录执行  bash demo/r1_r03_two_view/run_demo.sh [输出目录]
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PACK="$REPO/demo/r1_r03_two_view"
OUT="${1:-$PACK/run_demo}"
PY="${PY:-python3}"
export MUJOCO_GL="${MUJOCO_GL:-osmesa}"
mkdir -p "$OUT"
cd "$REPO"

echo "== 1 输入校验"
for f in inputs/occ_two_view.npz inputs/parent/body.stl inputs/truth_collision/manifest.json \
         inputs/obs_first/observation.json inputs/obs_second/observation.json \
         inputs/collision_manifest.json; do
  [ -e "$PACK/$f" ] || { echo "缺输入: $f"; exit 2; }
done
echo "   ok"

echo "== 2 从占据重建候选与碰撞"
$PY scripts/v7_rebuild_from_occ.py --occ "$PACK/inputs/occ_two_view.npz" --out "$OUT/rebuilt"
$PY scripts/collision_box_union.py --occupancy "$PACK/inputs/occ_two_view.npz" \
   --out "$OUT/rebuilt/collision" --pitch 0.0025 --hypothesis-id demo

echo "== 3 验收（与包内 acceptance 对照）"
$PY scripts/collision_occupancy_metrics.py --mesh "$OUT/rebuilt/body.stl" \
   --collision "$OUT/rebuilt/collision" --out "$OUT/rebuilt/collision/metrics.json" --parity full

echo "== 4 新预演 + 新决策 + 独立真值执行"
echo "[{\"id\": \"demo_candidate\", \"world\": \"$OUT/rebuilt\", \"collision\": \"$OUT/rebuilt/collision\"}]" > "$OUT/hyp.json"
$PY scripts/v7_same_scene_formal.py --case cases/unseen_v1/R03.json \
   --hypotheses "$OUT/hyp.json" --truth-collision "$PACK/inputs/truth_collision" \
   --out "$OUT/run"

echo "== 5 回放"
$PY scripts/v7_player.py --traj "$OUT/run/same_scene_report.json" --out "$OUT/run/player.html" 2>/dev/null || \
  echo "   （该报告无逐帧轨迹，跳过播放器；见 run/same_scene_report.json）"
echo "== 完成：$OUT"
