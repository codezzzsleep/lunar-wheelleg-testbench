"""
V6 工作包 I1：为实际执行回合记录连续轨迹（qpos/qvel/action/contacts）。
渲染只读记录，不在渲染中推进物理。
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import skills
import terrain
import wheelleg_env
from runner import EpisodeRunner

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sha(p):
    h = hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()


def run(collision, option, seed, visible, out, label, goal_x=2.6, time_limit=30.0):
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=goal_x,
                             name='v6_traj_' + label)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(collision)}]
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=time_limit,
                                   v_ref=1.0, tip_deg=60.0)
    r = EpisodeRunner(env, skills.make_skill(option), visible=visible, seed=seed,
                      record_trajectory=True)
    res = r.run_with_seed(seed)
    payload = {
        'schema': 'trajectory/v1', 'label': label, 'option': option, 'seed': seed,
        'collision': str(collision), 'collision_sha': sha(pathlib.Path(collision) / 'manifest.json'),
        'time_limit_s': time_limit, 'goal_x': goal_x,
        'initial_full_hash': res.get('initial_full_hash'),
        'initial_qpos': res.get('initial_qpos'), 'initial_qvel': res.get('initial_qvel'),
        'result': {k: res.get(k) for k in ('reason', 'success', 'abort', 't_end',
                                            'final_x', 'max_tilt', 'contact',
                                            'control_steps', 'physics_steps')},
        'frames': res.get('trajectory'),
        'note': ('轨迹来自实际 runner；回放只恢复 qpos/qvel 渲染，不推进物理。'
                 if label.startswith('truth') else
                 '候选预演轨迹；不是独立真值成功。'),
    }
    out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False))
    print(json.dumps({'label': label, 'reason': res.get('reason'),
                      'frames': len(res.get('trajectory') or []),
                      't_end': res.get('t_end'), 'out': str(out)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--collision', required=True)
    ap.add_argument('--option', required=True)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--observation', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', required=True)
    a = ap.parse_args()
    visible = json.loads((pathlib.Path(a.observation) / 'observation.json').read_text())['visible']
    run(a.collision, a.option, a.seed, visible, a.out, a.label)


if __name__ == '__main__':
    main()
