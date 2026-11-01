"""碰撞按决策等价使用（下一批任务书 §6）。

同一资产、同一状态、同一预算，只把碰撞表示变粗一档（占据 2×2×2 合并 → 5 mm box），
比较**选中动作**与**执行结论**是否改变：

  decision_changed / outcome_changed = false  → 选用较粗表示，注明适用条件；
  任一 changed                                → 该资产标 representation_sensitive，
                                                 用参考表示，不拖住其他对象。

不新增验收器，不再追求 IoU 0.95 或固定 2 mm；旧 IoU 只在附录里引用。

  python scripts/v7_collision_equiv.py --config R02_s0.9 --asset <occ 所在目录> --out <dir>
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np

import common_planner as CP
import runner
import skills
import v7_common_matrix as MX

PY = sys.executable
BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'


def downsample(occ, factor=2):
    """2×2×2 合并（OR），返回粗一档的占据与新的 dims/origin（cell-center 约定不变）。"""
    n = np.array(occ.shape)
    pad = (-n) % factor
    if pad.any():
        occ = np.pad(occ, [(0, int(p)) for p in pad], constant_values=False)
    s = occ.shape
    shr = occ.reshape(s[0] // factor, factor, s[1] // factor, factor,
                      s[2] // factor, factor)
    return shr.any(axis=(1, 3, 5))


def build_coarse(occ_path, out_dir, factor=2):
    d = np.load(occ_path)
    occ = d['occupied'].astype(bool)
    pitch = float(d['pitch'])
    origin = np.asarray(d['origin'], dtype=float)
    coarse = downsample(occ, factor)
    # 粗格覆盖原细格范围：origin 保持，pitch *= factor
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    npz = out_dir / 'occ_coarse.npz'
    np.savez_compressed(npz, occupied=coarse, origin=origin, pitch=pitch * factor,
                        dims=np.array(coarse.shape),
                        convention=str(d['convention']),
                        algorithm='downsample-or/%d' % factor,
                        parent_id=str(d['parent_id']) + f'_coarse{factor}',
                        observation_sha=str(d['observation_sha']),
                        config_sha=str(d['config_sha']),
                        content_sha='coarse-%d' % factor)
    r = subprocess.run([PY, 'scripts/collision_box_union.py', '--occupancy', str(npz),
                        '--out', str(out_dir / 'collision'), '--pitch', str(pitch * factor),
                        '--hypothesis-id', f'coarse{factor}'],
                       cwd=str(ROOT), capture_output=True, text=True)
    return {'occ': str(npz.relative_to(ROOT)) if npz.is_relative_to(ROOT) else str(npz),
            'collision_dir': str((out_dir / 'collision').relative_to(ROOT))
            if (out_dir / 'collision').is_relative_to(ROOT) else str(out_dir / 'collision'),
            'pitch_m': pitch * factor, 'factor': factor,
            'n_boxes': (json.loads((out_dir / 'collision' / 'manifest.json').read_text())
                        .get('n_boxes') if (out_dir / 'collision' / 'manifest.json').is_file()
                        else None),
            'rc': r.returncode, 'err': (r.stderr or '')[-300:]}


def decide_and_run(family, asset, cfg, soil, seed, snap, vis, goal_x, budget, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    hyps = [{'id': family, 'kind': family, 'collision_dir': asset}]
    p = CP.plan_action(hyps, snap, vis, [soil], budget,
                       (lambda h, s: MX.build_env(cfg, s, collision_dir=asset)),
                       goal_x=goal_x, seed=seed)
    CP.write_plan(p, out_dir)
    act = p['decision']['chosen']
    (out_dir / 'decision.json').write_text(json.dumps(p['decision'], ensure_ascii=False,
                                                      indent=2))
    env = MX.build_env(cfg, soil, collision_dir=MX.truth_collision_for(cfg))
    env.reset(seed=seed)
    env.restore_state(snap, mode='same_scene')
    r = runner.EpisodeRunner(env, skills.make_skill(act), visible=vis, seed=seed,
                             record_trajectory=True).run_current()
    return {'family': family, 'asset': asset, 'chosen': act,
            'safe_set': p['decision'].get('safe_set'), 'cells': p['counts']['rows'],
            'success': bool(r.get('success')), 'reason': r.get('reason'),
            'final_x': r.get('final_x'),
            'outcome': ('pass' if r.get('success') else
                        ('safe_abandon' if act == 'A0' else 'fail'))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--soil', default='nominal')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--assets', required=True,
                    help='逗号分隔：family=occ_dir（occ.npz 所在目录）')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out_root = ROOT / a.out if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    out_root.mkdir(parents=True, exist_ok=True)
    plan = json.loads((ROOT / 'plans/r1_states_plan.json').read_text())
    cfg = next(c for c in plan['configs'] if c['config_id'] == a.config)
    unit = ROOT / BATCH / 'common_states' / a.config / a.soil / f'seed{a.seed}'
    acq = json.loads((unit / 'acquisition.json').read_text())
    snap = json.loads((ROOT / acq['state']['snapshot']).read_text())
    vis = acq.get('visible') or {}
    goal_x = json.loads((ROOT / cfg['case_config']).read_text())['goal_x']
    budget = float(cfg.get('budget_s', 30.0))

    rows = []
    for spec in a.assets.split(','):
        family, occ_dir = spec.split('=', 1)
        occ_path = ROOT / occ_dir / 'occ.npz'
        if not occ_path.is_file():
            rows.append({'family': family, 'error': f'缺 occ.npz：{occ_dir}'})
            continue
        ref = occ_dir
        coarse = build_coarse(occ_path, out_root / family / 'coarse')
        r_ref = decide_and_run(family, ref, cfg, a.soil, a.seed, snap, vis, goal_x,
                               budget, out_root / family / 'reference')
        r_co = decide_and_run(family, coarse['collision_dir'], cfg, a.soil, a.seed, snap,
                              vis, goal_x, budget, out_root / family / 'coarse_run')
        changed_decision = r_ref['chosen'] != r_co['chosen']
        changed_outcome = r_ref['outcome'] != r_co['outcome']
        rows.append({'family': family, 'reference': r_ref, 'coarse': r_co,
                     'coarse_asset': coarse,
                     'decision_changed': changed_decision,
                     'outcome_changed': changed_outcome,
                     'representation_sensitive': bool(changed_decision or changed_outcome),
                     'adopt': ('coarse' if not (changed_decision or changed_outcome)
                               else 'reference')})
        print(json.dumps({'family': family, 'ref': r_ref['chosen'],
                          'coarse': r_co['chosen'],
                          'sensitive': rows[-1]['representation_sensitive']},
                         ensure_ascii=False), flush=True)
    out = {'schema': 'collision-equivalence/v1', 'config': a.config, 'soil': a.soil,
           'seed': a.seed, 'state_hash': snap.get('state_hash'),
           'criterion': ('选中动作与执行结论是否随碰撞表示变粗而改变；'
                         '旧 IoU/距离仅在附录引用，不作门槛'),
           'rows': rows}
    (out_root / 'equivalence.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({r['family']: r.get('adopt') for r in rows if 'adopt' in r},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
