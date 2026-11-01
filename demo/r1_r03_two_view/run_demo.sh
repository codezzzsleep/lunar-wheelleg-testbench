#!/bin/bash
# 最小演示包完整运行（收口整改 §8）：
#   校验内容身份 → 重建占据派生网格与碰撞 → 复测资格 → 新预演 → 新决策
#   → 独立真值执行 → 实际轨迹 → 连续回放
# 任何一步缺失都**非零退出**，不允许"跳过回放仍打印完成"。
#
# 用法：bash demo/r1_r03_two_view/run_demo.sh [输出目录]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PACK="$REPO/demo/r1_r03_two_view"
OUT="${1:-$PACK/run_demo}"
PY="${PY:-python3}"
export MUJOCO_GL="${MUJOCO_GL:-osmesa}"
mkdir -p "$OUT"
cd "$REPO"

fail() { echo "DEMO_FAILED: $*" >&2; exit 1; }

echo "== 0 代码与模型依赖"
CODE_SHA="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
ROBOT="$REPO/vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml"
[ -f "$ROBOT" ] || fail "缺机器人模型 $ROBOT（先运行 setup.sh）"
echo "   code=$CODE_SHA robot=ok"

echo "== 1 输入校验（含内容身份）"
for f in inputs/occ_two_view.npz inputs/parent/body.stl inputs/truth_collision/manifest.json \
         inputs/obs_first/observation.json inputs/obs_second/observation.json \
         inputs/collision_manifest.json inputs/case.json; do
  [ -e "$PACK/$f" ] || fail "缺输入 $f"
done
$PY - "$PACK" <<'PY' || fail "输入身份与 MANIFEST 不符"
import json, hashlib, pathlib, sys
pack = pathlib.Path(sys.argv[1])
man = json.loads((pack / 'MANIFEST.json').read_text())
bad = []
for it in man.get('items', []):
    p = pack / it['path']
    if not p.exists():
        bad.append(f"缺 {it['path']}")
        continue
    if p.is_file() and it.get('sha256'):
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if not h.startswith(it['sha256'][:16]) and h != it['sha256']:
            bad.append(f"哈希不符 {it['path']}")
if bad:
    print('; '.join(bad)); sys.exit(1)
print(f"   {len(man.get('items', []))} 项输入身份通过")
PY

echo "== 2 从占据重建网格与碰撞（不重新生成）"
echo "[{\"id\": \"demo_candidate\", \"world\": \"$OUT/rebuilt\", \"collision\": \"$OUT/rebuilt/collision\"}]" > "$OUT/hyp.json"
$PY scripts/v7_rebuild_from_occ.py --occ "$PACK/inputs/occ_two_view.npz" --out "$OUT/rebuilt" || fail "重建失败"
$PY scripts/collision_box_union.py --occupancy "$PACK/inputs/occ_two_view.npz" \
   --out "$OUT/rebuilt/collision" --pitch 0.0025 --hypothesis-id demo || fail "碰撞重建失败"

echo "== 3 复测资格（可见 + 碰撞 + 身份，唯一门）"
$PY scripts/collision_occupancy_metrics.py --mesh "$OUT/rebuilt/body.stl" \
   --collision "$OUT/rebuilt/collision" --out "$OUT/rebuilt/collision/metrics_full.json" \
   --label demo --parity full || fail "碰撞测量失败"

echo "== 4 新预演 + 新决策 + 独立真值执行（生产执行器落盘轨迹）"
$PY scripts/v7_same_scene_formal.py --case "$PACK/inputs/case.json" \
   --hypotheses "$OUT/hyp.json" --truth-collision "$PACK/inputs/truth_collision" \
   --out "$OUT/run" --budget 30 --exec-soil nominal || fail "闭环执行失败"
TRAJ="$OUT/run/trajectory.jsonl"
[ -s "$TRAJ" ] || fail "执行未落盘轨迹（$TRAJ）"

echo "== 5 连续回放（缺失即失败）"
$PY scripts/v7_player.py --traj "$TRAJ" --out "$OUT/run/player.html" \
   --title "R03 两视角 演示包" || fail "播放器生成失败"
[ -s "$OUT/run/player.html" ] || fail "播放器文件为空"

echo "== 6 证据汇总"
$PY - "$OUT" "$CODE_SHA" <<'PY' || fail "证据汇总失败"
import json, pathlib, sys
out = pathlib.Path(sys.argv[1]); code = sys.argv[2]
rep = json.loads((out / 'run' / 'same_scene_report.json').read_text())
traj = (out / 'run' / 'trajectory.jsonl').read_text().strip().splitlines()
summary = {
    'schema': 'demo-run/v2', 'code_sha': code,
    'decision': (rep.get('decision') or {}).get('chosen'),
    'decision_sha': (rep.get('decision') or {}).get('decision_sha'),
    'cells': (rep.get('decision') or {}).get('cells'),
    'execution': rep.get('execution'),
    'trajectory': rep.get('trajectory'), 'trajectory_frames': len(traj),
    'player': str((out / 'run' / 'player.html')),
    'truth_identity': rep.get('truth_identity'),
    'observation_acceptance': rep.get('observation_acceptance'),
    'note': '本目录由演示包完整运行产生：重建→资格→预演→决策→真值执行→轨迹→回放。',
}
(out / 'demo_run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(json.dumps({k: summary[k] for k in ('decision', 'trajectory_frames', 'player')},
                 ensure_ascii=False))
PY

echo "== 完成：$OUT"
