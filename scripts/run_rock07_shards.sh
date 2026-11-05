#!/bin/sh
cd /workspace/work/lunar-lab
for spec in "rock_07_h1v0 0.60,0.70 r1" "rock_07_h1v0 0.80,0.90 r2" "rock_07_h1v1 0.60,0.70 r3" "rock_07_h1v1 0.80,0.90 r4"; do
  set -- $spec
  st=$1; ch=$2; tag=$3
  mkdir -p runs/v5/a_r3/$tag
  rm -f /tmp/$tag.log /tmp/$tag.exit
  nohup sh -c "MUJOCO_GL=egl python3 -u scripts/v5_a_r3.py --states $st --channels $ch --out runs/v5/a_r3/$tag > /tmp/$tag.log 2>&1; echo \$? > /tmp/$tag.exit" >/dev/null 2>&1 &
  echo $! > /tmp/$tag.pid
done
sleep 5
echo launched
