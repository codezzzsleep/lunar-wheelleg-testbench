"""静态标定：支撑腿 hip 偏移 -> 机身 roll 的符号与增益（不猜符号）。"""
import argparse, json, pathlib, sys
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain, wheelleg_env
LEG = ('FR', 'FL', 'RR', 'RL')
STANCE = {'hip': 0.0, 'thigh': 0.85, 'calf': -1.65}


def roll(env):
    import math
    q = env.data.qpos[3:7]
    w, x, y, z = map(float, q)
    return math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))


def trial(h):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=5.0, name='rollcal')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=4.0)
    env.reset(seed=0)
    base = {leg: dict(STANCE) for leg in LEG}
    for _ in range(20):
        env.step_command(joint_targets_rad=base, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
    r0 = roll(env)
    tgt = {leg: dict(STANCE) for leg in LEG}
    for leg in ('FL', 'RR', 'RL'):
        tgt[leg]['hip'] = h
    for _ in range(60):
        env.step_command(joint_targets_rad=tgt, wheel_omega_rad_s=np.zeros(4),
                         wheel_brake=np.ones(4))
    return {'hip': h, 'roll0_deg': round(np.degrees(r0), 3),
            'roll_deg': round(np.degrees(roll(env)), 3),
            'delta_deg': round(np.degrees(roll(env) - r0), 3),
            'tilt_deg': round(float(env._tilt()), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/control/rollcal.json')
    a = ap.parse_args()
    rows = [trial(h) for h in (-0.2, -0.1, 0.0, 0.1, 0.2)]
    xs = np.array([r['hip'] for r in rows]); ys = np.array([r['delta_deg'] for r in rows])
    gain = float(np.polyfit(xs, ys, 1)[0]) if len(set(xs)) > 1 else None
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'schema': 'v3-rollcal/v1', 'rows': rows,
                               'd_roll_deg_per_rad': None if gain is None else round(gain, 3)},
                              ensure_ascii=False, indent=2))
    print(json.dumps({'rows': rows, 'gain_deg_per_rad': None if gain is None else round(gain, 3)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
