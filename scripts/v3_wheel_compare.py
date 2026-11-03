"""S5：同场景、同三个 S0 的纯轮式对照（关节目标保持站姿，不抬腿）。

  MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_wheel_compare.py --soil nominal --out runs/v3/stage003/s5_wheel
"""
import argparse
import hashlib
import json
import pathlib
import sys

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain            # noqa: E402
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402
import v3_climb as vc     # noqa: E402
import v3_basic_cycle as bc  # noqa: E402

LEG = bc.LEG
STANCE = {leg: dict(vc.STANCE[leg]) for leg in LEG}
FAR_X = 2.35


def build_env(soil):
    out = ROOT / 'runs/v3/stage003/_scene'
    out.mkdir(parents=True, exist_ok=True)
    box_fr = vc.make_step(out / 'step_fr.stl', h=0.05, sx=1.40, sy=0.45)
    box_fl = vc.make_step(out / 'step_fl.stl', h=0.05, sx=1.22, sy=0.45)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=2.95, name='stage003_s5',
                             objects=[{'mesh_file': box_fr, 'x': 1.65, 'y': -0.115,
                                       'yaw_deg': 0.0},
                                      {'mesh_file': box_fl, 'x': 1.74, 'y': 0.185,
                                       'yaw_deg': 0.0}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=90.0)
    env.reset(seed=0)
    return env


def perturb(env, dx, dy, dyaw):
    q = env.data.qpos
    q[0] += dx
    q[1] += dy
    if abs(dyaw) > 1e-9:
        th = np.deg2rad(dyaw)
        c, s = np.cos(th / 2), np.sin(th / 2)
        w, x, y, z = (float(v) for v in q[3:7])
        q[3] = c * w - s * z
        q[4] = c * x + s * y
        q[5] = c * y - s * x
        q[6] = c * z + s * w
    mujoco.mj_forward(env.model, env.data)


def run_one(soil, dx, dy, dyaw, speed):
    env = build_env(soil)
    perturb(env, dx, dy, dyaw)
    qh = hashlib.sha256(np.asarray(env.data.qpos, np.float64).tobytes()).hexdigest()
    m, d = env.model, env.data
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    term = {}
    for _ in range(int(45.0 * 50)):
        env.step_command(joint_targets_rad=STANCE,
                         wheel_omega_rad_s=np.full(4, speed / vc.WHEEL_R),
                         wheel_mode='velocity')
        if env.terminated or env.truncated:
            term = {'reason': env.last_termination.get('reason')}
            break
        if float(d.qpos[0]) >= FAR_X + 0.35:
            break
    for _ in range(80):
        if abs(float(d.qvel[0])) <= 0.010:
            break
        env.step_command(joint_targets_rad=STANCE, wheel_omega_rad_s=np.zeros(4),
                         wheel_mode='velocity')
    rows = []
    for _ in range(100):
        env.step_command(joint_targets_rad=STANCE, wheel_omega_rad_s=np.zeros(4),
                         wheel_mode='velocity')
        rows.append({'t': round(float(env.t), 3), 'x': round(float(d.qpos[0]), 4),
                     'tilt': round(float(np.degrees(np.arccos(
                         np.clip(d.xmat[bid][8], -1, 1)))), 3),
                     'vx': round(float(d.qvel[0]), 4)})
        if env.terminated or env.truncated:
            break
    win = rows[-50:]
    wheel_z = {leg: round(float(d.xpos[bc.wheel_body(env, leg)][2]), 4) for leg in LEG}
    tilt = max((r['tilt'] for r in win), default=99)
    vx = max((abs(r['vx']) for r in win), default=99)
    grounded = all(z <= 0.12 for z in wheel_z.values())
    crossed = float(d.qpos[0]) >= FAR_X + 0.25
    ok = bool(win and crossed and grounded and tilt <= 10.0 and vx <= 0.03
              and not env.terminated)
    return {'state': {'dx': dx, 'dy': dy, 'dyaw_deg': dyaw, 'qpos_sha256': qh},
            'speed_mps': speed, 'passed': ok, 'crossed': crossed,
            'grounded': grounded, 'final_x': round(float(d.qpos[0]), 4),
            'wheel_z': wheel_z, 'tilt_max': tilt, 'vx_max': vx,
            'termination': term, 'time_s': round(float(env.t), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--soil', default='nominal', choices=['rigid', 'nominal'])
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    states = [(0.0, 0.0, 0.0), (0.02, 0.01, 1.0), (-0.02, -0.01, -1.0)]
    rows = []
    for st in states:
        for speed in (0.30, 0.15):
            r = run_one(a.soil, *st, speed)
            rows.append(r)
            print(json.dumps(r, ensure_ascii=False))
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    res = {'schema': 'v3-wheel-compare/v1', 'soil': a.soil, 'far_x': FAR_X,
           'criterion': 'same terminal function: crossed + grounded + tilt<=10 + vx<=0.03 + no term',
           'rows': rows}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
