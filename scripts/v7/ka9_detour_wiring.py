"""KA9：绕行几何计划必须真正生效。偏移 0.45 / 0.75 两档，最大横移应随之变化；回位点后移，回到中线的 x 也要后移。"""
import sys, json, pathlib, numpy as np
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import wheelleg_env, v3_core
spec = {'name': 'ka9', 'seed': 0, 'split': 'train', 'start': [0.0, 0.0], 'goal_x': 3.2,
        'terrain': {'kind': 'flat', 'slope_deg': 0.0, 'span': None, 'roughness': 0.0, 'pits': 0, 'pit_depth': 0.0},
        'objects': [], 'channel': {'center_y': 0.0, 'half_width': 1.2}}
vis = {'x_front': 1.2, 'W_vis': 0.27, 'H_vis': 0.2}
rows = []
for off, leave in ((0.45, 1.6), (0.75, 1.6), (0.75, 2.3)):
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=20); env.reset(seed=0); snap = env.save_state()
    out = ROOT / f'runs/v7/ka9/off{off}_leave{leave}'
    r = v3_core.run_action(env, snap, 'D1', vis, mode='same_scene', record_dir=out, params={'offset_m': off, 'leave_x': leave})
    q = np.concatenate([np.load(f)['qpos'] for f in sorted(out.glob('chunk_*.npz'))])
    ymax = float(q[:, 1].max()); i = int(np.argmax(q[:, 1]))
    back = q[i:][np.abs(q[i:, 1]) < 0.1]
    rows.append({'offset_m': off, 'leave_x': leave, 'y_max': round(ymax, 3), 'x_at_ymax': round(float(q[i, 0]), 3),
                 'x_back_to_center': round(float(back[0, 0]), 3) if len(back) else None, 'success': r['success']})
    print(rows[-1])
ok = (abs(rows[0]['y_max'] - 0.45) < 0.12 and abs(rows[1]['y_max'] - 0.75) < 0.12
      and rows[2]['x_back_to_center'] is not None and rows[1]['x_back_to_center'] is not None
      and rows[2]['x_back_to_center'] > rows[1]['x_back_to_center'] + 0.4)
print('KA9', 'PASS' if ok else 'FAIL')
(ROOT / 'runs/v7/ka9/ka9.json').write_text(json.dumps({'rows': rows, 'pass': ok}, indent=2))
