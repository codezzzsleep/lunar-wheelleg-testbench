"""Stage006：nominal 平地 BODY_CLEARANCE 标定（抬身/保持/恢复）。"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain  # noqa: E402
import v7_soil  # noqa: E402
import wheelleg_env  # noqa: E402
import v3_record  # noqa: E402
import v3_basic_cycle as bc  # noqa: E402
import stage6_body as SB  # noqa: E402


def flat_env(soil='nominal', budget=60.0):
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=6.0, objects=[])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve(soil)
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=budget)
    env.reset(seed=0)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/v3/stage006/calib')
    ap.add_argument('--targets', default='0.02,0.04,0.06')
    a = ap.parse_args()
    out = (ROOT / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    results = []
    for tgt in [float(x) for x in a.targets.split(',')]:
        env = flat_env()
        rec = v3_record.Recorder(out / f'z{int(round(tgt*100)):02d}' / 'record',
                                 {'skill': 'BODY_CLEARANCE', 'target_z': tgt}, hz=50.0)
        targets = {leg: dict(bc.STANCE) for leg in bc.LEG}
        k = 0
        rows = []
        h0 = None
        # settle
        for _ in range(25):
            env.step_command(joint_targets_rad=targets, wheel_mode='coast')
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t)); k += 1
        z0 = float(env.data.qpos[2]); c0 = SB.chassis_min_z(env)
        # raise 2 s
        t2, r = SB.ramp(env, targets, 100, tgt, k0=k)
        for row in r:
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t)); k += 1
        rows += r; targets = t2
        # hold 1.5 s
        r = SB.hold(env, targets, 75, 'hold', k)
        for _ in r:
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t)); k += 1
        rows += r
        z_hold = float(env.data.qpos[2]); c_hold = SB.chassis_min_z(env)
        # lower 2 s
        t3, r = SB.ramp(env, targets, 100, -tgt, k0=k)
        for row in r:
            rec.add(v3_record.frame_from_env(env, None, [0, 0, 0], k, env.t)); k += 1
        rows += r; targets = t3
        # settle
        r = SB.hold(env, targets, 25, 'settle', k)
        rows += r
        ref = rec.close()
        hold_rows = [x for x in rows if x['phase'] == 'hold']
        win = hold_rows[-50:] if len(hold_rows) >= 50 else hold_rows
        tilt_max = max((x['tilt'] for x in win), default=99)
        load_min = min((min(x['loads'].values()) for x in win), default=0)
        z_gain = z_hold - z0
        c_gain = c_hold - c0
        margin_min = min((min(v['margin_lo'], v['margin_hi']) for x in rows for v in x['joints'].values()), default=0)
        ok = bool(win and tilt_max <= 10 and load_min >= 1.0
                  and 0.8 * tgt <= z_gain <= 1.5 * tgt
                  and c_gain >= 0.8 * tgt and margin_min >= 0.03
                  and not env.terminated)
        res = {'target_z': tgt, 'z0': round(z0, 4), 'z_hold': round(z_hold, 4),
               'z_gain': round(z_gain, 4), 'chassis0': round(c0, 4),
               'chassis_hold': round(c_hold, 4), 'clearance_gain': round(c_gain, 4),
               'tilt_max': round(tilt_max, 3), 'min_wheel_load': round(load_min, 3),
               'joint_margin_min': round(margin_min, 4), 'terminated': bool(env.terminated),
               'hold_window': len(win), 'ok': ok,
               'trajectory': ref,
               'rows': [{kk: x[kk] for kk in ('t', 'phase', 'base_z', 'tilt',
                                              'min_load', 'chassis_min_z')}
                        for x in rows] if False else None}
        # 精简行，避免结果文件过大
        res.pop('rows', None)
        results.append(res)
        print(json.dumps({k: res[k] for k in ('target_z', 'z_gain', 'clearance_gain',
                                              'tilt_max', 'min_wheel_load',
                                              'joint_margin_min', 'ok')}))
    (out / 'result.json').write_text(json.dumps({'schema': 'stage6-calib/v1', 'results': results},
                                                ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
