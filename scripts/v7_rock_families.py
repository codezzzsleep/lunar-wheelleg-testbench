"""石头七行比较（复用正式处理链）：每（石头, 初态）一张表。"""
import argparse, json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np
import collision_asset as CA, common_planner as CP, eval_six, observe, runner, skills
import v7_elev25d as E, v7_holdout_scan as HS, v7_common_matrix as MX
POSES = {7: (0.04, 0.03), 11: (0.05, 0.04), 13: (0.06, 0.05)}
SOILS = ('nominal', 'low_traction', 'high_drag')

def build_env(rock, case, pose, objects=None):
    import wheelleg_env
    env = HS.make_env_for_rock(rock, case)
    if objects is not None:
        env.spec['objects'] = objects
        env = wheelleg_env.WheelLegEnv(env.spec, max_seconds=30.0)
    env.init_perturbation = {'lateral': abs(pose[0]), 'yaw': abs(pose[1])}
    env.reset(seed=7)
    return env

def assets_for(rock, case, obs_dir, out, seed):
    d = out / rock['id'] / f'seed{seed}'
    reg, objs, vis, H = {}, {}, json.loads((obs_dir/'observation.json').read_text())['visible'], None
    H = float(vis['H_vis'])
    # 方盒 / 镜像：只用公共可见量
    import observe as _ob
    obs_ctx = {'visible': vis, 'obs_dir': str(obs_dir)}
    for name, fn, args in (('box', eval_six.plan_box, (vis, {'box_depth_m': 0.375})),
                           ('mirror', eval_six.plan_mirror,
                            ({'visible': vis, 'obs_dir': str(obs_dir)},))):
        try:
            wd, _ = fn(*args, str(d/name))
            reg[name] = str(pathlib.Path(wd).relative_to(ROOT)) if pathlib.Path(wd).is_relative_to(ROOT) else str(wd)
        except Exception as e:
            reg[name] = None; reg[name+'_error'] = f'{type(e).__name__}: {e}'[:150]
    # 2.5D：只用观测深度
    try:
        Hm, OBS, meta = E.build_elevation(obs_dir, case, E.CELL_M)
        g = E.ground_reference(Hm, OBS, meta)
        for s in ('block', 'fill'):
            bx, info = E.to_boxes(Hm, OBS, meta, s, g, E.CELL_M)
            E.write_asset(d/f'e25d_{s}', bx, meta, info, s, E.CELL_M)
            reg[f'E25D_{s}'] = str((d/f'e25d_{s}').relative_to(ROOT))
    except Exception as e:
        reg['E25D_error'] = f'{type(e).__name__}: {e}'[:150]
    # Lux3D：GLB → 网格 → 观测约束融合 → 碰撞
    glb = ROOT/'assets/generated'/rock['id']/'extracted/mesh/tex_mesh.glb'
    if glb.is_file():
        try:
            import trimesh
            m = trimesh.load(glb, force='mesh', process=True)
            m.apply_scale(H / max(1e-6, float(m.bounds[1][2]-m.bounds[0][2])))
            m.apply_translation([0,0,-m.bounds[0][2]])
            m.apply_translation([case['obstacle_x'], 0.0, 0.0])
            wp = d/'lux3d_world.stl'; wp.parent.mkdir(parents=True, exist_ok=True); m.export(wp)
            cp = subprocess.run([sys.executable,'scripts/collision_box_union.py','--mesh',str(wp),
                                 '--solid-from-mesh','--out',str(d/'lux3d_coll'),'--pitch','0.0025',
                                 '--hypothesis-id','Lux3D'], cwd=str(ROOT), capture_output=True, text=True)
            if not (d/'lux3d_coll'/'manifest.json').is_file():
                reg['Lux3D_error'] = (cp.stderr or cp.stdout or '')[-200:]
            if (d/'lux3d_coll'/'manifest.json').is_file():
                reg['Lux3D'] = str((d/'lux3d_coll').relative_to(ROOT))
        except Exception as e:
            reg['Lux3D_error'] = f'{type(e).__name__}: {e}'[:150]
    reg['U_truth'] = None
    return reg, vis

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rocks', required=True); ap.add_argument('--seeds', default='7,11,13')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    pool = {r['id']: r for r in json.loads((ROOT/'assets/procedural_rocks/index.json').read_text())['rocks']}
    case = json.loads((ROOT/'cases/unseen_v1/R02.json').read_text())
    out = ROOT/a.out; out.mkdir(parents=True, exist_ok=True)
    table = {'schema':'rock-families/v1','planning_soils':list(SOILS),'execution_soil':'nominal',
             'candidate_scope':'固定首候选（每块一个生成候选）','rows':{}}
    for rid in a.rocks.split(','):
        rock = pool[rid]
        for seed in [int(s) for s in a.seeds.split(',')]:
            pose = POSES[seed]; key = f'{rid}|{seed}'
            env = build_env(rock, case, pose)
            od = out/rid/f'seed{seed}'/'obs'; observe.capture_observation(env, od, case_id=rid)
            snap = env.save_state()
            reg, vis = assets_for(rock, case, od, out, seed)
            rec = {'rock': rid, 'seed': seed, 'state_hash': snap.get('state_hash'),
                   'qpos': [round(float(v),6) for v in env.data.qpos],
                   'qvel': [round(float(v),6) for v in env.data.qvel],
                   'visible': vis, 'assets': reg, 'rows': {}}
            fams = [('B1_height','rule'),('B2_F','box'),('B3_F','mirror'),('E25D_block','E25D_block'),
                    ('E25D_fill','E25D_fill'),('H5_F','Lux3D'),('U_truth',None)]
            for fam, assetkey in fams:
                if assetkey == 'rule':
                    act, _ = eval_six.plan_height(vis, {'climb_direct': 1.0,
                                                        'climb_leg': 1.6, 'wheel_r': 0.08595})
                    dd = out/rid/f'seed{seed}'/fam; dd.mkdir(parents=True, exist_ok=True)
                    (dd/'decision.json').write_text(json.dumps({'chosen': act,
                        'rule': 'height'}, ensure_ascii=False, indent=2))
                    env3 = build_env(rock, case, pose); env3.restore_state(snap, mode='same_scene')
                    r = runner.EpisodeRunner(env3, skills.make_skill(act), visible=vis,
                                             seed=7, record_trajectory=True).run_current()
                    fr = r.get('trajectory') or []
                    if fr:
                        (dd/'trajectory.jsonl').write_text(
                            '\n'.join(json.dumps(f, ensure_ascii=False) for f in fr)+'\n')
                    rec['rows'][fam] = {'status':'planned','chosen':act,'cells':None,
                                        'success':bool(r.get('success')),'reason':r.get('reason'),
                                        'final_x':r.get('final_x'),'frames':len(fr)}
                    print(json.dumps({'rock':rid,'seed':seed,'family':fam,'chosen':act,
                                      'ok':bool(r.get('success'))}, ensure_ascii=False), flush=True)
                    continue
                asset = None if assetkey is None else reg.get(assetkey)
                if assetkey is not None and not asset:
                    rec['rows'][fam] = {'status':'asset_missing',
                                        'error': reg.get((assetkey or '')+'_error')}
                    continue
                def builder(h, soil, asset=asset, rid=rid, pose=pose, rock=rock):
                    if asset is None: return build_env(rock, case, pose)
                    asset = CA.resolve(asset)['collision_dir'] if not str(asset).endswith('.glb') else asset
                    if str(asset).endswith('.stl'):
                        return build_env(rock, case, pose, objects=[{'mesh_file':str(ROOT/asset)}])
                    return build_env(rock, case, pose, objects=[{'posed_dir':str(ROOT/asset) if not pathlib.Path(asset).is_absolute() else asset}])
                try:
                    p = CP.plan_action([{'id':fam,'kind':fam,'collision_dir':asset or ''}],
                                       snap, vis, list(SOILS), 30.0, builder,
                                       goal_x=case['goal_x'], seed=7)
                    dd = out/rid/f'seed{seed}'/fam; dd.mkdir(parents=True, exist_ok=True)
                    CP.write_plan(p, dd)
                    act = p['decision']['chosen']
                    rec['rows'][fam] = {'status':'planned','chosen':act,'cells':p['counts']['rows'],
                                        'errors':p['decision'].get('rehearsal_errors'),
                                        'safe_set':p['decision'].get('safe_set')}
                except Exception as e:
                    rec['rows'][fam] = {'status':'error','error':f'{type(e).__name__}: {e}'[:200]}
                    continue
                env3 = build_env(rock, case, pose); env3.restore_state(snap, mode='same_scene')
                r = runner.EpisodeRunner(env3, skills.make_skill(act), visible=vis, seed=7,
                                         record_trajectory=True).run_current()
                fr = r.get('trajectory') or []
                if fr:
                    (out/rid/f'seed{seed}'/fam/'trajectory.jsonl').write_text(
                        '\n'.join(json.dumps(f, ensure_ascii=False) for f in fr)+'\n')
                rec['rows'][fam].update({'success':bool(r.get('success')),'reason':r.get('reason'),
                                         'final_x':r.get('final_x'),'frames':len(fr)})
                print(json.dumps({'rock':rid,'seed':seed,'family':fam,'chosen':act,
                                  'ok':bool(r.get('success'))}, ensure_ascii=False), flush=True)
            table['rows'][key] = rec
            (out/'table.json').write_text(json.dumps(table, ensure_ascii=False, indent=2))
    print('done', len(table['rows']))
if __name__ == '__main__':
    main()
