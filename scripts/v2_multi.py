"""v2 多候选：同一观测组的 6 个候选 → 融合/碰撞/预演 → 单候选 vs 多候选。

  python scripts/v2_multi.py --rock P06 --state S1 --obs <obs dir> --cands <dir> --out <dir>
"""
import argparse, json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import collision_asset as CA, common_planner as CP, observe, runner, skills
import v7_holdout_scan as HS, v7_common_matrix as MX, v7_soil, wheelleg_env

PY_ = sys.executable
SOILS_CURRENT = ('nominal',)          # v2 正式口径：按当前土壤规划
SOILS_ABLATION = ('nominal', 'low_traction', 'high_drag')  # 仅开发消融

def build_env(rock, case, seed, pose, soil, objects=None):
    env = HS.make_env_for_rock(rock, case)
    r = v7_soil.resolve(soil)
    spec = dict(env.spec)
    spec['soil'] = ({'mode':'rigid','label':soil} if r.get('mode')=='rigid'
                    else {'mode':'soil','label':r.get('label'),'params':r['params']})
    if objects is not None:
        spec['objects'] = objects
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
    env.init_perturbation = {'lateral': abs(pose[0]), 'yaw': abs(pose[1])}
    env.reset(seed=seed)
    return env

def prep_raw(glb, rock, case, out, tag, vis):
    import trimesh
    d = out/tag; d.mkdir(parents=True, exist_ok=True)
    m = trimesh.load(glb, force='mesh', process=True)
    Hv = float(vis['H_vis'])
    m.apply_scale(Hv/max(1e-6, float(m.bounds[1][2]-m.bounds[0][2])))
    m.apply_translation([0,0,-m.bounds[0][2]])
    m.apply_translation([case['obstacle_x'], 0.0, 0.0])
    pw = d/'parent'; pw.mkdir(exist_ok=True); m.export(pw/'body.stl')
    return str((pw/'body.stl').relative_to(ROOT))


def prep(glb, rock, case, obs_dir, out, tag, vis):
    """GLB → 世界父 → 观测融合 → 碰撞。返回资产目录或 None。"""
    import trimesh
    d = out/tag; d.mkdir(parents=True, exist_ok=True)
    m = trimesh.load(glb, force='mesh', process=True)
    Hv = float(vis['H_vis'])
    m.apply_scale(Hv/max(1e-6, float(m.bounds[1][2]-m.bounds[0][2])))
    m.apply_translation([0,0,-m.bounds[0][2]])
    m.apply_translation([case['obstacle_x'], 0.0, 0.0])
    pw = d/'parent'; pw.mkdir(exist_ok=True); m.export(pw/'body.stl')
    fus = d/'fused'
    subprocess.run([PY_,'scripts/fuse_observed.py','--observation',str(obs_dir),'--method','H5_F',
                    '--parent-world',str(pw),'--parent-id',tag,'--out',str(fus),'--pitch','0.0025',
                    '--config','configs/unseen_v7_r1_fusion_gapfill.json'],
                   cwd=str(ROOT), capture_output=True)
    if not (fus/'occ.npz').is_file():
        return None
    subprocess.run([PY_,'scripts/collision_box_union.py','--occupancy',str(fus/'occ.npz'),
                    '--out',str(d/'coll'),'--pitch','0.0025','--hypothesis-id',tag],
                   cwd=str(ROOT), capture_output=True)
    return str((d/'coll').relative_to(ROOT)) if (d/'coll'/'manifest.json').is_file() else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rock', required=True); ap.add_argument('--state', default='S1')
    ap.add_argument('--obs', required=True); ap.add_argument('--cands', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--soils', default='current',
                    choices=('current', 'ablation'),
                    help='current=只按当前土壤（v2 正式）；ablation=三档（开发消融）')
    ap.add_argument('--no-fuse', action='store_true',
                    help='不做观测融合，直接用原始 GLB 世界网格作为几何')
    a = ap.parse_args()
    st = {s['id']: s for s in json.loads((ROOT/'plans/rock_initial_states.json').read_text())['states']}[a.state]
    rock = {r['id']: r for r in json.loads((ROOT/'assets/procedural_rocks/index.json').read_text())['rocks']}[a.rock]
    case = json.loads((ROOT/'cases/unseen_v1/R02.json').read_text())
    obs_dir = ROOT/a.obs
    vis = json.loads((obs_dir/'observation.json').read_text())['visible']
    out = ROOT/a.out; out.mkdir(parents=True, exist_ok=True)
    env = build_env(rock, case, st['seed'], (st['lateral_m'], st['yaw_rad']), 'nominal')
    snap = env.save_state()
    glbs = sorted((ROOT/a.cands/'raw').glob('*/results.zip'))
    cands = {}
    for z in glbs:
        tag = z.parent.name
        ext = z.parent/'mesh'/'tex_mesh.glb'
        if not ext.is_file():
            import zipfile
            with zipfile.ZipFile(z) as f: f.extractall(z.parent)
        if ext.is_file():
            asset = (prep_raw(ext, rock, case, out, tag, vis) if a.no_fuse
                     else prep(ext, rock, case, obs_dir, out, tag, vis))
            cands[tag] = asset
    res = {'schema':'v2-multi/v2','rock':a.rock,'state':a.state,'candidates':cands,
           'planning_soils': (list(SOILS_CURRENT) if a.soils=='current' else list(SOILS_ABLATION)),
           'soil_label': ('current' if a.soils=='current' else 'three_level_ablation'),
           'state_hash': snap.get('state_hash'), 'visible': vis, 'rows': {}}
    def run(tags, tag):
        assets = {t: cands[t] for t in tags if cands.get(t)}
        if not assets: return None
        hyps = [{'id': t, 'kind': 'lux3d', 'collision_dir': assets[t]} for t in assets]
        raw = a.no_fuse
        def builder(h, soil):
            v = assets[h['id']]
            objs = ([{'mesh_file': str(ROOT/v), 'x': 0.0, 'y': 0.0, 'yaw_deg': 0.0}]
                    if raw else
                    [{'posed_dir': str(ROOT/CA.resolve(v)['collision_dir'])}])
            return build_env(rock, case, st['seed'], (st['lateral_m'], st['yaw_rad']), soil,
                             objects=objs)
        soils = list(SOILS_CURRENT if a.soils == 'current' else SOILS_ABLATION)
        p = CP.plan_action(hyps, snap, vis, soils, 30.0, builder,
                           goal_x=case['goal_x'], seed=st['seed'])
        dd = out/tag; dd.mkdir(exist_ok=True); CP.write_plan(p, dd)
        act = p['decision']['chosen']
        e2 = build_env(rock, case, st['seed'], (st['lateral_m'], st['yaw_rad']), 'nominal')
        e2.restore_state(snap, mode='same_scene')
        r = runner.EpisodeRunner(e2, skills.make_skill(act), visible=vis, seed=st['seed']).run_current()
        return {'chosen': act, 'cells': p['counts']['rows'], 'n_candidates': len(assets),
                'safe_set': p['decision'].get('safe_set'),
                'success': bool(r.get('success')), 'reason': r.get('reason'),
                'errors': p['decision'].get('rehearsal_errors')}
    first = sorted(cands)[0] if cands else None
    if first: res['rows']['first'] = run([first], 'first')
    res['rows']['multi'] = run(sorted(cands), 'multi')
    (out/'multi.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res['rows'], ensure_ascii=False))

if __name__ == '__main__':
    main()
