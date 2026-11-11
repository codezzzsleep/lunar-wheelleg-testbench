"""OpenGL 可用性探测，给 GL 相关测试做优雅跳过。

为什么必须走子进程：本机没有 DISPLAY/EGL 时，直接在主进程里建 `mujoco.Renderer`
往往不是抛一个可捕获的异常，而是 SIGABRT（core dump，退出码 -6/134）——那会把整个
unittest 进程杀掉，`unittest discover` 当场中断，排在后面的模块一个都跑不到。
在子进程里探测，主进程只读 returncode，永远不会被 abort 带走。

判定：子进程建一个 640×480 的 Renderer 并渲染一帧，returncode == 0 才算 GL 可用；
崩溃、超时、找不到解释器一律按不可用处理（宁可跳过，不要 core dump）。
"""
import functools
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

_PROBE = """
import mujoco
m = mujoco.MjModel.from_xml_string(
    '<mujoco><worldbody><geom type="box" size=".1 .1 .1"/></worldbody></mujoco>')
d = mujoco.MjData(m)
mujoco.mj_forward(m, d)
r = mujoco.Renderer(m, 480, 640)
r.update_scene(d)
img = r.render()
assert img.shape == (480, 640, 3), img.shape
"""


@functools.lru_cache(maxsize=1)
def gl_available():
    """GL 上下文可用 -> True。结果缓存：一次 discover 里只探一次。"""
    try:
        p = subprocess.run([sys.executable, '-c', _PROBE], cwd=str(ROOT),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0
