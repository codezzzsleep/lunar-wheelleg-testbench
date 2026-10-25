"""
几何碰撞对照：同一孔洞，原始闭合网格被当成凸包（孔被盖上），CoACD 拆块后孔真实存在。

作为可复用函数导出 `run_check()`，返回结构化结果；
不再把中间文件写到固定路径，调用方直接拿返回值判断，杜绝"读到旧文件判通过"。
"""
import json
import pathlib
import tempfile
import time

import coacd
import mujoco
import numpy as np
import trimesh

BALL_R = 0.02
BLOCKED_Z = 0.25   # 小球停在网格中心上方即视为被挡住


def _scene_xml(part_files):
    assets, geoms = [], []
    for i, f in enumerate(part_files):
        assets.append(f'<mesh name="p{i}" file="{f}"/>')
        geoms.append(f'<geom type="mesh" mesh="p{i}" mass="0.1" rgba=".7 .6 .5 1"/>')
    return f"""
    <mujoco>
      <option gravity="0 0 -1.62" timestep="0.002"/>
      <worldbody>
        <geom type="plane" size="3 3 .1" rgba=".2 .2 .25 1"/>
        <body name="obstacle" pos="0 0 0.30">{''.join(geoms)}</body>
        <body pos="0 0 0.70"><freejoint/>
          <geom type="sphere" size="{BALL_R}" mass=".05" rgba="1 .5 .2 1"/>
        </body>
      </worldbody>
      <asset>{''.join(assets)}</asset>
    </mujoco>"""


def _drop(xml, steps=2500):
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    for _ in range(steps):
        mujoco.mj_step(m, d)
    return float(d.qpos[2])


def run_check(tmpdir=None):
    """返回 {raw_final_z, raw_blocked, coacd_parts, coacd_seconds, decomposed_final_z, pass}."""
    tmp = pathlib.Path(tmpdir) if tmpdir else pathlib.Path(tempfile.mkdtemp())
    tmp.mkdir(parents=True, exist_ok=True)

    torus = trimesh.creation.torus(major_radius=0.15, minor_radius=0.035,
                                   major_segments=64, minor_segments=24)
    raw_stl = tmp / 'torus_raw.stl'
    torus.export(raw_stl)
    raw_z = _drop(_scene_xml([str(raw_stl)]))

    t0 = time.time()
    cm = coacd.Mesh(torus.vertices, torus.faces)
    parts = coacd.run_coacd(cm, threshold=0.05, max_convex_hull=32)
    coacd_s = time.time() - t0
    part_files = []
    for i, (v, f) in enumerate(parts):
        p = tmp / f'part_{i:02d}.stl'
        trimesh.Trimesh(np.asarray(v), np.asarray(f)).export(p)
        part_files.append(str(p))
    dec_z = _drop(_scene_xml(part_files))

    return {
        'torus_faces': int(len(torus.faces)),
        'torus_watertight': bool(torus.is_watertight),
        'raw_final_z': round(raw_z, 4),
        'raw_blocked': raw_z > BLOCKED_Z,
        'coacd_parts': len(parts),
        'coacd_seconds': round(coacd_s, 2),
        'decomposed_final_z': round(dec_z, 4),
        'decomposed_passes': dec_z < BLOCKED_Z,
        'pass': bool(raw_z > BLOCKED_Z and dec_z < BLOCKED_Z),
    }


if __name__ == '__main__':
    r = run_check()
    print(json.dumps(r, indent=2))
    raise SystemExit(0 if r['pass'] else 1)
