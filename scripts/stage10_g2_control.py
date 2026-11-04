"""G2 正对照：真值网格走同一观测配准入口。"""
import json, pathlib, sys
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_register

def main():
    truth = ROOT / 'runs/v3/stage008/truth_v2'
    out = ROOT / 'runs/v3/stage010/g2_control'; out.mkdir(parents=True, exist_ok=True)
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    mesh_path = truth / 'truth/body_world.stl'
    rec = v3_register.register(str(mesh_path), str(truth / 'observation'), proto, out, top_k=6)
    M = np.asarray(rec['M'], float)
    R = M[:3, :3] / np.cbrt(np.linalg.det(M[:3, :3]))
    ang = float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))
    diag = rec['best']['diagnostics']
    rep = {'schema': 'g2-positive-control/v1', 'input': str(mesh_path),
           'pose_world_expected': 'identity (mesh is already in the truth world frame)',
           'M': M.tolist(), 'rotation_error_deg': round(ang, 3),
           'translation_m': [round(float(x), 5) for x in M[:3, 3]],
           'best_diagnostics': diag, 'n_refined': rec.get('n_refined')}
    (out / 'control.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    sys.exit(main())
