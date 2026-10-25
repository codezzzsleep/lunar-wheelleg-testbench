"""
生成可用的月面考场 XML：go2w + 月球重力 + 平面地面。

为什么要"拼"而不是直接 include scene.xml：
  · go2w.xml 只有机器人，没有地面（地面在 scene.xml 里）
  · go2w.xml 已有一个 <option>，再 include 一份 <option> 会重复定义
所以直接在原文件文本上注入重力与地面，产物写回同目录，meshdir="assets" 才能解析。
"""
import pathlib, re, sys

SRC = pathlib.Path('vendor/unitree_mujoco/unitree_robots/go2w/go2w.xml')
DST = SRC.parent / 'moon_flat.xml'
G = 1.62


def build(gravity=G, friction='0.9 0.02 0.001', out=DST):
    xml = SRC.read_text()

    # 1) lunar gravity on the existing <option>
    xml, n = re.subn(r'<option([^>]*?)/>',
                     rf'<option\1 gravity="0 0 -{gravity}"/>', xml, count=1)
    assert n == 1, 'option tag not found'

    # 2) floor + light, injected at the top of worldbody
    inject = (
        '\n    <light pos="0 0 3" dir="0 0 -1" directional="true" diffuse="0.7 0.7 0.7"/>'
        f'\n    <geom name="lunar_ground" type="plane" size="0 0 0.05"'
        f' friction="{friction}" rgba=".28 .28 .32 1"/>'
    )
    xml, n = re.subn(r'<worldbody>', '<worldbody>' + inject, xml, count=1)
    assert n == 1, 'worldbody not found'

    out.write_text(xml)
    return out


if __name__ == '__main__':
    p = build()
    print('wrote', p)
    import mujoco
    m = mujoco.MjModel.from_xml_path(str(p))
    print('gravity', m.opt.gravity, '| ngeom', m.ngeom, '| nq', m.nq, '| nu', m.nu)
    names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) for i in range(m.ngeom)]
    print('has ground:', any(x == 'lunar_ground' for x in names))
