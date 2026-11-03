#!/bin/bash
# 生产自检套件：碰撞缓存身份 + 预演保真。任一失败返回非零。
set -e
cd /workspace/lunar-lab
echo "== collision cache identity =="
/opt/lunar/bin/python scripts/v3_selftest_collision.py
echo "== rehearsal fidelity (same_scene vs project) =="
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_selftest_fidelity.py
echo "== all selftests passed =="
