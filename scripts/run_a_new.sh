#!/bin/sh
cd /workspace/work/lunar-lab
mkdir -p runs/v5/a_r3/new1 runs/v5/a_r3/new2 runs/v5/a_r3/new3 runs/v5/a_r3/new4
rm -f /tmp/n1.log /tmp/n1.exit; nohup sh -c "MUJOCO_GL=egl python3 -u scripts/v5_a_r3.py --states moon_rock_05_h1v1,moon_rock_05_h2v0 --out runs/v5/a_r3/new1 > /tmp/n1.log 2>&1; echo \$? > /tmp/n1.exit" >/dev/null 2>&1 & echo $! > /tmp/n1.pid
rm -f /tmp/n2.log /tmp/n2.exit; nohup sh -c "MUJOCO_GL=egl python3 -u scripts/v5_a_r3.py --states moon_rock_06_h1v0,moon_rock_06_h1v1 --out runs/v5/a_r3/new2 > /tmp/n2.log 2>&1; echo \$? > /tmp/n2.exit" >/dev/null 2>&1 & echo $! > /tmp/n2.pid
rm -f /tmp/n3.log /tmp/n3.exit; nohup sh -c "MUJOCO_GL=egl python3 -u scripts/v5_a_r3.py --states moon_rock_06_h2v1,moon_rock_07_h2v0 --out runs/v5/a_r3/new3 > /tmp/n3.log 2>&1; echo \$? > /tmp/n3.exit" >/dev/null 2>&1 & echo $! > /tmp/n3.pid
rm -f /tmp/n4.log /tmp/n4.exit; nohup sh -c "MUJOCO_GL=egl python3 -u scripts/v5_a_r3.py --states rock_07_h1v0,rock_07_h1v1 --out runs/v5/a_r3/new4 > /tmp/n4.log 2>&1; echo \$? > /tmp/n4.exit" >/dev/null 2>&1 & echo $! > /tmp/n4.pid
sleep 20
tail -2 /tmp/n1.log
