"""V8 场景：月球南极附近，陨坑边缘与大石堆之间的窄道。

  左边：月溪（一道 1 m 深的长沟，轨道图上标为禁行）——低于路面，不会把影子投进窄道
  右边：大石堆（比机身高，轨道图上标为禁行）——影子投向右侧外面
  窄道里：两块轨道图分辨不出的石头（< 1 m）
    石块 A：右侧，天然长条（rock_07，长宽比 1.85，高 0.55 m，比机身还高），从右侧石堆横伸到车道中间。机器人在右车道上正对它的长边：
            看得到亮着的长边，看不到它有多厚——厚度决定绕过去之后什么时候能切回右车道
    石块 B：左侧大石板（moon_rock_04，高 0.42 m），从溪沿伸到车道中间，在 A 后方约 1.35 m，略斜：
            越往后越向右凸。B 左边到溪沿不够车身宽，只能从右边过
  太阳：左后方，高度角 10°（南极附近太阳总是很低）。A 的影子盖住它背后要换道的那片地

坐标：x 向前，y 向左，平台地面 z = 0。
"""
import os
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(ROOT / 'scripts/v7'))
import terrain, wheelleg_env, v7_soil  # noqa: E402
import lunar_world as LW  # noqa: E402
LW.ROCKS = pathlib.Path(os.environ.get('V7_ROCK_ROOT', str(ROOT / 'assets/v3/rocks')))

SPAN, NGRID = 16.0, 257                     # 地形 32 m × 32 m，0.125 m 一格
CAM = {'pos': [0.42, 0.0, -0.00125], 'pitch_deg': -24.83, 'fovy': 70.0}
ROBOT = {'half_len': 0.38, 'half_wid': 0.33, 'turn_radius': 0.50}
SUN_EL_DEG, SUN_AZ_DEG = 10.0, 35.0         # 光线朝前偏右 35°（太阳在左后方），高度角 10°
RILLE = {'edge_y': 1.30, 'width': 4.2, 'wall': 1.15, 'depth': 1.0}   # 左侧月溪：右沿 y≈1.3，深 1 m，两侧坡约 40°
ROCKS = {   # 名称: 扫描岩石、等比缩放后的高度（都比相机高 0.38 m，相机看不到顶面）、中心位置、偏航
    'A': {'rock': 'rock_07', 'height': 0.55, 'x': 4.55, 'y': -0.735, 'yaw': 90.0},
    'B': {'rock': 'moon_rock_04', 'height': 0.42, 'x': 6.86, 'y': 0.22, 'yaw': -26.0},
}
WALL = {'y_inner': -1.35, 'x0': -2.0, 'x1': 13.0}
START = (0.0, -0.50)
STOP1 = (2.30, -0.50)          # 第一次停车观察的位置（右车道，正对 A 的长边）
GOAL = (10.5, 0.00)
WALL_ROCKS = ['rock_09', 'moon_rock_04', 'rock_07', 'moon_rock_03', 'moon_rock_06', 'moon_rock_07']   # 不用 boulder_01（6.7 万顶点）、stone_01（2.8 万）：省内存


def sun_dir():
    el, az = np.radians(SUN_EL_DEG), np.radians(SUN_AZ_DEG)
    d = np.array([np.cos(el) * np.cos(az), -np.cos(el) * np.sin(az), -np.sin(el)])
    return d / np.linalg.norm(d)                 # 光线传播方向


def rille_edge(x):
    """月溪右沿（靠窄道一侧）的 y：轻微弯曲，在 B 附近收窄。"""
    x = np.asarray(x, float)
    return RILLE['edge_y'] + 0.12 * np.sin(0.8 * x + 0.4) - 0.20 * np.exp(-((x - 7.4) / 1.3) ** 2)


def height_at(X, Y):
    r = RILLE
    e = rille_edge(X)
    d = Y - e                                   # 进入月溪的横向深度（>0 在溪内）
    w = r['width']
    H = np.zeros_like(X, dtype=float)
    # 右坡：0 -> -depth；溪底；左坡：-depth -> 0
    t1 = np.clip(d / r['wall'], 0, 1); t2 = np.clip((w - d) / r['wall'], 0, 1)
    s1 = t1 * t1 * (3 - 2 * t1); s2 = t2 * t2 * (3 - 2 * t2)
    inside = (d > 0) & (d < w)
    H[inside] = -r['depth'] * np.minimum(s1, s2)[inside]
    H += 0.025 * np.exp(-(d / 0.35) ** 2) * (d < 0)            # 溪沿外侧轻微隆起
    return H


def height_map():
    terrain.SPAN = SPAN; terrain.N = NGRID
    X, Y = terrain.grid_xy(NGRID)
    return height_at(X, Y)


def terrain_visual_obj(path, step=0.08, tile=0.9):
    """成片用的地面网格：比物理高度场细，顶点法线平滑；带贴图坐标。物理仍用高度场。"""
    path = pathlib.Path(path)
    if path.exists():
        return path
    xs = np.arange(-SPAN, SPAN + 1e-9, step); ys = np.arange(-SPAN, SPAN + 1e-9, step)
    X, Y = np.meshgrid(xs, ys); Z = height_at(X, Y)
    ny, nx = X.shape
    with open(path, 'w') as f:
        for x, y, z in zip(X.ravel(), Y.ravel(), Z.ravel()):
            f.write(f'v {x:.4f} {y:.4f} {z:.4f}\n')
        for x, y in zip(X.ravel(), Y.ravel()):
            f.write(f'vt {x / tile:.4f} {y / tile:.4f}\n')
        idx = np.arange(nx * ny).reshape(ny, nx) + 1
        a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
        for i in range(len(a)):
            f.write(f'f {a[i]}/{a[i]} {b[i]}/{b[i]} {c[i]}/{c[i]}\nf {a[i]}/{a[i]} {c[i]}/{c[i]} {d[i]}/{d[i]}\n')
    return path


def rock_asset_uniform(rock_id, height, level='h1'):
    """扫描岩石等比缩放到给定高度：水平主轴转到 x，底面落在 z=0，包围盒中心在原点。"""
    src, tex = LW.rock_asset(rock_id, level)
    dst = LW.CACHE / f'{rock_id}_{level}_v8ax_h{int(height * 1000)}_2s.obj'
    if not dst.exists():
        lines = pathlib.Path(src).read_text().splitlines()
        V = np.array([[float(t) for t in l.split()[1:4]] for l in lines if l.startswith('v ')])
        c = V[:, :2].mean(0); w, U = np.linalg.eigh(np.cov((V[:, :2] - c).T)); ax = U[:, np.argmax(w)]
        th = -np.arctan2(ax[1], ax[0]); R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        xy = (V[:, :2] - c) @ R.T
        s = height / np.ptp(V[:, 2]); mid = (xy.min(0) + xy.max(0)) / 2; z0 = V[:, 2].min()
        out, k = [], 0
        for l in lines:
            if l.startswith('v '):
                x, y = xy[k] - mid; z = V[k, 2] - z0; k += 1
                out.append(f'v {x * s:.6f} {y * s:.6f} {z * s:.6f}')
            elif l.startswith('vn '):
                n = np.array([float(v) for v in l.split()[1:4]]); n[:2] = R @ n[:2]
                out.append(f'vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}')
            else:
                out.append(l)
        dst.write_text('\n'.join(out) + '\n')
    return dst, tex


def scene_spec(run):
    H = height_map()
    hf = pathlib.Path(run) / 'scene' / 'height.npy'; hf.parent.mkdir(parents=True, exist_ok=True); np.save(hf, H)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=GOAL[0], span=SPAN, name='v8_polar')
    spec['terrain']['field_x_max'] = SPAN
    spec['terrain']['custom_height_file'] = str(hf)
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.4}
    spec['soil'] = v7_soil.resolve('nominal')
    spec['front_cam'] = dict(CAM)
    objs, rock_bodies, meta = [], {}, {'rocks': {}, 'walls': []}
    for key, p in ROCKS.items():
        obj, _ = rock_asset_uniform(p['rock'], p['height'])
        objs.append({'mesh_file': str(obj), 'x': p['x'], 'y': p['y'], 'yaw_deg': p['yaw'], 'height_m': p['height']})
        b = f'obstacle{len(objs) - 1}'; rock_bodies[b] = p['rock']; meta['rocks'][key] = dict(p, body=b, obj=str(obj))
    rng = np.random.default_rng(18)
    x = WALL['x0']
    while x < WALL['x1']:                         # 右侧大石堆：两排，彼此重叠
        for row in (0, 1):
            Hh = float(rng.uniform(0.6, 1.05)) * (1.0 + 0.25 * row)
            rid = WALL_ROCKS[rng.integers(len(WALL_ROCKS))]
            obj, _ = rock_asset_uniform(rid, Hh)
            V = np.array([[float(t) for t in l.split()[1:3]] for l in pathlib.Path(obj).read_text().splitlines() if l.startswith('v ')])
            yaw = float(rng.uniform(-25, 25)) + (90.0 if row else 0.0)
            th = np.radians(yaw); R2 = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
            ext = (V @ R2.T)
            half_y = float(np.abs(ext[:, 1]).max())
            yc = WALL['y_inner'] - half_y - row * float(rng.uniform(0.6, 1.1)) + float(rng.uniform(-0.05, 0.05))
            objs.append({'mesh_file': str(obj), 'x': x + float(rng.uniform(-0.1, 0.1)), 'y': yc, 'yaw_deg': yaw, 'height_m': Hh})
            b = f'obstacle{len(objs) - 1}'; rock_bodies[b] = rid; meta['walls'].append(b)
        x += float(rng.uniform(0.75, 1.05))
    spec['objects'] = objs
    return spec, rock_bodies, meta


def make_env(spec):
    terrain.SPAN = SPAN; terrain.N = NGRID
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=900); env.reset(seed=0)
    return env


def place(env, x, y, yaw=0.0):
    import mujoco
    q = env.data.qpos
    q[0], q[1] = x, y
    q[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
    env.data.qvel[:] = 0
    mujoco.mj_forward(env.model, env.data)


def settle(env, steps=60):
    for _ in range(steps):
        env.step_command(joint_targets_rad=np.array([[0, 0.85, -1.65]] * 4), wheel_brake=np.ones(4, bool))
