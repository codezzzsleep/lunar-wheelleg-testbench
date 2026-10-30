#!/bin/bash
# V7 串行链（内存守卫）：同一时刻只跑一个重任务；单进程虚拟内存上限 5 GB。
cd /var/lib/deepseek-harness/lunar-lab || exit 1
ulimit -v 5000000
export LD_LIBRARY_PATH=/tmp/sysroot/usr/lib/x86_64-linux-gnu:/tmp/sysroot/lib/x86_64-linux-gnu
export MUJOCO_GL=osmesa
B=runs/unseen/delivery_v7/v7_20261030
declare -A OBS=( [V7_R01_tv1]=R01 [V7_R01_s1]=R01 [V7_R01_s2]=R01 \
                 [V7_R03_s1]=R03 [V7_R03_s2]=R03 \
                 [V7_R02_s1]=R02 [V7_R02_s2]=R02 [V7_R04_s1]=R04 [V7_R04_s2]=R04 )
for c in V7_R01_tv1 V7_R03_s1 V7_R01_s1 V7_R03_s2 V7_R01_s2 V7_R04_s1 V7_R02_s2 V7_R04_s2; do
  o=${OBS[$c]}
  echo "[$(date +%H:%M:%S)] start $c"
  if [ ! -f "$B/candidates/$c/align" ]; then
    timeout 1800 .venv/bin/python scripts/align24.py --candidate "$B/candidates/$c/clean/body.stl" \
      --obs "runs/unseen/recovery_r3/obs_$o" --out "$B/candidates/$c/align" --top-k 4 \
      > "$B/candidates/$c/align.log" 2>&1
  fi
  if [ ! -f "$B/processed/$c/process.json" ]; then
    timeout 2400 .venv/bin/python scripts/v7_process.py --candidate-dir "$B/candidates/$c" \
      --observation "runs/unseen/recovery_r3/obs_$o" --out "$B/processed/$c" \
      > "$B/candidates/$c/process.log" 2>&1
  fi
  echo "[$(date +%H:%M:%S)] done $c: $(tail -1 $B/candidates/$c/process.log 2>/dev/null | cut -c1-140)"
done
echo "[$(date +%H:%M:%S)] V7 chain finished"
