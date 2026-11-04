"""统一任务终点执行：D2 与 BODY 共用 env 任务合同（min wheel>=goal_x + settle）。"""
import json, pathlib, sys
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import wheelleg_env, skills, runner, stage6_body_skill as SB
import v3_basic_cycle as bc
import stage8_matrix2 as M, stage6_matrix as S6M

def load_scene(name):
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    if name == 'ref':
        return json.loads((truth / 'scene_spec.json').read_text()), truth / 'state_snapshot.json'
    z = np.load(ROOT / 'runs/v3/stage010/g1v2' / f'occ2_{name}.npz')
    occ = M.resample_walls(z['P'], np.asarray(z['origin'], float), float(z['pitch']))
    tmp = ROOT / 'runs/v3/stage11/scenes' / name; tmp.mkdir(parents=True, exist_ok=True)
    spec, _env, sha = M.make_scene(occ, tmp, f'endpoint_{name}')
    return spec, truth / 'state_snapshot.json'

def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    snap = json.loads((truth / 'state_snapshot.json').read_text())
    out = ROOT / 'runs/v3/stage11/endpoint'; out.mkdir(parents=True, exist_ok=True)
    rep = {'schema': 'stage11-endpoint/v1',
           'contract': {'goal_x': None, 'settle_s': None, 'tip_deg': None,
                        'budget_s': 120.0,
                        'success': 'env reason=success (min wheel x >= goal_x, in channel, stable settle)',
                        'timing': 'env.t from common S0 until termination'},
           'runs': {}}
    for scen in ('ref', 'len_short'):
        spec, _ = load_scene(scen)
        env0 = wheelleg_env.WheelLegEnv(spec, max_seconds=120.0); env0.reset(seed=0)
        env0.restore_state(snap, mode='same_scene' if scen == 'ref' else 'project')
        q0 = np.asarray(env0.data.qpos, float).copy()
        # 合同值直接来自冻结 spec
        rep['contract'].update(goal_x=float(spec.get('goal_x')), settle_s=float(spec.get('settle_seconds', 1.0)),
                               tip_deg=float(spec.get('tip_deg', 60.0)))
        # 底座到后轮的最小前向偏移（从模型本身量，不用手写常数）
        import mujoco
        mujoco.mj_forward(env0.model, env0.data)
        offset = float(q0[0] - min(env0._wheel_xs()))
        for action in ('D2', 'BODY'):
            tag = f'{scen}_{action}'
            d = out / tag; d.mkdir(parents=True, exist_ok=True)
            env = wheelleg_env.WheelLegEnv(spec, max_seconds=120.0); env.reset(seed=0)
            env.restore_state(snap, mode='same_scene' if scen == 'ref' else 'project')
            env.data.qacc_warmstart[:] = 0.0
            t0 = float(env.t)
            if action == 'D2':
                sk = skills.make_skill('D2')
                ep = runner.EpisodeRunner(env, sk, visible={'x_front': 0.834, 'W_vis': 0.275, 'H_vis': 0.30},
                                          seed=0, record_trajectory=True)
                import v3_record
                rec = v3_record.Recorder(d / 'record', {'action': 'D2', 'method': 'stage11_endpoint'}, hz=50.0)
                ep.recorder = rec; ep.record_trajectory = True
                res = ep.run_from_state(snap, mode='same_scene' if scen == 'ref' else 'project')
                rec.close()
                success = bool(res['success']); t_end = float(res['t_end'])
            else:
                plan = {'raise_z': 0.06, 'ramp_steps': 100, 'speed': 0.15,
                        'lower_at_x': 1.165, 'end_x': round(float(spec.get('goal_x')) + offset, 3),
                        'stop_tilt_deg': 12.0, 'plan_id': 'stage11_unified'}
                row = SB.run_body_clearance(env, plan, record_dir=d / 'record',
                                            meta={'action': 'BODY', 'method': 'stage11_endpoint'})
                # 统一任务终点：底盘到达后继续以同一速度行驶，直到后轮越过 goal_x；
                # 再制动并满足 settle，全部按 env 任务合同判定。
                targets = {leg: dict(bc.STANCE) for leg in bc.LEG}
                while (not env.terminated and env.t < 120.0
                       and min(env._wheel_xs()) < float(spec.get('goal_x', 2.6)) + 0.02):
                    env.step_command(joint_targets_rad=targets,
                                     wheel_omega_rad_s=np.full(4, 0.15 / 0.086),
                                     wheel_mode='velocity')
                while not env.terminated and env.t < 120.0:
                    # 刹车保持（避免零速控制滚回终点线以下），仍走 env.step 的任务检查
                    env.step_command(joint_targets_rad=targets, wheel_brake=np.ones(4, bool))
                term = dict(getattr(env, 'last_termination', {}) or {})
                success = term.get('reason') == 'success'
                t_end = float(env.t)
            rec_dir = d / 'record'
            chunks = sorted(rec_dir.glob('chunk_*.npz'))
            q = np.concatenate([np.load(c)['qpos'] for c in chunks]) if chunks else None
            man = {'base_x': round(float(env.data.qpos[0]), 3),
                   'min_wheel_x': round(float(min(env._wheel_xs())), 3),
                   'chassis_contacts': int(S6M.chassis_contacts_from_record({'trajectory_path': str(rec_dir / 'index.json')})),
                   't_start': round(t0, 3), 't_end': round(t_end, 3),
                   'cost_s': round(t_end - t0, 3), 'success_env_contract': success,
                   'termination': dict(getattr(env, 'last_termination', {}) or {}),
                   'budget_s': 120.0}
            rep['runs'][tag] = man
            (out / f'{tag}.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
            print(json.dumps({tag: man}, ensure_ascii=False), flush=True)
            del env
    (out / 'endpoint_result.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    sys.exit(main())
