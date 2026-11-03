"""生产入口验证：采样后修改仿真数组，已入队/已落盘的帧必须保持不变。"""
import json
import pathlib
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import terrain            # noqa: E402
import v7_soil            # noqa: E402
import wheelleg_env       # noqa: E402
import v3_record          # noqa: E402
import v3_basic_cycle as bc  # noqa: E402

LEG = bc.LEG
STANCE = {leg: dict(bc.STANCE) for leg in LEG}


def main():
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=3.0, name='rec_selftest')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('rigid')
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=10.0)
    env.reset(seed=0)
    out = pathlib.Path(tempfile.mkdtemp(prefix='rec_selftest_'))
    rec = v3_record.Recorder(out / 'record', {'scenario': 'rec_selftest'}, hz=50.0,
                             chunk_frames=3)
    saved = []
    for k in range(7):
        env.step_command(joint_targets_rad=STANCE, wheel_mode='coast')
        frame = v3_record.frame_from_env(env, None, np.zeros(3), k, env.t)
        saved.append({'qpos': frame['qpos'].copy(), 'qvel': frame['qvel'].copy(),
                      'wheel_torque': None if frame['wheel_torque'] is None
                      else frame['wheel_torque'].copy()})
        rec.add(frame)
        # 采样后立刻原地改仿真数组：模拟后续物理步
        env.data.qpos[0] += 0.5
        env.data.qvel[1] += 1.0
        env.data.actuator_force[0] += 5.0
    info = rec.close()
    chunks = sorted((out / 'record').glob('chunk_*.npz'))
    got = np.concatenate([np.load(c)['qpos'] for c in chunks], axis=0)
    ok = len(got) == len(saved)
    diffs = []
    for i in range(min(len(got), len(saved))):
        # 记录器按 float32 落盘；与 float32 快照比对，验证的是"不再是 view"，
        # 不是 float64 精度。若仍是 view，diff 会是 0.5 量级。
        d = float(np.max(np.abs(got[i] - np.asarray(saved[i]['qpos'], np.float32))))
        diffs.append(d)
        ok = ok and d <= 1e-6
    res = {'schema': 'v3-record-selftest/v1', 'ok': bool(ok),
           'frames': len(saved), 'chunks': len(chunks),
           'max_qpos_diff': max(diffs) if diffs else None,
           'trajectory': info, 'out': str(out)}
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
