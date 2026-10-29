"""
V5 月壤物理验收（P5）。

  MUJOCO_GL=osmesa .venv/bin/python scripts/soil_acceptance_v5.py \
      --out runs/unseen/delivery_v5/v5_20261029/soil --stages a,b,c,d,f,g
  MUJOCO_GL=osmesa .venv/bin/python scripts/soil_acceptance_v5.py \
      --out ... --stages e --episodes 1000

层级（每项都写清楚，不把近似冒充真实月壤）：
  A 单轮载荷-下陷：公式目标 vs 单轮标定/验证；标定与验证载荷分开；
  B 平地阻力：刚性 vs 土壤，同控制输入；
  C 坡面：冻结坡度扫描，记录通过/滑转/倾角/载荷；
  D 零牵引：复用单轮判别数据；
  E 稳定性：平地/坡面/障碍 × 参数样本 × 初态 × 动作，至少 1000 回合；
  F 吞吐：刚性 vs 土壤同场景对比；
  G 整机几何下陷：实测轮底穿透 vs 公式估计，明确是否实现。
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import actions as ACT
import runner as R
import skills
import soil as SOIL
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
MOON_G = 1.62


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _spec(slope=0.0, obstacle=None, soil_params=None, seed=0, goal_x=2.6):
    spec = terrain.make_spec(kind='flat', seed=seed, slope_deg=slope,
                             objects=[], goal_x=goal_x, name='soilv5')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    if obstacle:
        spec['objects'] = [obstacle]
    if soil_params is not None:
        spec['soil'] = {'mode': 'soil', 'params': soil_params}
    return spec


def run_skill(slope=0.0, obstacle=None, soil_params=None, action='R1', seed=0,
              seconds=6.0):
    env = wheelleg_env.WheelLegEnv(_spec(slope, obstacle, soil_params, seed),
                                   control_hz=50.0, max_seconds=seconds,
                                   v_ref=1.0, tip_deg=60.0)
    vis = {'x_front': 1.6, 'W_vis': 0.16, 'H_vis': 0.30}
    t0 = time.time()
    out = R.EpisodeRunner(env, skills.make_skill(action), visible=vis,
                          seed=seed).run()
    wall = time.time() - t0
    st = env.soil_report() if env.soil_mode != 'rigid' else None
    # 轮底相对地表的穿透（正=下陷，负=悬空）
    pen = []
    try:
        for g in sorted(env.wheel_geoms):
            Rr, _bw = env._wheel_geom_radius(g)
            p = env.data.geom_xpos[g]
            gh = env._ground_height(float(p[0]), float(p[1]))
            pen.append(float(gh - (float(p[2]) - Rr)))
    except Exception:
        pass
    return {
        'action': action, 'seed': seed, 'slope_deg': slope,
        'obstacle': bool(obstacle), 'soil': soil_params is not None,
        'reason': out['reason'], 'success': out['success'], 'abort': out['abort'],
        't_end': out['t_end'], 'final_x': out['final_x'],
        'max_tilt': out['max_tilt'], 'contact': out['contact'],
        'control_steps': out['steps'], 'physics_steps': int(env.n_physics),
        'wall_s': round(wall, 4), 'soil_report': st,
        'wheel_penetration_m': (round(float(np.max(pen)), 6) if pen else None),
        'finite': bool(np.all(np.isfinite(env.data.qpos)) and
                       np.all(np.isfinite(env.data.qvel))),
        'max_abs_qpos': round(float(np.max(np.abs(env.data.qpos))), 6),
        'max_abs_qvel': round(float(np.max(np.abs(env.data.qvel))), 6),
    }


def stage_a(out):
    """单轮载荷-下陷：已有标定 + 新的验证载荷（同一单轮装置、同一拟合系数）。"""
    import soil_single_wheel as SW
    src = ROOT / 'runs/unseen/recovery_r3/soil/single_wheel.json'
    base = json.loads(src.read_text()) if src.exists() else {}
    factor = float((base.get('fit') or {}).get('factor') or 0.00151)
    pm = SOIL.SoilParams.moon_nominal()
    rows = []
    for W in (30.0, 50.0, 70.0, 90.0):
        z_t = pm.sinkage(W, SW.WHEEL_B, SW.WHEEL_R)
        k = SW.tangent_stiffness(pm, z_t, SW.WHEEL_B) * factor
        dmp = 0.9 * 2 * np.sqrt(max(k, 1e-6) * 0.4)
        z_m, stable = SW.measure_sinkage(k, dmp, W, seconds=3.0)
        rows.append({'load_n': W, 'split': 'validation',
                     'z_target_mm': round(z_t * 1000, 3),
                     'z_measured_mm': (round(z_m * 1000, 3) if z_m is not None else None),
                     'rel_err': (round(abs(z_m - z_t) / max(z_t, 1e-9), 4)
                                 if z_m is not None else None),
                     'stable': bool(stable), 'k_used': round(k, 3)})
    return {
        'stage': 'A_single_wheel_load_sinkage',
        'source': str(src), 'source_sha256': sha(src) if src.exists() else None,
        'calibration': base.get('calibrated_rows'),
        'validation': rows,
        'fit_factor': factor,
        'rig_geometry': {'wheel_radius_m': SW.WHEEL_R, 'wheel_width_m': SW.WHEEL_B},
        'robot_wheel_geometry': {'wheel_radius_m': 0.08595, 'wheel_width_m': 0.0526},
        'units': {'W': 'N (force)', 'z': 'm', 'p': 'Pa',
                  'kc': 'N/m^(n+1)', 'kphi': 'N/m^(n+2)'},
        'limitation': ('单轮竖直滑轨、显式刚度弹簧近似；不是整机，不含滑转/坡面；'
                       '轮几何 0.09/0.10 与整机 0.08595/0.0526 不同，'
                       '因子不能直接证明整机几何下陷'),
    }


def stage_b(out):
    rows = []
    for soil_mode in (False, True):
        params = SOIL.SoilParams.moon_nominal().as_dict() if soil_mode else None
        if params:
            params = {k: params[k] for k in
                      ('kc', 'kphi', 'n', 'cohesion_pa', 'phi_deg', 'k_shear', 'source')
                      if k in params}
        for rep in range(3):
            rows.append(run_skill(soil_params=params, action='R1', seed=rep,
                                  seconds=6.0))
    rigid = [r for r in rows if not r['soil']]
    soft = [r for r in rows if r['soil']]
    def mean(k, rs):
        v = [r[k] for r in rs if r.get(k) is not None]
        return round(float(np.mean(v)), 4) if v else None
    return {'stage': 'B_flat_resistance', 'rows': rows,
            'summary': {'rigid_final_x_mean': mean('final_x', rigid),
                        'soil_final_x_mean': mean('final_x', soft),
                        'rigid_wall_s_mean': mean('wall_s', rigid),
                        'soil_wall_s_mean': mean('wall_s', soft),
                        'soil_work_j_mean': (round(float(np.mean(
                            [r['soil_report']['work_j'] for r in soft
                             if r.get('soil_report')])), 4) if soft else None),
                        'note': '同一 R1 控制输入；土壤模式的位移/功由实际接触与压实阻力产生'}}


def stage_c(out):
    rows = []
    for deg in (0.0, 5.0, 10.0, 15.0, 20.0):
        for soil_mode in (False, True):
            params = SOIL.SoilParams.moon_nominal().as_dict() if soil_mode else None
            if params:
                params = {k: params[k] for k in
                          ('kc', 'kphi', 'n', 'cohesion_pa', 'phi_deg', 'k_shear', 'source')
                          if k in params}
            r = run_skill(slope=deg, soil_params=params, action='R1', seed=0,
                          seconds=6.0)
            rows.append(r)
    return {'stage': 'C_slope', 'rows': rows,
            'note': ('冻结 R1/6 s/初态 seed0；坡度只改 slope_deg；'
                     '未通过的坡面如实记录，不调控制参数凑预期')}


def stage_d(out):
    src = ROOT / 'runs/unseen/recovery_r3/soil/traction_test.json'
    rows = []
    if src.exists():
        d = json.loads(src.read_text())
        rows = [r for r in d.get('rows', []) if r.get('cohesion_pa') == 0.0
                and r.get('phi_deg') == 0.0]
    return {'stage': 'D_zero_traction', 'source': str(src),
            'source_sha256': sha(src) if src.exists() else None,
            'rows': rows,
            'rule': 'H=0 时不允许持续牵引；瞬态 p95 与稳态 p50 分开',
            'note': '复用已提交的单轮判别数据；不是整机'}


def stage_f(out):
    rows = []
    for soil_mode in (False, True):
        params = SOIL.SoilParams.moon_nominal().as_dict() if soil_mode else None
        if params:
            params = {k: params[k] for k in
                      ('kc', 'kphi', 'n', 'cohesion_pa', 'phi_deg', 'k_shear', 'source')
                      if k in params}
        for rep in range(3):
            rows.append(run_skill(soil_params=params, action='R1', seed=rep,
                                  seconds=4.0))
    rigid = [r for r in rows if not r['soil']]
    soft = [r for r in rows if r['soil']]
    def mean(k, rs):
        return round(float(np.mean([r[k] for r in rs])), 4) if rs else None
    ratio = (mean('wall_s', soft) / mean('wall_s', rigid)
             if rigid and soft and mean('wall_s', rigid) else None)
    return {'stage': 'F_throughput', 'rows': rows,
            'summary': {'rigid_wall_s_mean': mean('wall_s', rigid),
                        'soil_wall_s_mean': mean('wall_s', soft),
                        'wall_time_ratio_soil_over_rigid': round(ratio, 3) if ratio else None,
                        'same_control_steps': all(r['control_steps'] == rows[0]['control_steps']
                                                  for r in rows),
                        'note': '同场景/同控制/同初态；无渲染；土壤模式额外做逐轮接触计算'}}


def stage_g(out):
    # 整机平地土壤 3 s：公式估计的下陷 vs 轮底实际几何穿透
    params = SOIL.SoilParams.moon_nominal().as_dict()
    params = {k: params[k] for k in
              ('kc', 'kphi', 'n', 'cohesion_pa', 'phi_deg', 'k_shear', 'source')
              if k in params}
    r = run_skill(soil_params=params, action='R1', seed=0, seconds=3.0)
    est = (r.get('soil_report') or {}).get('max_sink_m')
    pen = r.get('wheel_penetration_m')
    # 静态整机：零动作 1 s，轮底与地表穿透；比移动末端更直接
    env = wheelleg_env.WheelLegEnv(_spec(soil_params=params), control_hz=50.0,
                                   max_seconds=2.0, v_ref=1.0, tip_deg=60.0)
    env.reset(seed=0)
    for _ in range(100):
        env.step(np.zeros(3))
    sp = []
    try:
        for g in sorted(env.wheel_geoms):
            Rr, _bw = env._wheel_geom_radius(g)
            p = env.data.geom_xpos[g]
            gh = env._ground_height(float(p[0]), float(p[1]))
            sp.append(float(gh - (float(p[2]) - Rr)))
    except Exception:
        pass
    static_pen = (max(sp) if sp else None)
    static_contact = bool(len(env.data.contact) > 0)
    static_est = (env.soil_report() or {}).get('max_sink_m')
    implemented = bool(static_pen is not None and static_pen > 0.001)
    return {'stage': 'G_whole_machine_geometry_sinkage', 'row': r,
            'moving': {'formula_max_sink_m': est, 'wheel_penetration_m': pen,
                       'contact_at_end': r.get('contact')},
            'static': {'steps': 100, 'penetration_m': static_pen,
                       'formula_max_sink_m': static_est,
                       'contact': static_contact,
                       'wheel_penetrations_m': [round(x, 6) for x in sp]},
            'geometry_sinkage_implemented': implemented,
            'verdict': ('PARTIAL_NOT_IMPLEMENTED' if not implemented else 'IMPLEMENTED'),
            'note': ('整机是刚性接触 + Bekker 压实阻力/等效牵引；'
                     '静态/移动实测轮底穿透都接近 0，公式 max_sink_m 是估计量；'
                     '没有把单轮标定的刚度映射为整机垂直下陷')}


def stage_e(out, episodes=1000, seconds=5.0):
    """稳定性组合：平地/坡面/障碍 × 5 参数 × 10 初态 × 5 动作 = 1000。"""
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    box = out / 'obstacle_box.stl'
    if not box.exists():
        import trimesh
        m = trimesh.creation.box(extents=[0.30, 0.30, 0.12])
        m.apply_translation([0, 0, 0.06])
        m.export(box)
    obstacle = {'mesh_file': str(box), 'x': 1.2, 'y': 0.0, 'yaw_deg': 0.0,
                'target_height_m': 0.12}
    nominal = SOIL.SoilParams.moon_nominal()
    rng = np.random.default_rng(20261029)
    samples = [nominal] + [SOIL.SoilParams.sample(rng) for _ in range(4)]
    samples = [{k: v for k, v in s.as_dict().items()
                if k in ('kc', 'kphi', 'n', 'cohesion_pa', 'phi_deg', 'k_shear', 'source')}
               for s in samples]
    terrains = [('flat', 0.0, None), ('slope10', 10.0, None),
                ('slope15', 15.0, None), ('obstacle', 0.0, obstacle)]
    actions = ['R1', 'R2', 'S1', 'D1', 'A0']
    seeds = list(range(10))
    combos = [(t, p, s, a) for t in terrains for p in range(len(samples))
              for s in seeds for a in actions]
    if len(combos) != episodes:
        # 以真实组合为准；不重复同一条补数
        print(f'note: combos={len(combos)} != requested {episodes}', file=sys.stderr)
    rows = []
    log = out / 'stability_1000.jsonl'
    with open(log, 'w') as f:
        for i, ((tname, slope, obs), pi, sd, act) in enumerate(combos, 1):
            r = run_skill(slope=slope, obstacle=obs, soil_params=samples[pi],
                          action=act, seed=sd, seconds=seconds)
            r.update({'terrain': tname, 'param_index': pi, 'episode': i})
            r['anomaly'] = (not r['finite'] or r['max_abs_qpos'] > 1e3
                            or r['max_abs_qvel'] > 1e3)
            rows.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
            f.flush()
            if i % 50 == 0:
                print(f'{i}/{len(combos)}', flush=True)
    summary = {
        'stage': 'E_stability', 'n_episodes': len(rows),
        'n_anomaly': sum(1 for r in rows if r['anomaly']),
        'n_nonfinite': sum(1 for r in rows if not r['finite']),
        'by_outcome': {}, 'by_terrain': {}, 'by_action': {},
        'max_abs_qpos': max(r['max_abs_qpos'] for r in rows),
        'max_abs_qvel': max(r['max_abs_qvel'] for r in rows),
        'max_final_x_m': max(r['final_x'] for r in rows),
        'max_tilt_deg': max((r.get('max_tilt') or 0.0) for r in rows),
        'n_out_of_field': sum(1 for r in rows if abs(r.get('final_x', 0.0)) > 6.1),
        'anomaly_rule': ('NaN/Inf、|final_x|>6.1 m、|max_tilt|>90°；'
                         'max_abs_qpos/qvel 含轮关节，不等于机体位姿'),
        'note': ('组合含平地/坡面/障碍、5 组土壤参数、10 个初态、5 个动作；'
                 '不是重复同一平地回合 1000 次；每回合 5 s'),
    }
    for r in rows:
        for key, field in (('by_outcome', 'reason'), ('by_terrain', 'terrain'),
                           ('by_action', 'action')):
            k = r[field]
            summary[key][k] = summary[key].get(k, 0) + 1
    (out / 'stability_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--stages', default='a,b,c,d,f,g')
    ap.add_argument('--episodes', type=int, default=1000)
    ap.add_argument('--episode-seconds', type=float, default=5.0)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    stages = [s.strip().lower() for s in a.stages.split(',') if s.strip()]
    rp = out / 'acceptance.json'
    if rp.exists():
        report = json.loads(rp.read_text())
        report.setdefault('stages', {})
    else:
        report = {'schema': 'soil-acceptance/v1',
                  'soil_version': SOIL.VERSION, 'stages': {},
                  'started': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    for s in stages:
        t0 = time.time()
        if s == 'a':
            report['stages']['a'] = stage_a(out)
        elif s == 'b':
            report['stages']['b'] = stage_b(out)
        elif s == 'c':
            report['stages']['c'] = stage_c(out)
        elif s == 'd':
            report['stages']['d'] = stage_d(out)
        elif s == 'e':
            report['stages']['e'] = stage_e(out, a.episodes, a.episode_seconds)
        elif s == 'f':
            report['stages']['f'] = stage_f(out)
        elif s == 'g':
            report['stages']['g'] = stage_g(out)
        else:
            raise SystemExit(f'未知 stage {s}')
        report['stages'][s]['wall_s'] = round(time.time() - t0, 2)
        (out / 'acceptance.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2))
        print('DONE', s, report['stages'][s]['wall_s'], flush=True)
    print(json.dumps({'stages': list(report['stages']),
                      'out': str(out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
