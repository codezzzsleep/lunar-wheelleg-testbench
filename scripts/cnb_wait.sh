#!/usr/bin/env bash
# 等待沙箱里的远端任务结束，并把产物回传本地。
#
# 用法：bash scripts/cnb_wait.sh <remote-pattern> <remote-path> <local-dest> [timeout-min]
#   remote-pattern : 远端 pgrep 的模式，例如 "v7_measure_candidate"
#   remote-path    : 远端要回传的文件或目录
#   local-dest     : 本地目标路径
#
# 设计要点：沙箱里的后台进程不会唤醒 DSH，所以这个脚本必须由**本地后台作业**调用，
# 它自己阻塞等待，结束时本地作业完成 -> 才有通知。
set -uo pipefail

PATTERN="${1:?需要远端进程模式}"
REMOTE_PATH="${2:?需要远端产物路径}"
LOCAL_DEST="${3:?需要本地目标路径}"
TIMEOUT_MIN="${4:-90}"
SSH_HOST="${CNB_SSH:?需要 CNB_SSH，例如 user@cnb.space}"

SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15"
deadline=$(( $(date +%s) + TIMEOUT_MIN * 60 ))
while :; do
  running=$(ssh $SSH_OPTS "$SSH_HOST" "pgrep -c -f '$PATTERN' 2>/dev/null || true" 2>/dev/null | tr -d '\r\n ')
  exists=$(ssh $SSH_OPTS "$SSH_HOST" "test -e '$REMOTE_PATH' && echo yes || echo no" 2>/dev/null | tr -d '\r\n ')
  if [ "${running:-0}" = "0" ] && [ "$exists" = "yes" ]; then
    echo "远端任务已结束，回传 $REMOTE_PATH"
    mkdir -p "$(dirname "$LOCAL_DEST")"
    scp -q -r $SSH_OPTS "$SSH_HOST:$REMOTE_PATH" "$LOCAL_DEST" && echo "回传完成 -> $LOCAL_DEST"
    exit 0
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "超时 ${TIMEOUT_MIN} 分钟：远端 running=$running exists=$exists"
    exit 2
  fi
  sleep 30
done
