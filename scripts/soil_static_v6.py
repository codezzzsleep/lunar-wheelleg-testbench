"""
V6 工作包 H1/H2：真正静态的整机月壤测量。

与 V5 stage_g 的区别：
  - 不用 env.step(np.zeros(3))（仍按 v_ref 驱动车轮）；
  - 用 env.brake_step() 显式零轮速/制动保持；
  - 记录轮速、机体速度、倾角、连续稳定窗口与轮-土接触；
  - 不稳定/无有效接触 -> insufficient_evidence，不拿 contact=false 时的轮底高度解释载荷—下陷。
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import soil as SOIL
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def wheel_state(env):
    out = []
    for g in sorted(env.wheel_geoms):
        R, width = env._wheel_geom_radius(g)
        p = np.asarray(env.data.geom_xpos[g], dtype=float)
        gh = float(env._ground_height(float(p[0]), float(p[1])))
        out.append({'geom': int(g), 'R_m': round(float(R), 5),
                    'width_m': round(float(width), 5),
                    'center_z': round(float(p[2]), 6),
                    'ground_z': round(gh, 6),
                    'penetration_m': round(float(gh - (float(p[2]) - float(R))), 6)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='runs/unseen/delivery_v6/v6_20261029/soil')
    ap.add_argument('--seconds', type=float, default=3.0)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    p = SOIL.SoilParams.moon_nominal()
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6,
                             name='v6_static')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    params = {k: getattr(p, k) for k in ('kc', 'kphi', 'n', 'cohesion_pa', 'phi_deg', 'k_shear', 'source')}
    spec['soil'] = {'mode': 'soil', 'params': params}
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=a.seconds + 1.0,
                                   v_ref=1.0, tip_deg=60.0)
    env.reset(seed=a.seed)
    steps = int(round(a.seconds / 0.02))
    hist = []
    t0 = time.time()
    for i in range(steps):
        env.brake_step()
        wheels = wheel_state(env)
        ws = []
        for leg in ('FL', 'FR', 'RL', 'RR'):
            j = env.J.get(f'{leg}_wheel_joint')
            if j:
                ws.append(abs(float(env.data.qvel[j['vadr']])))
        hist.append({
            'i': i, 't_sim': round(float(env.t), 4),
            'wheel_qvel_abs': [round(x, 6) for x in ws],
            'base_vx': round(abs(float(env.data.qvel[0])), 6),
            'base_vy': round(abs(float(env.data.qvel[1])), 6),
            'tilt_deg': round(float(env._tilt()), 4),
            'ncon': int(env.data.ncon),
            'wheels': wheels,
            'soil': env.soil_report() if hasattr(env, 'soil_report') else None,
        })
    tail = hist[-50:]
    stable = {
        'window_steps': len(tail),
        'max_wheel_qvel': max((max(h['wheel_qvel_abs']) if h['wheel_qvel_abs'] else 0.0) for h in tail),
        'max_base_vx': max(h['base_vx'] for h in tail),
        'max_base_vy': max(h['base_vy'] for h in tail),
        'max_tilt_range': max(h['tilt_deg'] for h in tail) - min(h['tilt_deg'] for h in tail),
        'min_ncon': min(h['ncon'] for h in tail),
    }
    stable_ok = (stable['max_wheel_qvel'] < 0.05 and stable['max_base_vx'] < 0.02
                 and stable['max_base_vy'] < 0.02 and stable['max_tilt_range'] < 1.0
                 and stable['min_ncon'] >= 1)
    wheels = hist[-1]['wheels']
    load = 14.5 * 9.81 / max(1, len(wheels))   # 整机名义质量；公开值，非真值内部状态
    rows = []
    for w in wheels:
        z = p.sinkage(load, w['width_m'], w['R_m'])
        rows.append({**w, 'nominal_load_n': round(float(load), 3),
                     'formula_sink_m': round(float(z), 6),
                     'actual_penetration_m': w['penetration_m']})
    report = {
        'schema': 'soil-static/v6', 'version': 'v6/H1-H2', 'seed': a.seed,
        'seconds': a.seconds, 'steps': steps, 'wall_s': round(time.time() - t0, 3),
        'mode': 'soil', 'params': p.as_dict(),
        'stable_window': stable, 'stable_ok': bool(stable_ok),
        'contact_valid': bool(stable['min_ncon'] >= 1 and any(w['penetration_m'] > -0.01 for w in wheels)),
        'wheels': rows,
        'formula_max_sink_m': max((r['formula_sink_m'] for r in rows), default=None),
        'actual_max_penetration_m': max((r['actual_penetration_m'] for r in rows), default=None),
        'verdict': ('MEASURED' if (stable_ok and stable['min_ncon'] >= 1)
                    else 'INSUFFICIENT_EVIDENCE'),
        'note': ('真正静态：brake_step 零轮速/制动保持；不是 env.step(零) 的 v_ref 驱动。'
                 '公式用该轮法向载荷/轮宽/轮径；实际穿透用同一时刻轮底相对地面。'
                 '未稳定或无接触时判 insufficient_evidence。'),
        'history_tail': hist[-10:],
    }
    (out / 'static_v6.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ('stable_ok', 'contact_valid', 'verdict',
                                             'formula_max_sink_m', 'actual_max_penetration_m',
                                             'stable_window')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
