"""v2 土壤对照 C：当前土壤（nominal）附近的小范围扰动。

在 nominal 参数上按冻结比例生成四个角点 + 中心（共 5 点），对每个状态、
每个动作真实预演，判断是否存在**在全部 5 点上通过**的动作。

  python scripts/v2_soil_c.py --rocks P06,P29 --states S1,S2 --out <dir>
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import runner, skills, v7_holdout_scan as HS, v7_soil, wheelleg_env

PERT = 0.10

def nominal_params():
    r = v7_soil.resolve('nominal')
    return dict(r['params'])

def points(base):
    keys = ['mu_eff', 'b_eff']
    keys = [k for k in keys if k in base] or [k for k in base if isinstance(base[k], (int, float))][:2]
    pts = []
    for dy in (-1, 1):
        for dx in (-1, 1):
            p = dict(base)
            for k, s in zip(keys, (dx, dy)):
                p[k] = float(base[k]) * (1 + s*PERT)
            pts.append(p)
    pts.append(dict(base))
    return keys, pts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rocks', required=True); ap.add_argument('--states', default='S1,S2,S3')
    ap.add_argument('--actions', default='R1,R2,L1,L2,D1,D2')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    states = {s['id']: s for s in json.loads((ROOT/'plans/rock_initial_states.json').read_text())['states']}
    pool = {r['id']: r for r in json.loads((ROOT/'assets/procedural_rocks/index.json').read_text())['rocks']}
    case = json.loads((ROOT/'cases/unseen_v1/R02.json').read_text())
    base = nominal_params(); keys, pts = points(base)
    out = ROOT/a.out; out.mkdir(parents=True, exist_ok=True)
    res = {'schema':'v2-soil-c/v1','perturbation':PERT,'keys':keys,
           'base_params':base,'points':pts,'states':{}}
    for rid in a.rocks.split(','):
        rock = pool[rid]
        for sid in a.states.split(','):
            st = states[sid]; key = f'{rid}|{sid}'
            row = {}
            for act in a.actions.split(','):
                outs = []
                for pi, p in enumerate(pts):
                    env = HS.make_env_for_rock(rock, case)
                    spec = dict(env.spec); spec['soil'] = {'mode':'soil','label':'C','params':p}
                    env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
                    env.init_perturbation = {'lateral': abs(st['lateral_m']), 'yaw': abs(st['yaw_rad'])}
                    env.reset(seed=st['seed'])
                    r = runner.EpisodeRunner(env, skills.make_skill(act), visible={}, seed=st['seed']).run_current()
                    outs.append('success' if r.get('success') else ('abort' if r.get('abort') else 'failure'))
                row[act] = {'outcomes': outs, 'robust': all(o == 'success' for o in outs)}
            res['states'][key] = {'actions': row,
                                  'robust_actions': sorted(k for k, v in row.items() if v['robust'])}
            (out/'soil_c.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
            print(json.dumps({'state': key, 'robust': res['states'][key]['robust_actions']}, ensure_ascii=False), flush=True)
    print('done', len(res['states']))

if __name__ == '__main__':
    main()
