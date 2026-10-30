#!/bin/sh
# 烟测：MuJoCo 能建模 + OSMesa 能出图 + 仓库脚本可导入
set -e
cd "$(dirname "$0")/.."
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; else PATH="$PWD/.venv/bin:$PATH"; export PATH; fi
export MUJOCO_GL=osmesa

python - <<'PY'
import numpy as np, mujoco
xml = '<mujoco><worldbody><geom type="box" size=".1 .1 .1" pos="0 0 .05"/></worldbody></mujoco>'
m = mujoco.MjModel.from_xml_string(xml)
d = mujoco.MjData(m)
mujoco.mj_forward(m, d)
r = mujoco.Renderer(m, 64, 64)
r.update_scene(d)
img = r.render()
print('render', img.shape, img.dtype, int(img.sum()))
assert img.shape == (64, 64, 3) and img.sum() > 0, 'OSMesa 渲染为空'
PY

python - <<'PY'
import sys, pathlib
sys.path.insert(0, str(pathlib.Path('scripts').resolve()))
import terrain, wheelleg_env, runner, skills
print('imports ok', terrain.__name__, wheelleg_env.__name__, runner.__name__, skills.__name__)
PY
echo "smoke ok"
