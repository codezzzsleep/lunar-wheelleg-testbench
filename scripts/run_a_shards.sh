#!/bin/sh
cd /workspace/work/lunar-lab
python3 - <<'PY'
s=open('runs/v5/a_states.txt').read().strip().split(',')
for i in range(4):
    open(f'/tmp/a_g{i}.txt','w').write(','.join(s[i::4]))
PY
for i in 0 1 2 3; do
  st=$(cat /tmp/a_g$i.txt)
  rm -f /tmp/a_g$i.log /tmp/a_g$i.exit
  nohup sh -c "MUJOCO_GL=egl python3 -u scripts/v5_a_r3.py --states '$st' --out runs/v5/a_r3/shard$i > /tmp/a_g$i.log 2>&1; echo \$? > /tmp/a_g$i.exit" >/dev/null 2>&1 &
  echo $! > /tmp/a_g$i.pid
done
sleep 20
tail -2 /tmp/a_g0.log
