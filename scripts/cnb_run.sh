#!/usr/bin/env bash
# 在 CNB 沙箱里跑 R1 收尾任务（一条命令：起环境 → 同步 → 跑 → 回传）。
#
#   CNB_TOKEN=... bash scripts/cnb_run.sh --repo ycyc755/lunar-lab-r1 --branch main
#
# 设计要点：
#   · 全程持有一条 SSH 会话（`ssh ... 'while true; do sleep 60; done'`），否则工作区
#     在无活动连接 10–12 分钟后被回收，后台任务一起消失；
#   · 代码用 tar 管道同步，不依赖 GitHub 可达；
#   · 远端任务用 setsid nohup 跑，结果目录回传后再退出。
set -uo pipefail

REPO="${CNB_REPO:-ycyc755/lunar-lab-r1}"
BRANCH="${CNB_BRANCH:-main}"
API="https://api.cnb.cool"
TOKEN="${CNB_TOKEN:?需要 CNB_TOKEN}"
LOCAL="$(cd "$(dirname "$0")/.." && pwd)"
LOG=/tmp/cnb_run.log

say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

api() { curl -s -H "Authorization: Bearer $TOKEN" -H 'Accept: application/vnd.cnb.api+json' "$@"; }

say "启动工作区 $REPO@$BRANCH"
START=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Accept: application/vnd.cnb.api+json' \
        -H 'Content-Type: application/json' -d "{\"branch\":\"$BRANCH\"}" \
        "$API/$REPO/-/workspace/start")
SN=$(printf '%s' "$START" | grep -o '"sn":"[^"]*"' | head -1 | cut -d'"' -f4)
[ -n "$SN" ] || { echo "启动失败：$START"; exit 1; }
say "sn=$SN；等待 running"
for i in $(seq 1 60); do
  ST=$(api "$API/workspace/list" | grep -o "\"sn\":\"$SN\"[^}]*\"status\":\"[a-z]*\"" | grep -o '"status":"[a-z]*"' | cut -d'"' -f4)
  [ "$ST" = "running" ] && break
  sleep 10
done
[ "$ST" = "running" ] || { echo "工作区未就绪（status=$ST）"; exit 1; }

DETAIL=$(api "$API/$REPO/-/workspace/detail/$SN")
SSH_HOST=$(printf '%s' "$DETAIL" | grep -o '"remoteSsh":"[^"]*"' | cut -d'"' -f4)
[ -n "$SSH_HOST" ] || { echo "拿不到 remoteSsh：$DETAIL"; exit 1; }
say "SSH: $SSH_HOST"

SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=100000"
# 保活：这条会话一断，工作区就开始计时回收
setsid nohup ssh $SSH_OPTS "$SSH_HOST" 'while true; do sleep 60; done' \
  > /tmp/cnb_keepalive.log 2>&1 < /dev/null &
KEEP=$!
trap 'kill $KEEP 2>/dev/null' EXIT
sleep 5

say "同步代码（不含 runs/.git/.venv）"
tar -C "$LOCAL" -cf - --exclude=.git --exclude=runs --exclude=.venv . 2>/dev/null \
  | ssh $SSH_OPTS "$SSH_HOST" 'mkdir -p /workspace/lunar-lab && cd /workspace/lunar-lab && tar -xf -'

say "远端：补齐依赖并在后台跑任务"
ssh $SSH_OPTS "$SSH_HOST" 'bash -s' <<'REMOTE' 2>&1 | tee -a $LOG
set -u
cd /workspace/lunar-lab || exit 1
/opt/lunar/bin/python -c "import rtree" 2>/dev/null || /opt/lunar/bin/pip install -q rtree
export MUJOCO_GL=osmesa
/opt/lunar/bin/python scripts/run_r1.py --audit || echo "(audit 有缺失项属正常：证据包未全同步)"
nohup setsid bash -lc '
  cd /workspace/lunar-lab
  export MUJOCO_GL=osmesa
  /opt/lunar/bin/python scripts/v7_update_two_views.py \
     --obs1 runs/unseen/recovery_r3/obs_R03 \
     --obs2 runs/unseen/delivery_v7/v7_20261030_r1/observation/obs_R03_at_driven \
     --parent runs/unseen/delivery_v7/v7_20261030/candidates/V7_R03_s1/world/align \
     --parent-id V7_R03_s1 --pitch 0.0025 \
     --out runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/tv_R03_s1
' > /tmp/tv.log 2>&1 < /dev/null &
echo "远端任务已起：tail /tmp/tv.log"
REMOTE

say "等待两视角更新（最多 40 分钟）"
for i in $(seq 1 80); do
  OUT=$(ssh $SSH_OPTS "$SSH_HOST" 'cat /tmp/tv.log 2>/dev/null | tail -2; ls /workspace/lunar-lab/runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/tv_R03_s1/update_report.json 2>/dev/null')
  printf '%s\n' "$OUT" | grep -q update_report.json && { say "完成"; break; }
  sleep 30
done

say "回传结果"
ssh $SSH_OPTS "$SSH_HOST" 'cd /workspace/lunar-lab && tar -cf - runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/tv_R03_s1 2>/dev/null' \
  | tar -C "$LOCAL" -xf - 2>/dev/null

say "结束；结果在 $LOCAL/runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/tv_R03_s1"
say "工作区 $SN 仍在运行；要停：curl -X POST -H \"Authorization: Bearer \$CNB_TOKEN\" -d '{\"sn\":\"$SN\"}' $API/workspace/stop"
