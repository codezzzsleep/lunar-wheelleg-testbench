"""v2 八行主表的非 Lux3D 六行：B1_height / B2_F / B3_F / E25D_block / E25D_fill / U_truth。

同一状态、同一观测、同一土壤集合、同一 30 s 预算、同一真值执行口径。
资产可以来自既有 grid 目录（B2_F/B3_F/E25D_*），也可以来自 v7_rock_families
新生成的 box/mirror/e25d_* 目录；U_truth 直接用真值场景，不需要资产。

  python scripts/v2_nonlux_rows.py --rock P06 --state S1 --obs <obs> \
      --assets <grid or table state dir> --out <dir> --soils nominal
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import collision_asset as CA
import common_planner as CP
import eval_six
import runner
import skills
from v2_multi import build_env

FAMILIES = [
    ('B1_height', None),
    ('B2_F', ('B2_F', 'box')),
    ('B3_F', ('B3_F', 'mirror')),
    ('E25D_block', ('E25D_block', 'e25d_block')),
    ('E25D_fill', ('E25D_fill', 'e25d_fill')),
    ('U_truth', None),
]


def find_asset(root, names):
    for name in names:
        for cand in (root / name, root / name / 'coll', root / name / name):
            if (cand / 'manifest.json').is_file():
                return cand
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rock', required=True)
    ap.add_argument('--state', default='S1')
    ap.add_argument('--obs', required=True)
    ap.add_argument('--assets', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--soils', default='nominal')
    a = ap.parse_args()
    st = {s['id']: s for s in json.loads(
        (ROOT / 'plans/rock_initial_states.json').read_text())['states']}[a.state]
    rock = {r['id']: r for r in json.loads(
        (ROOT / 'assets/procedural_rocks/index.json').read_text())['rocks']}[a.rock]
    case = json.loads((ROOT / 'cases/unseen_v1/R02.json').read_text())
    obs = (ROOT / a.obs).resolve()
    vis = json.loads((obs / 'observation.json').read_text())['visible']
    assets_root = (ROOT / a.assets).resolve()
    soils = [s.strip() for s in a.soils.split(',') if s.strip()]
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    env = build_env(rock, case, st['seed'], (st['lateral_m'], st['yaw_rad']), 'nominal')
    snap = env.save_state()
    res = {'schema': 'v2-nonlux/v1', 'rock': a.rock, 'state': a.state,
           'observation': a.obs, 'assets_root': a.assets,
           'planning_soils': soils, 'state_hash': snap.get('state_hash'),
           'visible': vis, 'rows': {}}

    def execute(fam, act):
        e2 = build_env(rock, case, st['seed'], (st['lateral_m'], st['yaw_rad']), 'nominal')
        e2.restore_state(snap, mode='same_scene')
        r = runner.EpisodeRunner(e2, skills.make_skill(act), visible=vis,
                                 seed=st['seed']).run_current()
        return {'success': bool(r.get('success')), 'reason': r.get('reason'),
                'final_x': r.get('final_x')}

    for fam, names in FAMILIES:
        if fam == 'B1_height':
            act, why = eval_six.plan_height(
                vis, {'climb_direct': 1.0, 'climb_leg': 1.6, 'wheel_r': 0.08595})
            row = {'status': 'planned', 'chosen': act, 'evidence': why,
                   'cells': None, 'planning_soils': soils}
            row.update(execute(fam, act))
            res['rows'][fam] = row
            print(json.dumps({'family': fam, **row}, ensure_ascii=False), flush=True)
            continue
        asset = None if names is None else find_asset(assets_root, names)
        if names is not None and not asset:
            res['rows'][fam] = {'status': 'asset_missing',
                                'searched': [str(assets_root / n) for n in names]}
            print(json.dumps({'family': fam, 'status': 'asset_missing'},
                             ensure_ascii=False), flush=True)
            continue

        def builder(h, soil, asset=asset):
            objs = None
            if asset is not None:
                cd = CA.resolve(str(asset))['collision_dir']
                objs = [{'posed_dir': str(ROOT / cd)}]
            return build_env(rock, case, st['seed'],
                             (st['lateral_m'], st['yaw_rad']), soil, objects=objs)

        try:
            p = CP.plan_action([{'id': fam, 'kind': fam,
                                 'collision_dir': str(asset) if asset else ''}],
                               snap, vis, soils, 30.0, builder,
                               goal_x=case['goal_x'], seed=st['seed'])
            dd = out / fam
            dd.mkdir(parents=True, exist_ok=True)
            CP.write_plan(p, dd)
            act = p['decision']['chosen']
            row = {'status': 'planned', 'chosen': act,
                   'cells': p['counts']['rows'],
                   'safe_set': p['decision'].get('safe_set'),
                   'errors': p['decision'].get('rehearsal_errors'),
                   'asset': (str(asset.relative_to(ROOT)) if asset else None),
                   'planning_soils': soils}
            row.update(execute(fam, act))
            res['rows'][fam] = row
            print(json.dumps({'family': fam, 'chosen': act,
                              'ok': row['success']}, ensure_ascii=False), flush=True)
        except Exception as e:
            res['rows'][fam] = {'status': 'error',
                                'error': f'{type(e).__name__}: {e}'[:400]}
            print(json.dumps({'family': fam, 'status': 'error',
                              'error': str(e)[:200]}, ensure_ascii=False), flush=True)
    (out / 'nonlux.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({'rows': {k: v.get('chosen') for k, v in res['rows'].items()}},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
