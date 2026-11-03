"""快速可行性探针：真实岩石在小尺度下，现有动作集是否真的能越过。

只用于开发期判断（不产出正式结论）：对指定岩石/档位，从起点跑 7 个可通行动作 + A0，
打印 reason/final_x/t_end。30 s 预算与正式执行一致。
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import skills
import terrain
import runner
import v7_soil
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rocks', nargs='+', default=['moon_rock_02'])
    ap.add_argument('--levels', nargs='+', type=int, default=[1])
    ap.add_argument('--obstacle-x', type=float, default=1.35)
    ap.add_argument('--goal-x', type=float, default=2.9)
    ap.add_argument('--budget', type=float, default=30.0)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    for rid in a.rocks:
        for lvl in a.levels:
            d = ROOT / f'assets/v3/rocks/{rid}/h{lvl}'
            stl = d / 'body.stl'
            meta = json.loads((d / 'meta.json').read_text())
            H = meta['height_m']
            spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=a.goal_x,
                                     name=f'smoke_{rid}_{lvl}')
            spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
            spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
            spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
            spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
            spec['objects'] = [{'mesh_file': str(stl), 'x': a.obstacle_x, 'y': 0.0,
                                'yaw_deg': 0.0, 'target_height_m': H}]
            r = v7_soil.resolve('nominal')
            spec['soil'] = {'mode': 'soil', 'label': r['label'], 'params': r['params']}
            row = {}
            for opt in ['R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2', 'A0']:
                try:
                    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0,
                                                   max_seconds=a.budget, v_ref=1.0,
                                                   tip_deg=60.0)
                    vis = {'x_front': a.obstacle_x - 0.05,
                           'W_vis': float(meta['extents_m'][1]),
                           'H_vis': H}
                    ep = runner.EpisodeRunner(env, skills.make_skill(opt), visible=vis)
                    out = ep.run_with_seed(a.seed)
                    row[opt] = {'reason': out['reason'],
                                'final_x': round(out['final_x'], 3),
                                't': round(out['t_end'] or -1, 2)}
                except Exception as e:  # noqa: BLE001
                    row[opt] = {'error': f'{type(e).__name__}: {e}'}
            print(json.dumps({'rock': rid, 'level': lvl, 'H': round(H, 4),
                              'extents': meta['extents_m'], 'out': row},
                             ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
