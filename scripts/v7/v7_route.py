"""V7 连续任务路线：一次连续仿真，遭遇点现场拍照 -> Lux3D -> 准入 -> 预演 -> 决策 -> 执行。

    python3 scripts/v7/v7_route.py --arm full --run runs/v7/route_full
    python3 scripts/v7/v7_route.py --arm obs  --run runs/v7/route_obs

可断点续跑：每到需要 Lux3D 的地方，写出 <run>/<E>/<look>/lux_request.json 并以退出码 10 结束；
本地模型按 docs/v6/LUX3D_CALL.md 执行后写回同目录的 lux_result.json，再运行同一条命令即可从检查点继续。

规则（不得改）：
  * 动作只来自 v7_encounter.decide 写出的 decision.json；本文件不含任何动作名常量的决策逻辑。
  * 观测、配准、准入、预演全部走 v7_observe / v7_encounter（内部调用已验证模块）。
  * 每一帧都有真实的 action / phase 标签。
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(HERE))
import terrain, wheelleg_env, v3_core, v3_record, v7_soil  # noqa: E402
import lunar_world as LW, v7_visual as VV, v7_observe as VO, v7_encounter as VE  # noqa: E402

WAIT_LUX3D = 10
BASE_POSE = np.array([[0, 0.85, -1.65]] * 4)
CAM = {'pos': [0.42, 0.0, -0.00125], 'pitch_deg': -24.83, 'fovy': 70.0}     # v3 采集几何
ROUTE = {   # 固定布局（米）；E 的停车点与岩石的相对位置照搬 v3 状态
    'gravel_x': (3.0, 5.5), 'slope_x': (10.5, 13.5, 16.5), 'slope_rise': 0.26, 'goal_x': 22.0,
    'E1': {'rock': 'moon_rock_02', 'level': 'h2', 'height': 0.2236, 'stop_x': 7.65, 'dx': 1.353, 'y': 0.10, 'v3_state': 'moon_rock_02_h2v0'},
    'E2': {'rock': 'moon_rock_01', 'level': 'h0', 'height': 0.1204, 'stop_x': 18.0, 'dx': 1.353, 'y': 0.10, 'v3_state': 'moon_rock_01_h0v0'},
    'second_look': {'back_m': 2.0, 'lateral_m': 0.35},
}


# ---------------------------------------------------------------- 场景
def route_spec(run):
    terrain.SPAN = 32.0
    X, Y = terrain.grid_xy(terrain.N)              # 列 = x，行 = y（翻转）——仓库约定
    H = np.zeros_like(X)
    a, b, c = ROUTE['slope_x']; r = ROUTE['slope_rise']
    H += np.where((X >= a) & (X <= b), r * (X - a) / (b - a), 0.0)
    H += np.where((X > b) & (X <= c), r * (c - X) / (c - b), 0.0)
    hf = pathlib.Path(run) / 'scene' / 'height.npy'; hf.parent.mkdir(parents=True, exist_ok=True); np.save(hf, H)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=ROUTE['goal_x'], span=32.0, name='v7_route')
    spec['terrain']['field_x_max'] = 32.0
    spec['terrain']['custom_height_file'] = str(hf)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['soil'] = v7_soil.resolve('nominal')
    spec['front_cam'] = dict(CAM)
    objs, rock_bodies = [], {}
    rng = np.random.default_rng(21)                  # E0 碎石：石高 ≤ 0.05 m，轮子直接碾过
    peb = ['moon_rock_03', 'moon_rock_04', 'moon_rock_06', 'moon_rock_07']
    for i in range(16):
        rid = peb[i % len(peb)]; hgt = float(rng.uniform(0.015, 0.035))
        obj, _ = LW.rock_asset_scaled(rid, 'h0', hgt)          # 预先缩放：环境不会替 mesh_file 物体缩放
        objs.append({'mesh_file': str(obj), 'x': float(rng.uniform(*ROUTE['gravel_x'])), 'y': float(rng.uniform(-0.55, 0.55)),
                     'yaw_deg': float(rng.uniform(0, 360)), 'height_m': hgt})
        rock_bodies[f'obstacle{len(objs) - 1}'] = rid
    for e in ('E1', 'E2'):
        p = ROUTE[e]; obj, _ = LW.rock_asset_scaled(p['rock'], p['level'], p['height'])
        objs.append({'mesh_file': str(obj), 'x': p['stop_x'] + p['dx'], 'y': p['y'], 'height_m': p['height']})
        rock_bodies[f'obstacle{len(objs) - 1}'] = p['rock']; p['body'] = f'obstacle{len(objs) - 1}'
    spec['objects'] = objs
    return spec, rock_bodies


def make_env(spec):
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=400); env.reset(seed=0)
    return env


# ---------------------------------------------------------------- 记录
class Log:
    def __init__(self, run):
        self.run = pathlib.Path(run); self.k = 0; self.rec = None; self.seg = 0
        self.events_p = self.run / 'events.jsonl'

    def open(self, label):
        self.close()
        segs = sorted((self.run / 'segments').glob('seg_*')) if (self.run / 'segments').exists() else []
        self.seg = len(segs)
        self.rec = v3_record.Recorder(self.run / 'segments' / f'seg_{self.seg:03d}_{label}', {'segment': label}, hz=50.0)

    def frame(self, env, action, phase):
        self.rec.add(v3_record.frame_from_env(env, None, np.zeros(3), self.k, env.t,
                                              extra={'action': action, 'phase': phase, 'ctrl': np.asarray(env.data.ctrl, float).tolist()}))
        self.k += 1

    def close(self):
        if self.rec is not None:
            self.rec.close(); self.rec = None

    def event(self, **kw):
        kw['wall'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        with self.events_p.open('a') as f:
            f.write(json.dumps(kw, ensure_ascii=False) + '\n')


def yaw_of(env):
    w, x, y, z = env.data.qpos[3:7]
    return float(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def cruise(env, log, x_target, y_target=0.0, phase='cruise', reverse=False, limit=120.0):
    """巡航底座：横向/航向比例控制，轮速 3.5 rad/s（与 WP8/M3 相同）。"""
    t0 = env.t
    while (env.data.qpos[0] > x_target if reverse else env.data.qpos[0] < x_target) and env.t - t0 < limit:
        e = float(env.data.qpos[1]) - y_target
        # 航向项与行驶方向无关；横向项在倒车时反号（倒车时车尾朝向决定横移方向）
        yd = float(np.clip((2.5 if reverse else -2.5) * e - 1.6 * yaw_of(env), -0.9, 0.9))
        v = -2.0 if reverse else 3.5
        env.step_command(joint_targets_rad=BASE_POSE, wheel_omega_rad_s=np.array([v + 1.2 * yd, v - 1.2 * yd, v + 1.2 * yd, v - 1.2 * yd]),
                         wheel_mode='velocity')
        log.frame(env, 'CRUISE', phase)


def square_up(env, log, phase, max_steps=400):
    """原地刹停并把航向修正到 <1°（轮序 FR, FL, RR, RL：右轮快 = 左转，与 cruise 同一约定）。"""
    for k in range(max_steps):
        yaw = yaw_of(env)
        if abs(np.degrees(yaw)) < 1.0 and k > 20:
            env.step_command(joint_targets_rad=BASE_POSE, wheel_brake=np.ones(4, bool))
        else:
            w = float(np.clip(-6.0 * yaw, -3.0, 3.0))
            env.step_command(joint_targets_rad=BASE_POSE, wheel_omega_rad_s=np.array([w, -w, w, -w]), wheel_mode='velocity')
        log.frame(env, 'OBSERVE', phase)
    for _ in range(25):
        env.step_command(joint_targets_rad=BASE_POSE, wheel_brake=np.ones(4, bool))
        log.frame(env, 'OBSERVE', phase)


def hold(env, log, action, phase, n):
    for _ in range(n):
        env.step_command(joint_targets_rad=BASE_POSE, wheel_brake=np.ones(4, bool))
        log.frame(env, action, phase)


# ---------------------------------------------------------------- 检查点
def save_ck(run, env, stage, extra=None):
    ck = {'stage': stage, 'state': env.save_state(), 't': float(env.t), 'extra': extra or {}}
    (pathlib.Path(run) / 'checkpoint.json').write_text(json.dumps(ck, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o)))


def load_ck(run):
    p = pathlib.Path(run) / 'checkpoint.json'
    return json.loads(p.read_text()) if p.exists() else None


def lux_ready(look_dir):
    p = pathlib.Path(look_dir) / 'lux_result.json'
    if not p.exists():
        return None
    res = json.loads(p.read_text())
    req = json.loads((pathlib.Path(look_dir) / 'lux_request.json').read_text())
    if req['mode'] == 'imgs':
        # 两视图必须是真实的两图调用（请求体字段 imgs，两张图按顺序），不得拼成一张组合图
        for t in res['tasks']:
            if t.get('status') == 'ok' and not (t.get('api_field') == 'imgs' and t.get('n_images') == 2):
                raise RuntimeError(f'{p}: task {t.get("id")} is not a real two-image call (need api_field=imgs, n_images=2); '
                                   'composite images are not allowed')
    return [{'id': t['id'], 'glb': str(ROOT / t['glb'])} for t in res['tasks'] if t.get('status') == 'ok' and t.get('glb')]


def _sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


REUSE = None     # --reuse-lux：旧运行目录


def try_reuse(look_dir, mode, items):
    """复用旧运行同一位置、输入图逐字节相同的 Lux3D 结果。只限单图模式；任何一项对不上就不复用（照常请求）。"""
    if REUSE is None or mode != 'img':
        return False
    look_dir = pathlib.Path(look_dir)
    old_res = REUSE / look_dir.parent.name / look_dir.name / 'lux_result.json'
    if not old_res.exists():
        return False
    by_id = {t['id']: t for t in json.loads(old_res.read_text())['tasks']}
    out = []
    for it in items:
        t = by_id.get(it['id'])
        if t is None or len(t.get('inputs') or []) != 1:
            return False
        if _sha(ROOT / t['inputs'][0]) != _sha(ROOT / it['path']):
            return False
        if t.get('status') == 'ok':
            g = ROOT / t['glb']
            if not g.exists() or _sha(g) != t.get('glb_sha256'):
                return False
        nt = dict(t); nt['inputs'] = [it['path']]; nt['reused_from'] = rel(old_res)
        out.append(nt)
    (look_dir / 'lux_result.json').write_text(json.dumps({'schema': 'v7-lux-result/v1', 'reused_from': rel(old_res),
                                                         'input_check': 'sha256 of every input image identical', 'tasks': out}, indent=2))
    return True


def write_request(look_dir, mode, items):
    req = {'schema': 'v7-lux-request/v1', 'mode': mode, 'version': 'G1-Turbo', 'faceCount': 30000, 'items': items,
           'result_file': rel(pathlib.Path(look_dir) / 'lux_result.json'),
           'result_schema': {'tasks': [{'id': 'A1', 'task_id': '...', 'status': 'ok|failed', 'submitted_at': '...', 'finished_at': '...',
                                        'fetched_at': '...', 'glb': 'repo-relative path of tex_mesh.glb', 'glb_sha256': '...',
                                        'inputs': ['repo-relative input image paths'],
                                        **({'api_field': 'imgs', 'n_images': 2} if mode == 'imgs' else {})}]}}
    if mode == 'imgs':
        req['imgs_rule'] = ('Each item is ONE Lux3D task whose request body carries the field imgs = [url of paths[0], url of paths[1]] '
                            'in this order (scripts/lux3d_client.submit_img_to_3d_multi). Never stitch the two images into one picture. '
                            'Items with identical paths are independent samples: give each its own sample id so they are not cache hits.')
    (pathlib.Path(look_dir) / 'lux_request.json').write_text(json.dumps(req, indent=2, ensure_ascii=False))


def rel(p):
    return str(pathlib.Path(p).resolve().relative_to(ROOT))


# ---------------------------------------------------------------- 主流程
def execute(env, log, enc, dec, arm):
    action, plan, vis = VE.to_world(dec, 'FULL' if arm == 'full' else 'OBS_CONS')
    log.close()
    seg = log.run / 'segments' / f'seg_{len(list((log.run / "segments").glob("seg_*"))):03d}_{enc}_{action}'
    goal = env.spec.get('goal_x')
    env.spec['goal_x'] = plan['end_x']                       # 动作在本地终点（停车点 + 2.6 m）结束，与预演一致
    snap = env.save_state()
    r = v3_core.run_action(env, snap, action, vis, mode='same_scene', record_dir=seg,
                           params=plan if action in ('D1', 'D2') else None)
    env.spec['goal_x'] = goal
    for k in ('terminated', 'truncated'):
        if hasattr(env, k):
            setattr(env, k, False)
    log.event(encounter=enc, arm=arm, action=action, outcome=r.get('outcome'), reason=r.get('reason'),
              t_end=r.get('t_end'), contact=r.get('contact'), record=rel(seg))
    log.open(f'after_{enc}')
    return r


def encounter(env, log, run, enc, arm, vm):
    """返回 'WAIT' 或执行结果。"""
    p = ROUTE[enc]; edir = pathlib.Path(run) / enc
    look1 = edir / 'look1'
    if not (look1 / 'state.json').exists():
        square_up(env, log, f'{enc}_observe')
        VO.capture(env, vm, p['body'], look1, label=f'{enc}_look1')
        log.event(encounter=enc, step='look1', obs=rel(look1))
    if arm == 'obs':                                            # 只看正面：不调用 Lux3D
        dec = VE.decide(look1, [], edir / 'decide_look1')
        return execute(env, log, enc, dec, arm)
    cands = lux_ready(look1)
    if cands is None:
        st = json.loads((look1 / 'state.json').read_text())
        items = [{'id': k, 'path': v['path']} for k, v in sorted(st['crops'].items())]
        write_request(look1, 'img', items)
        if not try_reuse(look1, 'img', items):
            return 'WAIT'
        log.event(encounter=enc, step='look1_lux_reused', source=rel(REUSE / enc / 'look1' / 'lux_result.json'))
        cands = lux_ready(look1)
    dec1p = edir / 'decide_look1' / 'decision.json'
    dec = json.loads(dec1p.read_text()) if dec1p.exists() else VE.decide(look1, cands, edir / 'decide_look1')
    hold(env, log, 'WAIT_LUX3D', f'{enc}_imagine', 100)
    if dec['branch'] == 'accept':
        return execute(env, log, enc, dec, arm)
    # 全部拒绝 -> 再看一眼：后退、横移、摆正，拍第二张，用 imgs 两图模式重新想象
    look2 = edir / 'look2'
    if not (look2 / 'state.json').exists():
        x0 = env.data.qpos[0]
        cruise(env, log, x0 - ROUTE['second_look']['back_m'], 0.0, f'{enc}_second_look', reverse=True, limit=20)
        cruise(env, log, x0, ROUTE['second_look']['lateral_m'], f'{enc}_second_look', limit=30)
        square_up(env, log, f'{enc}_second_look')
        VO.capture(env, vm, p['body'], look2, label=f'{enc}_look2')
        log.event(encounter=enc, step='look2', obs=rel(look2))
    cands2 = lux_ready(look2)
    if cands2 is None:
        s1 = json.loads((look1 / 'state.json').read_text()); s2 = json.loads((look2 / 'state.json').read_text())
        items = [{'id': f'M{i}', 'paths': [s1['crops']['A1']['path'], s2['crops']['A1']['path']]} for i in (1, 2, 3)]
        write_request(look2, 'imgs', items)
        return 'WAIT'
    dec2p = edir / 'decide_look2' / 'decision.json'
    dec = json.loads(dec2p.read_text()) if dec2p.exists() else VE.decide(look2, cands2, edir / 'decide_look2')
    hold(env, log, 'WAIT_LUX3D', f'{enc}_imagine2', 100)
    return execute(env, log, enc, dec, arm)          # 采纳，或零准入时 decision 里已回退到 OBS_CONS


def main():
    global REUSE
    ap = argparse.ArgumentParser(); ap.add_argument('--arm', choices=['full', 'obs'], required=True); ap.add_argument('--run', required=True)
    ap.add_argument('--reuse-lux', default=None, help='旧运行目录：单图请求的输入图逐字节相同时直接复用其 Lux3D 结果')
    a = ap.parse_args()
    REUSE = pathlib.Path(a.reuse_lux).resolve() if a.reuse_lux else None
    run = pathlib.Path(a.run).resolve(); run.mkdir(parents=True, exist_ok=True)
    spec, rock_bodies = route_spec(run)
    (run / 'scene' / 'scene_spec.json').write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    env = make_env(spec)
    (run / 'scene' / 'model_physics.xml').write_text(env._xml)
    vm = VV.VisualModel(env, rock_bodies)
    (run / 'scene' / 'rock_bodies.json').write_text(json.dumps(rock_bodies, indent=2))
    log = Log(run)
    ck = load_ck(run)
    stage = 'start'
    if ck:
        env.restore_state(ck['state'], mode='same_scene'); stage = ck['stage']
        log.k = int(ck['extra'].get('k', 0))
    log.open(f'resume_{stage}')
    try:
        if stage == 'start':
            cruise(env, log, ROUTE['E1']['stop_x'], 0.0, 'E0_gravel_to_E1')
            log.event(step='arrive_E1', x=float(env.data.qpos[0]), y=float(env.data.qpos[1]), yaw_deg=float(np.degrees(yaw_of(env))))
            stage = 'E1'; save_ck(run, env, stage, {'k': log.k})
        if stage == 'E1':
            r = encounter(env, log, run, 'E1', a.arm, vm)
            if r == 'WAIT':
                save_ck(run, env, 'E1', {'k': log.k}); log.close(); print('WAIT_LUX3D E1'); sys.exit(WAIT_LUX3D)
            stage = 'to_E2'; save_ck(run, env, stage, {'k': log.k})
        if stage == 'to_E2':
            cruise(env, log, ROUTE['E2']['stop_x'], 0.0, 'slope_to_E2')
            stage = 'E2'; save_ck(run, env, stage, {'k': log.k})
        if stage == 'E2':
            r = encounter(env, log, run, 'E2', a.arm, vm)
            if r == 'WAIT':
                save_ck(run, env, 'E2', {'k': log.k}); log.close(); print('WAIT_LUX3D E2'); sys.exit(WAIT_LUX3D)
            stage = 'to_goal'; save_ck(run, env, stage, {'k': log.k})
        if stage == 'to_goal':
            cruise(env, log, ROUTE['goal_x'], 0.0, 'to_sample_site')
            hold(env, log, 'CRUISE', 'arrived', 50)
            stage = 'done'; save_ck(run, env, stage, {'k': log.k})
    finally:
        log.close()
    res = {'arm': a.arm, 'final_x': float(env.data.qpos[0]), 'final_y': float(env.data.qpos[1]), 't_end': float(env.t),
           'tilt_deg': float(env._tilt()), 'arrived': bool(env.data.qpos[0] >= ROUTE['goal_x'] - 0.05)}
    (run / 'result.json').write_text(json.dumps(res, indent=2)); print(json.dumps(res))


if __name__ == '__main__':
    main()
