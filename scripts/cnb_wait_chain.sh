#!/usr/bin/env bash
# 等待沙箱里的 chain.sh 结束（日志出现 CHAIN DONE），把结果回传并打印摘要。
# 必须由**本地后台作业**启动：沙箱里的进程不会唤醒 DSH，只有本地作业完成才有通知。
set -uo pipefail
SSH_HOST="${CNB_SSH:?需要 CNB_SSH}"
LOG="${1:-/tmp/chain.log}"
TIMEOUT_MIN="${2:-120}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15"
deadline=$(( $(date +%s) + TIMEOUT_MIN * 60 ))
while :; do
  out=$(ssh $SSH_OPTS "$SSH_HOST" "tail -1 '$LOG' 2>/dev/null; pgrep -c -f chain.sh 2>/dev/null || true" 2>/dev/null)
  last=$(printf '%s' "$out" | head -1)
  running=$(printf '%s' "$out" | tail -1 | tr -d '\r\n ')
  case "$last" in
    *"CHAIN DONE"*) echo "远端链路完成：$last"; break ;;
  esac
  if [ "${running:-0}" = "0" ] && [ "$(date +%s)" -ge "$deadline" ]; then
    echo "超时：chain.sh 已不在运行，最后一行=$last"; exit 2
  fi
  [ "$(date +%s)" -ge "$deadline" ] && { echo "超时 ${TIMEOUT_MIN} 分钟，最后一行=$last"; exit 2; }
  sleep 30
done
mkdir -p /tmp/chain_pull
for p in \
  runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/occ_R03_s1/collision/metrics_occ.json \
  runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/occ_R03_s1/visible_occ.json \
  runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/occ_R02_s2/occ.npz \
  runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/occ_R02_s2/collision/metrics_occ.json ; do
  scp -q $SSH_OPTS "$SSH_HOST:/workspace/lunar-lab/$p" "/tmp/chain_pull/$(basename $p)" 2>/dev/null \
    && echo "回传 $(basename $p)" || echo "未取到 $p"
done
for f in /tmp/chain_pull/*.json; do
  [ -f "$f" ] || continue
  echo "== $(basename $f)"; head -c 400 "$f"; echo
done
