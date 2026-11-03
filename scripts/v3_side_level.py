"""SIDE_LEVEL 独立评估（WIP）：右侧轮子站在小垫块上，左侧在平地。

注意：当前静态垫块场景在 reset/settle 阶段会把机器人掀翻（roll −71°~−131°），
还没有得到干净评估；不要把这个脚本的输出当作 SIDE_LEVEL 通过/失败结论。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_side_level.py --out runs/v3/side_level/r1
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain            # noqa: E402
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402
import v3_climb as vc     # noqa: E402

LEG = vc.LEG


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--soil', default='rigid', choices=['rigid', 'nominal'])
    ap.add_argument('--out', default='runs/v3/side_level/r1')
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    box = trimesh.creation.box(extents=[1.0, 0.12, 0.008])
    box.apply_translation([0, 0, 0.004])
    p = str(out / 'side_block.stl')
    box.export(p)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=3.0, name='side_level',
                             objects=[{'mesh_file': p, 'x': 0.0, 'y': -0.10,
                                       'yaw_deg': 0.0}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(a.soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
    env.reset(seed=0)
    c = vc.Climb(env, 1.2, 0.015, 0.5)
    for _ in range(50):              # 让右侧落在垫块上并稳定
        c.step('settle')
    roll1, _ = vc.bc.attitude(env)
    loads1 = {leg: round(vc.contact_load(env, leg), 3) for leg in LEG}
    z1 = {leg: round(float(env.data.xpos[vc.bc.wheel_body(env, leg)][2]), 4) for leg in LEG}
    res = c.side_level(3.0)
    roll2, _ = vc.bc.attitude(env)
    loads2 = {leg: round(vc.contact_load(env, leg), 3) for leg in LEG}
    z2 = {leg: round(float(env.data.xpos[vc.bc.wheel_body(env, leg)][2]), 4) for leg in LEG}
    ok = bool(abs(np.degrees(roll2)) < 2.0 and all(v > 1.0 for v in loads2.values())
              and not env.terminated)
    outj = {'schema': 'v3-side-level/v1', 'soil': a.soil,
            'roll_before_deg': round(float(np.degrees(roll1)), 3),
            'roll_after_deg': round(float(np.degrees(roll2)), 3),
            'loads_before': loads1, 'loads_after': loads2,
            'wheel_z_before': z1, 'wheel_z_after': z2,
            'side_level': res, 'ok': ok, 'terminated': bool(env.terminated)}
    (out / 'result.json').write_text(json.dumps(outj, ensure_ascii=False, indent=2))
    print(json.dumps(outj, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
