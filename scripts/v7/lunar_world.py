"""月面世界渲染器：机器人相机照片与视频画面共用。

只负责"看起来"：车道内的几何（地形、岩石）必须与仿真一致；车道外的远山、地球、装饰碎石只做视觉。
"""
import json
import pathlib

import numpy as np
import trimesh
from PIL import Image, ImageFilter

HERE = pathlib.Path(__file__).resolve().parent
SCRATCH = HERE.parent
GO2W = SCRATCH / 'vendor/unitree_mujoco/unitree_robots/go2w'
ROCKS = SCRATCH / 'v6dl/rocks/v3/rocks'
import os
CACHE = pathlib.Path(os.environ.get('V7_CACHE', str(HERE.parents[1] / 'runs/v7/cache')))
CACHE.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- 贴图
def _fbm(n, seed, beta=1.2):
    rng = np.random.default_rng(seed)
    fx = np.fft.fftfreq(n)[:, None]; fy = np.fft.fftfreq(n)[None, :]
    f = np.sqrt(fx ** 2 + fy ** 2); f[0, 0] = 1
    s = np.fft.fft2(rng.standard_normal((n, n))) / f ** beta; s[0, 0] = 0
    a = np.real(np.fft.ifft2(s)); return (a - a.mean()) / a.std()


def regolith_texture():
    p = CACHE / 'regolith2.png'
    if p.exists():
        return p
    n = 2048
    a = 0.8 * _fbm(n, 1, 1.1) + 0.45 * _fbm(n, 2, 0.6) + 0.35 * np.random.default_rng(3).standard_normal((n, n))
    rng = np.random.default_rng(4)
    yy, xx = np.mgrid[0:n, 0:n]
    for _ in range(140):     # 小陨坑：暗碗 + 亮缘
        cx, cy = rng.integers(0, n, 2); r = rng.uniform(4, 40) * (1 if rng.random() > 0.15 else 2.2)
        dx = np.minimum(abs(xx - cx), n - abs(xx - cx)); dy = np.minimum(abs(yy - cy), n - abs(yy - cy))
        d = np.sqrt(dx ** 2 + dy ** 2) / r
        a += np.where(d < 1, -1.1 * (1 - d ** 2), 0) + np.where((d >= 1) & (d < 1.3), 0.7 * (1 - abs(d - 1.12) / 0.18).clip(0), 0)
    v = (0.50 + 0.045 * a).clip(0, 1)
    rgb = np.stack([v * 1.00, v * 0.985, v * 0.965], -1)
    Image.fromarray((rgb * 255).astype(np.uint8)).save(p)
    return p


def sky_texture():
    """星空天空盒（cube 展开为同一张图）。地球用单独的球体画，不放在天空盒里。"""
    p = CACHE / 'stars2.png'
    if p.exists():
        return p
    n = 2048
    rng = np.random.default_rng(11)
    a = np.zeros((n, n), np.float32)
    k = 2600
    xs, ys = rng.integers(0, n, k), rng.integers(0, n, k)
    b = rng.uniform(0.15, 1.0, k) ** 3
    a[ys, xs] = b
    img = Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
    arr = np.asarray(img).astype(np.float32) * 3.2
    rgb = np.stack([arr, arr * 0.98, arr * 1.04], -1).clip(0, 255).astype(np.uint8)
    Image.fromarray(rgb).save(p)
    return p


def earth_texture():
    """程序化地球：海洋 + 大陆 + 云（风格化，不冒充真实影像）。"""
    p = CACHE / 'earth.png'
    if p.exists():
        return p
    w, h = 2048, 1024
    lon = np.linspace(-np.pi, np.pi, w)[None, :]; lat = np.linspace(np.pi / 2, -np.pi / 2, h)[:, None]
    x = np.cos(lat) * np.cos(lon); y = np.cos(lat) * np.sin(lon); z = np.sin(lat) * np.ones_like(lon)

    def noise3(x, y, z, seed, octaves=6):
        rng = np.random.default_rng(seed); s = np.zeros_like(x)
        for o in range(octaves):
            f = 2 ** o * 1.3
            for _ in range(3):
                kx, ky, kz = rng.standard_normal(3); ph = rng.uniform(0, 6.28)
                s += np.sin(f * (kx * x + ky * y + kz * z) * 2.0 + ph) / (2 ** o)
        return s
    land = noise3(x, y, z, 5) + 0.6 * np.abs(z) - 0.15
    cloud = noise3(x, y, z, 9, 7)
    ocean = np.stack([0.05 + 0 * x, 0.18 + 0.05 * z, 0.45 + 0.05 * z], -1)
    green = np.stack([0.20 + 0 * x, 0.35 + 0 * x, 0.16 + 0 * x], -1)
    desert = np.stack([0.62 + 0 * x, 0.52 + 0 * x, 0.34 + 0 * x], -1)
    lm = (land > 0.35)[..., None]
    lt = np.where((noise3(x, y, z, 7, 4) > 0.2)[..., None], desert, green)
    rgb = np.where(lm, lt, ocean)
    ice = (np.abs(z) > 0.86)[..., None]
    rgb = np.where(ice, np.array([0.92, 0.94, 0.97]), rgb)
    c = ((cloud - 0.4) / 1.2).clip(0, 1)[..., None] ** 1.2
    rgb = rgb * (1 - 0.85 * c) + 0.95 * c
    Image.fromarray((rgb.clip(0, 1) * 255).astype(np.uint8)).save(p)
    return p


# ---------------------------------------------------------------- 远山与装饰
def mountain_mesh(seed=0, r0=70.0, r1=110.0, nseg=200):
    """环形远山：只做视觉，离车道 30 m 以外。"""
    p = CACHE / f'mountains_{seed}.obj'
    if p.exists():
        return p
    rng = np.random.default_rng(seed)
    th = np.linspace(0, 2 * np.pi, nseg, endpoint=False)
    prof = np.zeros(nseg)
    for k in range(1, 22):
        prof += rng.uniform(0.3, 1.0) / k ** 0.9 * np.cos(k * th + rng.uniform(0, 6.28))
    prof = (prof - prof.min()) / (prof.max() - prof.min())
    hgt = 2.5 + 9.0 * prof ** 1.8
    rings = [(r0, 0.0), (r0 + 10, 0.45), (r0 + 22, 1.0), (r1, 0.7), (r1 + 20, 0.0)]
    V = []
    for rr, f in rings:
        jitter = 1 + 0.02 * np.convolve(rng.standard_normal(nseg + 8), np.ones(9) / 9, 'valid')
        for i, t in enumerate(th):
            V.append([rr * jitter[i] * np.cos(t), rr * jitter[i] * np.sin(t), f * hgt[i]])
    V = np.array(V); F = []
    for a in range(len(rings) - 1):
        for i in range(nseg):
            j = (i + 1) % nseg
            p00, p01 = a * nseg + i, a * nseg + j
            p10, p11 = (a + 1) * nseg + i, (a + 1) * nseg + j
            F += [[p00, p10, p11], [p00, p11, p01]]
    m = trimesh.Trimesh(V, np.array(F), process=False)
    m = m.subdivide().subdivide()
    m.vertices[:, 2] += 0.25 * np.sin(m.vertices[:, 0] * 0.9) * np.cos(m.vertices[:, 1] * 0.7) * (m.vertices[:, 2] > 0.3)
    m.export(str(p))
    return p


def two_sided(src, dst):
    """扫描岩石不封口：在 OBJ 文本里追加一份反向面片（保留 UV），避免背面剔除把石头渲染成空心环/碎片。"""
    if dst.exists():
        return dst
    lines = pathlib.Path(src).read_text().splitlines()
    faces = [l for l in lines if l.startswith('f ')]
    rev = ['f ' + ' '.join(l.split()[1:][::-1]) for l in faces]
    pathlib.Path(dst).write_text('\n'.join(lines + rev) + '\n')
    return dst


def lunar_tex(rock_id):
    """扫描贴图去饱和、略压暗，贴近月面岩石的灰色（只改显示，不改几何）。"""
    dst = CACHE / f'tex_{rock_id}.png'
    if not dst.exists():
        im = np.asarray(Image.open(ROCKS / rock_id / 'texture.png').convert('RGB')).astype(np.float32) / 255
        g = im.mean(-1, keepdims=True)
        out = (0.15 * im + 0.85 * g) * 0.92
        Image.fromarray((out.clip(0, 1) * 255).astype(np.uint8)).save(dst)
    return dst


def rock_asset_scaled(rock_id, level, height):
    """按目标高度等比缩放的两面岩石网格（OBJ 文本逐顶点缩放，保留 UV）。
    仿真环境对 mesh_file 物体不会按 target_height_m 缩放，所以必须在这里先缩好。"""
    src, tex = rock_asset(rock_id, level)
    dst = CACHE / f'{rock_id}_{level}_h{int(round(height * 10000)):05d}_2s.obj'
    if not dst.exists():
        lines = pathlib.Path(src).read_text().splitlines()
        vs = np.array([[float(t) for t in l.split()[1:4]] for l in lines if l.startswith('v ')])
        zmin, zmax = vs[:, 2].min(), vs[:, 2].max()
        s = float(height) / (zmax - zmin)
        out = []
        for l in lines:
            if l.startswith('v '):
                x, y, z = (float(t) for t in l.split()[1:4])
                out.append(f'v {x * s:.6f} {y * s:.6f} {(z - zmin) * s:.6f}')
            else:
                out.append(l)
        pathlib.Path(dst).write_text('\n'.join(out) + '\n')
    return dst, tex


def rock_asset(rock_id, level):
    src = ROCKS / rock_id / level / 'body_vis.obj'
    dst = CACHE / f'{rock_id}_{level}_2s.obj'
    return two_sided(src, dst), lunar_tex(rock_id)


# ---------------------------------------------------------------- 场景
def build_xml(target=None, deco_seed=3, lane_half=0.9, width=1920, height=1080,
              sun_dir=(0.80, -0.35, -0.38), robot_style=True, ground_size=150):
    """target: {rock_id, level, pos(x,y), yaw_deg}，车道内的岩石（与仿真同位姿）。"""
    reg, sky, earth = regolith_texture(), sky_texture(), earth_texture()
    assets = [f'<texture name="reg" type="2d" file="{reg}"/>',
              '<material name="reg" texture="reg" texuniform="true" texrepeat="0.9 0.9" specular="0.0" shininess="0.0"/>',
              f'<texture name="sky" type="skybox" file="{sky}"/>',
              f'<texture name="earth" type="2d" file="{earth}"/>',
              '<material name="earth" texture="earth" emission="0.22" specular="0.1" shininess="0.2"/>',
              '<material name="atmo" rgba="0.35 0.55 1.0 0.18" emission="1"/>',
              f'<mesh name="mtn" file="{mountain_mesh()}"/>',
              '<material name="mtn" texture="reg" texuniform="true" texrepeat="0.05 0.05" rgba="0.62 0.62 0.62 1" specular="0"/>']
    geoms = [f'<geom name="ground_vis" type="plane" size="{ground_size} {ground_size} 0.1" material="reg" contype="0" conaffinity="0"/>',
             '<geom name="mtn" type="mesh" mesh="mtn" material="mtn" contype="0" conaffinity="0"/>',
             # 地球：远处大球 + 薄大气层
             '<geom name="earth" type="sphere" size="9" pos="170 -40 36" material="earth" euler="20 -10 40" contype="0" conaffinity="0"/>',
             '<geom name="atmo" type="sphere" size="9.35" pos="170 -40 36" material="atmo" contype="0" conaffinity="0"/>']
    used = set()

    def add_rock(gname, rid, lev, pos, yaw, scale=1.0, z=0.0):
        key = (rid, lev)
        if key not in used:
            obj, tex = rock_asset(rid, lev)
            assets.append(f'<texture name="t_{rid}" type="2d" file="{tex}"/>')
            assets.append(f'<material name="m_{rid}" texture="t_{rid}" specular="0.06" shininess="0.05"/>')
            used.add(key)
        mname = f'mesh_{gname}'
        obj, _ = rock_asset(rid, lev)
        assets.append(f'<mesh name="{mname}" file="{obj}" scale="{scale} {scale} {scale}"/>')
        geoms.append(f'<geom name="{gname}" type="mesh" mesh="{mname}" material="m_{rid}" pos="{pos[0]:.4f} {pos[1]:.4f} {z:.4f}" '
                     f'euler="0 0 {yaw:.2f}" contype="0" conaffinity="0"/>')

    if target:
        add_rock('target', target['rock_id'], target['level'], target['pos'], target.get('yaw_deg', 0.0))
    # 装饰碎石：只放在车道外（|y| > lane_half），不影响物理
    rng = np.random.default_rng(deco_seed)
    pool = [('moon_rock_01', 'h2'), ('moon_rock_03', 'h2'), ('moon_rock_04', 'h2'), ('moon_rock_05', 'h2'),
            ('moon_rock_06', 'h2'), ('moon_rock_07', 'h2')]
    pool = [p for p in pool if (ROCKS / p[0] / p[1] / 'body_vis.obj').exists()]
    for i in range(55):
        x = rng.uniform(-6, 28); side = rng.choice([-1, 1]); y = side * (lane_half + rng.exponential(2.2))
        if abs(y) > 18:
            continue
        rid, lev = pool[rng.integers(len(pool))]
        s = float(np.clip(rng.lognormal(-0.1, 0.6), 0.3, 3.5)) * (1.0 + 0.25 * max(0, abs(y) - 4))
        add_rock(f'deco{i}', rid, lev, (x, y), rng.uniform(0, 360), scale=s, z=-0.01 * s)

    xml = (GO2W / 'go2w.xml').read_text()
    xml = xml.replace('meshdir="assets"', f'meshdir="{GO2W / "assets"}"')
    sd = np.array(sun_dir, float); sd /= np.linalg.norm(sd)
    light = (f'<light name="sun" type="directional" castshadow="true" dir="{sd[0]:.3f} {sd[1]:.3f} {sd[2]:.3f}" '
             'diffuse="1.75 1.72 1.66" specular="0.25 0.25 0.25" ambient="0.035 0.037 0.045"/>')
    visual = ('<visual><headlight ambient="0.05 0.05 0.06" diffuse="0.05 0.05 0.05" specular="0 0 0"/>'
              '<quality shadowsize="8192" offsamples="8"/><map shadowclip="6" shadowscale="0.5" znear="0.01" zfar="600" haze="0"/>'
              f'<global offwidth="{width}" offheight="{height}" fovy="45"/></visual>')
    xml = xml.replace('<asset>', '<asset>' + ''.join(assets), 1)
    xml = xml.replace('<worldbody>', '<worldbody>' + light + ''.join(geoms), 1)
    xml = xml.replace('</mujoco>', visual + '<statistic center="2 0 0.3" extent="1"/></mujoco>')
    return xml


def style_robot(model):
    """白色机身 + 橙色点缀 + 深色轮子（只改显示颜色，不改物理）。"""
    import mujoco
    for gi in range(model.ngeom):
        if model.geom_bodyid[gi] == 0:
            continue                     # 世界里的地面、岩石、远山不动，只改机器人
        if model.geom_contype[gi] != 0 or model.geom_conaffinity[gi] != 0:
            continue                     # 只改可视几何
        b = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, model.geom_bodyid[gi]) or ''
        if 'wheel' in b:
            model.geom_rgba[gi] = [0.10, 0.10, 0.11, 1]
        elif 'calf' in b:
            model.geom_rgba[gi] = [0.22, 0.22, 0.24, 1]
        elif 'thigh' in b:
            model.geom_rgba[gi] = [0.93, 0.93, 0.92, 1]
        elif 'hip' in b:
            model.geom_rgba[gi] = [0.95, 0.52, 0.16, 1]
        elif b == 'base':
            model.geom_rgba[gi] = [0.94, 0.94, 0.93, 1]
        if model.geom_rgba[gi][3] > 0:
            model.geom_matid[gi] = -1
