#!/usr/bin/env python3
"""Stage008 runnable pack: offline replay + cached-scene simulation. No API, no keys."""
import argparse, json, pathlib, subprocess, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'scripts'))
import mujoco
import terrain, v7_soil, wheelleg_env


def build_env(coll, budget=120.0):
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=2.6,
                             objects=[{'posed_dir': str(coll)}])
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    spec['render'] = {'size': [1280, 720]}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=budget)
    env.reset(seed=0)
    return env


def load_record(rec):
    chunks = sorted(pathlib.Path(rec).glob('chunk_*.npz'))
    if not chunks:
        raise SystemExit(f'no chunks under {rec}')
    q = np.concatenate([np.load(c)['qpos'] for c in chunks])
    t = np.concatenate([np.load(c)['t'] for c in chunks])
    return q, t


def replay(a):
    env = build_env(a.coll)
    q, t = load_record(a.record)
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    frames = out.parent / 'frames'; frames.mkdir(exist_ok=True)
    ren = mujoco.Renderer(env.model, 720, 1280)
    cam = mujoco.MjvCamera(); cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
    cam.trackbodyid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    cam.distance = 1.8; cam.azimuth = 135.0; cam.elevation = -12.0
    t0 = float(t[0]); n = int(min(float(t[-1]) - t0, a.seconds) * a.fps) + 1
    for i in range(n):
        k = min(len(q) - 1, max(0, int(np.searchsorted(t, t0 + i / a.fps))))
        env.data.qpos[:] = q[k][:env.model.nq]
        mujoco.mj_forward(env.model, env.data)
        ren.update_scene(env.data, camera=cam)
        from PIL import Image
        Image.fromarray(ren.render()).save(frames / f'{i:05d}.png')
    ren.close()
    subprocess.check_call(['ffmpeg', '-y', '-v', 'error', '-framerate', str(a.fps),
                           '-i', str(frames / '%05d.png'), '-c:v', 'libx264',
                           '-pix_fmt', 'yuv420p', '-crf', '22', str(out)])
    print(json.dumps({'replay': str(out), 'frames': n, 'fps': a.fps}))


def sim(a):
    env = build_env(a.coll, budget=float(a.seconds) + 10.0)
    sys.path.insert(0, str(HERE / 'scripts'))
    import v3_basic_cycle as bc, stage6_body as SB
    targets = {leg: dict(bc.STANCE) for leg in bc.LEG}
    for _ in range(15):
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
    z0 = float(env.data.qpos[2]); c0 = SB.chassis_min_z(env)
    steps = max(1, int(float(a.seconds) * float(env.control_hz)))
    for _ in range(steps):
        targets = SB.leg_tick_targets(env, targets, 0.06 / steps)
        env.step_command(joint_targets_rad=targets, wheel_mode='coast')
    print(json.dumps({'base_z0': round(z0, 4), 'base_z': round(float(env.data.qpos[2]), 4),
                      'chassis0': round(c0, 4), 'chassis': round(SB.chassis_min_z(env), 4),
                      'steps': steps, 'terminated': bool(env.terminated)}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['replay', 'sim'])
    ap.add_argument('--coll', default=str(HERE / 'data' / 'truth' / 'coll'))
    ap.add_argument('--record', default=str(HERE / 'data' / 'exec' / 'full_record' / 'TRUTH_FULL'))
    ap.add_argument('--out', default='out/replay.mp4')
    ap.add_argument('--seconds', type=float, default=5.0)
    ap.add_argument('--fps', type=int, default=30)
    a = ap.parse_args()
    {'replay': replay, 'sim': sim}[a.mode](a)


if __name__ == '__main__':
    main()
