"""石头七行比较（正式入口）：土壤/seed 显式注入，H5_F 走融合链，H5_raw 单列。

  python scripts/v7_rock_families.py --rocks P06 --states S1 --out <dir>
"""
import argparse, hashlib, json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np
import collision_asset as CA, common_planner as CP, eval_six, observe, runner, skills
import v7_elev25d as E, v7_holdout_scan as HS, v7_soil, wheelleg_env
PY_ = sys.executable


def frozen():
    d = json.loads((ROOT / 'plans/rock_initial_states.json').read_text())
    return {s['id']: s for s in d['states']}, d['planning_soils'], d['execution_soil']


def build_env(rock, case, seed, lateral, yaw, soil, objects=None):
    """土壤与 seed 在**创建环境前**注入；返回 (env, 实际生效参数)。"""
    env = HS.make_env_for_rock(rock, case)
    r = v7_soil.resolve(soil)
    spec = dict(env.spec)
    spec['soil'] = ({'mode': 'rigid', 'label': soil} if r.get('mode') == 'rigid'
                    else {'mode': 'soil', 'label': r.get('label'), 'params': r['params']})
    if objects is not None:
        spec['objects'] = objects
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
    env.init_perturbation = {'lateral': abs(lateral), 'yaw': abs(yaw)}
    env.reset(seed=seed)
    applied = {'seed': seed, 'lateral': abs(lateral), 'yaw': abs(yaw),
               'soil_label': soil, 'soil_mode': env.soil_mode,
               'soil_params': (spec['soil'].get('params') if env.soil_mode != 'rigid' else None),
               'scene_signature': env.scene_signature()}
    applied['soil_hash'] = hashlib.sha256(
        json.dumps(applied['soil_params'], sort_keys=True).encode()).hexdigest()[:12]
    return env, applied


def assets_for(rock, case, obs_dir, out, state_id):
    d = out / rock['id'] / state_id
    vis = json.loads((obs_dir / 'observation.json').read_text())['visible']
    reg = {}
    for name in ('box', 'mirror'):
        try:
            if name == 'box':
                wd, _ = eval_six.plan_box(vis, {'box_depth_m': 0.375}, str(d/'box'))
            else:
                wd, _ = eval_six.plan_mirror({'visible': vis, 'obs_dir': str(obs_dir)},
                                             str(d/'mirror'))
            reg[name] = str(pathlib.Path(wd).relative_to(ROOT))
        except Exception as e:
            reg[name] = None; reg[name+'_error'] = f'{type(e).__name__}: {e}'[:200]
    try:
        Hm, OBS, meta = E.build_elevation(obs_dir, case, E.CELL_M)
        g = E.ground_reference(Hm, OBS, meta)
        for s in ('block', 'fill'):
            bx, info = E.to_boxes(Hm, OBS, meta, s, g, E.CELL_M)
            E.write_asset(d/f'e25d_{s}', bx, meta, info, s, E.CELL_M)
            reg[f'E25D_{s}'] = str((d/f'e25d_{s}').relative_to(ROOT))
    except Exception as e:
        reg['E25D_error'] = f'{type(e).__name__}: {e}'[:200]
    # H5_raw：缩放后的原始 GLB（单列，不替代 H5_F）
    glb = ROOT/'assets/generated'/rock['id']/'extracted/mesh/tex_mesh.glb'
    reg['H5_raw'] = None
    if glb.is_file():
        try:
            import trimesh
            m = trimesh.load(glb, force='mesh', process=True)
            Hv = float(vis['H_vis'])
            m.apply_scale(Hv / max(1e-6, float(m.bounds[1][2]-m.bounds[0][2])))
            m.apply_translation([0,0,-m.bounds[0][2]])
            m.apply_translation([case['obstacle_x'], 0.0, 0.0])
            pw = d/'h5_raw_parent'; pw.mkdir(parents=True, exist_ok=True)
            wp = pw/'body.stl'; m.export(wp)
            cp = subprocess.run([PY_, 'scripts/collision_box_union.py', '--mesh', str(wp),
                                 '--out', str(d/'h5_raw_coll'), '--pitch', '0.0025',
                                 '--hypothesis-id', 'H5_raw'], cwd=str(ROOT),
                                capture_output=True, text=True)
            if (d/'h5_raw_coll'/'manifest.json').is_file():
                reg['H5_raw'] = str((d/'h5_raw_coll').relative_to(ROOT))
                reg['H5_raw_world'] = str(pw.relative_to(ROOT))
            else:
                reg['H5_raw_error'] = (cp.stderr or '')[-200:]
        except Exception as e:
            reg['H5_raw_error'] = f'{type(e).__name__}: {e}'[:200]
    # H5_F：配准 → 观测约束融合 → 碰撞
    reg['H5_F'] = None
    if reg.get('H5_raw_world'):
        try:
            fus = d/'h5f_fused'
            cp = subprocess.run([PY_, 'scripts/fuse_observed.py', '--observation', str(obs_dir),
                                 '--method', 'H5_F', '--parent-world', str(ROOT/reg['H5_raw_world']),
                                 '--parent-id', f"H5F_{rock['id']}_{state_id}",
                                 '--out', str(fus), '--pitch', '0.0025',
                                 '--config', 'configs/unseen_v7_r1_fusion_gapfill.json'],
                                cwd=str(ROOT), capture_output=True, text=True)
            if (fus/'occ.npz').is_file():
                cp2 = subprocess.run([PY_, 'scripts/collision_box_union.py', '--occupancy',
                                      str(fus/'occ.npz'), '--out', str(d/'h5f_coll'),
                                      '--pitch', '0.0025', '--hypothesis-id', 'H5_F'],
                                     cwd=str(ROOT), capture_output=True, text=True)
                if (d/'h5f_coll'/'manifest.json').is_file():
                    reg['H5_F'] = str((d/'h5f_coll').relative_to(ROOT))
                    reg['H5_F_fused'] = str((fus).relative_to(ROOT))
                else:
                    reg['H5_F_error'] = (cp2.stderr or '')[-200:]
            else:
                reg['H5_F_error'] = (cp.stderr or '')[-200:]
        except Exception as e:
            reg['H5_F_error'] = f'{type(e).__name__}: {e}'[:200]
    return reg, vis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rocks', required=True)
    ap.add_argument('--states', default='S1,S2,S3')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    states, planning_soils, exec_soil = frozen()
    pool = {r['id']: r for r in json.loads((ROOT/'assets/procedural_rocks/index.json').read_text())['rocks']}
    case = json.loads((ROOT/'cases/unseen_v1/R02.json').read_text())
    out = ROOT/a.out; out.mkdir(parents=True, exist_ok=True)
    table = {'schema': 'rock-families/v2', 'planning_soils': planning_soils,
             'execution_soil': exec_soil,
             'initial_states': {k: v for k, v in states.items()},
             'candidate_scope': '固定首候选（每块一个生成候选）', 'rows': {}}
    fams = [('B1_height','rule'), ('B2_F','box'), ('B3_F','mirror'),
            ('E25D_block','E25D_block'), ('E25D_fill','E25D_fill'),
            ('H5_raw','H5_raw'), ('H5_F','H5_F'), ('U_truth', None)]
    for rid in a.rocks.split(','):
        rock = pool[rid]
        for sid in a.states.split(','):
            st = states[sid]; key = f'{rid}|{sid}'
            env, applied = build_env(rock, case, st['seed'], st['lateral_m'],
                                     st['yaw_rad'], exec_soil)
            od = out/rid/sid/'obs'; observe.capture_observation(env, od, case_id=rid)
            snap = env.save_state()
            reg, vis = assets_for(rock, case, od, out, sid)
            rec = {'rock': rid, 'state': sid, 'applied': applied,
                   'state_hash': snap.get('state_hash'),
                   'visible': vis, 'assets': reg, 'rows': {}}
            for fam, akey in fams:
                if akey == 'rule':
                    act, why = eval_six.plan_height(vis, {'climb_direct':1.0,'climb_leg':1.6,
                                                          'wheel_r':0.08595})
                    rec['rows'][fam] = {'status':'planned','chosen':act,'cells':None,
                                        'evidence':why, 'applied':applied}
                else:
                    asset = None if akey is None else reg.get(akey)
                    if akey is not None and not asset:
                        rec['rows'][fam] = {'status':'asset_missing',
                                            'error': reg.get(akey+'_error')}
                        continue
                    def builder(h, soil, asset=asset):
                        objs = None
                        if asset is not None:
                            cd = CA.resolve(asset)['collision_dir']
                            objs = [{'posed_dir': str(ROOT/cd)}]
                        e, ap2 = build_env(rock, case, st['seed'], st['lateral_m'],
                                           st['yaw_rad'], soil, objects=objs)
                        return e
                    try:
                        p = CP.plan_action([{'id':fam,'kind':fam,'collision_dir':asset or ''}],
                                           snap, vis, planning_soils, 30.0, builder,
                                           goal_x=case['goal_x'], seed=st['seed'])
                        dd = out/rid/sid/fam; dd.mkdir(parents=True, exist_ok=True)
                        CP.write_plan(p, dd)
                        act = p['decision']['chosen']
                        rec['rows'][fam] = {'status':'planned','chosen':act,
                                            'cells':p['counts']['rows'],
                                            'errors':p['decision'].get('rehearsal_errors'),
                                            'safe_set':p['decision'].get('safe_set'),
                                            'applied':applied}
                    except Exception as e:
                        rec['rows'][fam] = {'status':'error',
                                            'error':f'{type(e).__name__}: {e}'[:200]}
                        continue
                # 真实执行：恢复同一快照
                env3, _ = build_env(rock, case, st['seed'], st['lateral_m'],
                                    st['yaw_rad'], exec_soil)
                env3.restore_state(snap, mode='same_scene')
                r = runner.EpisodeRunner(env3, skills.make_skill(act), visible=vis,
                                         seed=st['seed'], record_trajectory=True).run_current()
                fr = r.get('trajectory') or []
                d3 = out/rid/sid/fam; d3.mkdir(parents=True, exist_ok=True)
                if fr:
                    (d3/'trajectory.jsonl').write_text(
                        '\n'.join(json.dumps(f, ensure_ascii=False) for f in fr)+'\n')
                rec['rows'][fam].update({'success':bool(r.get('success')),
                                         'reason':r.get('reason'),
                                         'final_x':r.get('final_x'),'frames':len(fr)})
                print(json.dumps({'rock':rid,'state':sid,'family':fam,'chosen':act,
                                  'ok':bool(r.get('success'))}, ensure_ascii=False), flush=True)
            table['rows'][key] = rec
            (out/'table.json').write_text(json.dumps(table, ensure_ascii=False, indent=2))
    print('done', len(table['rows']))

if __name__ == '__main__':
    main()
