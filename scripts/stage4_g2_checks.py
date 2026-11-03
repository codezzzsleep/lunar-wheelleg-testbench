"""G2：三个真实配置 × 三臂（truth / 共享 V / 候选 FULL）的几何与适用性。"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_fuse  # noqa: E402
import stage4_config as S4C  # noqa: E402
import stage4_occ_geometry as G  # noqa: E402

IDS = ['moon_rock_04_h1v0', 'moon_rock_01_h2v0', 'moon_rock_05_h1v1']


def main():
    cfg = S4C.load()
    climb = cfg['climb']
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    rows = []
    for sid in IDS:
        d = ROOT / 'runs/v3/states' / sid
        truth = d / 'truth' / 'truth_occ.npz'
        if not truth.exists():
            v3_fuse.write_truth_occ(d, proto)
        arms = {
            'truth': (truth, True),
            'obs': (d / 'fusion' / 'V.npz', False),
            'full': (d / 'candidates' / 'A1' / 'fused' / 'occ_full.npz', True),
        }
        for arm, (path, assume) in arms.items():
            shell, space, origin, pitch = G.load_occ(path)
            m = G.corridor_metrics(shell, space, origin, pitch, climb,
                                   assume_far_known=assume)
            plan = G.plan_from_metrics(m, f'{arm}_occ', climb)
            rows.append({'state_id': sid, 'arm': arm, 'occ': str(path.relative_to(ROOT)),
                         'metrics': m, 'applicable': plan['applicable'],
                         'reject_reasons': plan['reject_reasons'],
                         'plan_id': plan['plan_id'], 'params': plan['params'],
                         'params_source': plan['param_sources'],
                         'unknowns': plan['unknowns']})
            print(json.dumps({'state': sid, 'arm': arm, 'ok': plan['applicable'],
                              'reasons': plan['reject_reasons']}, ensure_ascii=False))
    out = ROOT / 'runs/v3/stage004/g2_applicability.json'
    out.write_text(json.dumps({'schema': 'stage4-g2/v1', 'climb_cfg': climb,
                               'rows': rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
