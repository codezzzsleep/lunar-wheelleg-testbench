"""共同观察后真实状态采集（收口整改 §5.3）。

对每个（配置, 土壤, 验证 seed）：
  在独立真值场景里真实驾驶 → 制动 → 连续停稳 → 采集观测与完整状态快照。

产物是后续六方法共用的同一个状态：同一 qpos/qvel、同一时钟、同一状态哈希、
同一观测包，以及停稳判定。采集失败必须写 common_acquisition_failed 与证据，
不得伪造可用快照。

  python scripts/v7_acquire_states.py --plan plans/r1_states_plan.json --out <dir>
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np

import drive_observe as DO
import observe
import terrain
import v7_soil
import wheelleg_env


def sha_file(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def build_spec(cfg, soil_label, seed=None, pert=None):
    case = json.loads((ROOT / cfg['case_config']).read_text())
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=case['goal_x'],
                             name=f"acq_{cfg['config_id']}_{soil_label}")
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    # 只换 seed 标签不会产生不同状态：必须给出非负扰动幅度（§5.3）
    _p = pert or {}
    spec['init_perturbation'] = {'lateral_m': float(_p.get('lateral_m', 0.0)),
                                 'yaw_rad': float(_p.get('yaw_rad', 0.0))}
    spec['skill_cfg'] = {'task': 'M'}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    spec['objects'] = [{'mesh_file': cfg['mesh'], 'x': case['obstacle_x'], 'y': 0.0,
                        'yaw_deg': 0.0, 'target_height_m': case['H']}]
    r = v7_soil.resolve(soil_label)
    if r.get('mode') == 'rigid':
        spec['soil'] = {'mode': 'rigid', 'label': soil_label, 'params': None}
    else:
        spec['soil'] = {'mode': 'soil', 'label': r.get('label'), 'params': r['params']}
    return spec, case, r


def acquire(unit, cfg, out_root):
    cid = cfg['config_id']
    soil = unit['soil']
    seed = int(unit['seed'])
    d = out_root / cid / soil / f'seed{seed}'
    d.mkdir(parents=True, exist_ok=True)
    rec = {'schema': 'common-state/v1', 'config_id': cid, 'soil': soil, 'seed': seed,
           'case_config': cfg['case_config'], 'mesh': cfg['mesh'],
           'started': time.time()}
    t0 = time.time()
    try:
        pert = (cfg.get('perturbations') or {}).get(str(seed))
        spec, case, soilr = build_spec(cfg, soil, seed=seed, pert=pert)
        rec['perturbation'] = spec['init_perturbation']
        rec['soil_params_sha'] = soilr.get('params_sha')
        rec['soil_mode'] = soilr.get('mode')
        env = wheelleg_env.WheelLegEnv(spec, max_seconds=float(cfg.get('budget_s', 30.0)))
        env.reset(seed=seed)
        _s0 = env.save_state()
        rec['initial_state_hash'] = _s0.get('state_hash')
        _s0p = d / 'state_snapshot_s0.json'
        _s0p.write_text(json.dumps(_s0, ensure_ascii=False))
        rec['s0'] = {'snapshot': str(_s0p.relative_to(ROOT)),
                     'state_hash': _s0.get('state_hash'), 'env_t': _s0.get('env_t')}
        DO.drive_to_nav(env, float(cfg.get('drive_target_y', 0.30)),
                        stop_x=float(cfg.get('drive_stop_x', 1.30)),
                        max_s=float(cfg.get('drive_max_s', 10.0)),
                        v=float(cfg.get('drive_v', 0.10)))
        st = DO.brake_and_settle(env, max_s=float(cfg.get('settle_max_s', 6.0)))
        if not st.get('stable'):
            t_hold = float(env.t)
            while float(env.t) - t_hold < 0.8:
                env.step_drive(0.0, 0.0)
            st = DO.brake_and_settle(env, max_s=3.0)
        rec['settle'] = {'stable': bool(st.get('stable')),
                         'speed_mps': round(float(np.linalg.norm(np.asarray(env.data.qvel[:3]))), 5),
                         'omega_rps': round(float(np.linalg.norm(np.asarray(env.data.qvel[3:6]))), 5),
                         'tilt_deg': round(float(env._tilt()), 3)}
        import mujoco as mj
        mj.mj_forward(env.model, env.data)
        cam_id = observe.cam_id_of(env)
        rec['camera'] = {'pos': [float(x) for x in env.data.cam_xpos[cam_id]],
                         'schema': 'camera-snapshot/v2'}
        obs_dir = d / 'observation'
        try:
            observe.capture_observation(env, obs_dir, obs_id=f'{cid}_{soil}_seed{seed}')
            obs_ok = True
            obs_err = None
        except Exception as e:
            obs_ok = False
            obs_err = f'{type(e).__name__}: {e}'
        rec['observation'] = {'ok': obs_ok, 'error': obs_err,
                              'dir': str(obs_dir.relative_to(ROOT)) if obs_ok else None,
                              'sha': sha_file(obs_dir / 'observation.json') if obs_ok else None}
        if obs_ok:
            oj = json.loads((obs_dir / 'observation.json').read_text())
            rec['visible'] = oj.get('visible')
        snap = env.save_state()
        snap_path = d / 'state_snapshot.json'
        snap_path.write_text(json.dumps(snap, ensure_ascii=False))
        rec['state'] = {'snapshot': str(snap_path.relative_to(ROOT)),
                        'state_hash': snap.get('state_hash'),
                        'env_t': snap.get('env_t'), 'data_time': snap.get('data_time')}
        rec['ok'] = bool(obs_ok and st.get('stable'))
        if not rec['ok']:
            rec['failure'] = 'common_acquisition_failed'
            rec['failure_reasons'] = ([('observation_failed:' + str(obs_err))] if not obs_ok else []) + \
                                     ([] if st.get('stable') else ['not_stable_after_settle'])
    except Exception as e:
        rec['ok'] = False
        rec['failure'] = 'common_acquisition_failed'
        rec['error'] = f'{type(e).__name__}: {e}'
    rec['seconds'] = round(time.time() - t0, 2)
    (d / 'acquisition.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--config', default=None, help='只跑某个 config_id')
    ap.add_argument('--soils', default=None)
    ap.add_argument('--seeds', default=None)
    a = ap.parse_args()
    plan = json.loads((ROOT / a.plan).read_text())
    out_root = ROOT / a.out
    out_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for cfg in plan['configs']:
        if a.config and cfg['config_id'] != a.config:
            continue
        soils = a.soils.split(',') if a.soils else plan['soils']
        seeds = ([int(x) for x in a.seeds.split(',')] if a.seeds else plan['seeds'])
        for soil in soils:
            for seed in seeds:
                rec = acquire({'soil': soil, 'seed': seed}, cfg, out_root)
                rows.append(rec)
                print(json.dumps({'config': cfg['config_id'], 'soil': soil, 'seed': seed,
                                  'ok': rec.get('ok'), 'state_hash': (rec.get('state') or {}).get('state_hash'),
                                  'failure': rec.get('failure')}, ensure_ascii=False), flush=True)
                (out_root / 'index.json').write_text(json.dumps({'rows': rows}, ensure_ascii=False, indent=2))
    ok = sum(1 for r in rows if r.get('ok'))
    print(json.dumps({'n': len(rows), 'ok': ok,
                      'failed': len(rows) - ok}, ensure_ascii=False))


if __name__ == '__main__':
    main()
