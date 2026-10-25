"""
月面场景构建：把 go2w 模型 + 月球重力 + 地面拼成一段 MuJoCo XML。

设计约束（来自复查意见）：
  · **不在磁盘上共享中间文件。** 旧实现每个 worker 都写同一个 moon_flat.xml，
    并发时可能读到被截断的内容。现在只返回字符串，由调用方在内存里构建模型。
  · `meshdir` 改写成绝对路径，因此 XML 不再依赖 cwd、也不必须放在 go2w 目录下。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml'
GO2W_ASSETS = SRC.parent / 'assets'

DEFAULT_GRAVITY = 1.62
DEFAULT_FRICTION = '0.9 0.02 0.001'


def model_available():
    return SRC.exists() and GO2W_ASSETS.exists()


def moon_scene_xml(gravity=DEFAULT_GRAVITY, friction=DEFAULT_FRICTION):
    """返回完整 XML 字符串（含机器人、地面、光照、月球重力）。"""
    if not model_available():
        raise FileNotFoundError(
            f'找不到 go2w 模型：{SRC}\n'
            '请先运行 setup.sh，或按 README「获取机器人模型」一节拉取固定提交。')
    xml = SRC.read_text()
    # 绝对 meshdir：XML 不再依赖工作目录
    xml = xml.replace('meshdir="assets"', f'meshdir="{GO2W_ASSETS}"')
    xml, n = re.subn(r'<option([^>]*?)/>',
                     rf'<option\1 gravity="0 0 -{gravity}"/>', xml, count=1)
    assert n == 1, 'go2w.xml 里没有找到 <option>，模型可能已变更'
    floor = (
        '\n    <light pos="0 0 3" dir="0 0 -1" directional="true" diffuse="0.7 0.7 0.7"/>'
        f'\n    <geom name="lunar_ground" type="plane" size="0 0 0.05"'
        f' friction="{friction}" rgba=".28 .28 .32 1"/>'
    )
    xml, n = re.subn(r'<worldbody>', '<worldbody>' + floor, xml, count=1)
    assert n == 1, 'go2w.xml 里没有找到 <worldbody>'
    return xml


if __name__ == '__main__':
    import mujoco
    m = mujoco.MjModel.from_xml_string(moon_scene_xml())
    print(f'model ok: nq={m.nq} nu={m.nu} ngeom={m.ngeom} gravity={m.opt.gravity}')
