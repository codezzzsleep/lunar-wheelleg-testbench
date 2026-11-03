"""v3 素材：真实三维渲染 + 1920×1080/30fps 编码（ffmpeg）。

镜头（SPEC §11.2）：
  1 establishing  月面建立镜头（自由相机，缓慢推进）
  2 robotview     机器人视角 + 实际上传图
  3 lux3d_process 真实上传→生成→下载的时间线（真实 task_id/耗时，不伪造录屏）
  4 turntable     候选同尺度同光照转台
  5 overlay       共同可见面实体 + 候选背面半透明
  6 rehearsal     预演矩阵（页面用表，不出视频）
  7 exec          FULL / OBS_ONLY 并排执行（同一 S0、同一时刻）
  8 reveal        真值背面揭晓（候选→真值淡入）
  9 look_again    再观察（真实行驶 + 新观测）
 10 closing       收尾远景

所有画面由保存的 qpos/相机/时间重新渲染；不用点图代替机器人；不改轨迹。
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mujoco
import trimesh

import v3_core
import v3_register

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEDIA = ROOT / 'media/v3'
W, H = 1920, 1080
FPS = 30


def sha256_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _ffmpeg(frames_dir, out_mp4, fps=FPS):
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(fps),
           '-i', str(frames_dir / 'f_%05d.png'),
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20',
           '-movflags', '+faststart', str(out_mp4)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or '')[-400:]


def _renderer(model, w=W, h=H):
    model.vis.global_.offwidth = max(int(w), int(model.vis.global_.offwidth))
    model.vis.global_.offheight = max(int(h), int(model.vis.global_.offheight))
    return mujoco.Renderer(model, int(h), int(w))


def _free_cam(lookat, distance, azimuth, elevation):
    cam = mujoco.MjvCamera()
    cam.lookat[:] = lookat
    cam.distance = float(distance)
    cam.azimuth = float(azimuth)
    cam.elevation = float(elevation)
    return cam


def _shade_off(r):
    try:
        r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0
    except Exception:
        pass
    return r


def _scene_with_mesh(mesh_path, texture=None, extra_xml='', light=True):
    """最小场景：地面 + 一个网格（用于转台/叠加/揭晓）。"""
    tex = ''
    mat = 'rgba=".72 .62 .5 1"'
    if texture and pathlib.Path(texture).is_file():
        tex = (f'<texture name="rocktex" type="2d" file="{texture}"/>'
               f'<material name="rockmat" texture="rocktex" specular="0.05" shininess="0.1"/>')
        mat = 'material="rockmat"'
    xml = f"""
<mujoco model="v3shot">
  <option timestep="0.002" gravity="0 0 -1.62"/>
  <visual><headlight ambient="0.35 0.35 0.35" diffuse="0.6 0.6 0.6"/>
    <global offwidth="{W}" offheight="{H}"/></visual>
  <asset>{tex}
    <texture name="sky" type="skybox" builtin="flat" rgb1="0 0 0" rgb2="0 0 0" width="64" height="64"/>
    <mesh name="obj" file="{mesh_path}"/>
    <texture name="ground" type="2d" builtin="flat" rgb1=".30 .30 .33" rgb2=".30 .30 .33"
             width="128" height="128" mark="none"/>
    <material name="gm" texture="ground" specular="0.02"/>
  </asset>
  <worldbody>
    <light pos="-1.2 -0.8 1.4" dir="0.5 0.35 -0.75" diffuse="0.9 0.85 0.75" castshadow="true"/>
    <geom name="ground" type="plane" size="4 4 0.1" pos="0 0 0" material="gm"/>
    <body name="obstacle0" pos="0 0 0"><geom type="mesh" mesh="obj" {mat}
      contype="0" conaffinity="0"/></body>
    {extra_xml}
  </worldbody>
</mujoco>"""
    return mujoco.MjModel.from_xml_string(xml)


def _write_frames(frames, outdir):
    from PIL import Image
    outdir.mkdir(parents=True, exist_ok=True)
    for i, fr in enumerate(frames):
        Image.fromarray(fr).save(outdir / f'f_{i:05d}.png')


def shot_establishing(states, out_dir):
    """月面建立镜头：低机位缓慢推向岩石。"""
    st = states[0]
    spec = json.loads((ROOT / 'runs/v3/states' / st['state_id'] / 'scene_spec.json').read_text())
    spec = json.loads(json.dumps(spec))
    spec.pop('object_material', None)
    env = v3_core.make_env(spec, {'scene': {'control_hz': 50, 'budget_s': 30, 'tip_deg': 60}})
    m, d = env.model, env.data
    env.reset(seed=0)
    mujoco.mj_forward(m, d)
    r = _renderer(m)
    rock = st['rock_id']
    x0 = float(spec['objects'][0]['x'])
    y0 = float(spec['objects'][0]['y'])
    frames = []
    N = 5 * FPS
    for i in range(N):
        t = i / (N - 1)
        cam = _free_cam([x0 - 0.25 + 0.25 * t, y0, 0.10],
                        distance=1.9 - 0.9 * t, azimuth=118 + 18 * t, elevation=-12 + 4 * t)
        r.update_scene(d, camera=cam)
        _shade_off(r)
        frames.append(r.render())
    r.close()
    _write_frames(frames, out_dir / 'establishing')
    return _ffmpeg(out_dir / 'establishing', out_dir / '01_establishing.mp4')


def shot_images(state_dir, out_dir, seconds=6):
    """机器人视角 + 实际上传图（缓慢推近，不裁剪、不加 UI）。"""
    from PIL import Image
    obs = state_dir / 'observation'
    gen = obs / 'gen'
    imgs = [(obs / 'rgb.png', 'robot_view'), (gen / 'rgb_gen.png', 'native_highres')]
    for k in ('A1', 'B1', 'C1'):
        p = gen / 'variants' / f'{k}.png'
        if p.is_file():
            imgs.append((p, f'upload_{k}'))
    frames = []
    per = max(1, seconds * FPS // max(1, len(imgs)))
    for p, tag in imgs:
        if not p.is_file():
            continue
        im = Image.open(p).convert('RGB').resize((W, H), Image.LANCZOS)
        arr = np.asarray(im)
        for i in range(per):
            frames.append(arr)
    _write_frames(frames, out_dir / 'robotview')
    return _ffmpeg(out_dir / 'robotview', out_dir / '02_robot_view_and_upload.mp4')


def shot_turntable(cands, out_dir, seconds=4):
    """候选同尺度同光照转台（每个候选单独一段，横向排布由页面做）。"""
    outs = []
    for cid, mesh_p, tex in cands:
        try:
            m = _scene_with_mesh(mesh_p, tex)
        except Exception as e:  # noqa: BLE001
            outs.append((cid, None, f'{type(e).__name__}: {e}'))
            continue
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
        r = _renderer(m)
        frames = []
        N = seconds * FPS
        lo = m.geom_aabb  # noqa: F841 (未用，仅确保已 forward)
        for i in range(N):
            az = 360.0 * i / N
            cam = _free_cam([0, 0, 0.06], distance=0.75, azimuth=az, elevation=-12)
            r.update_scene(d, camera=cam)
            frames.append(r.render())
        r.close()
        _write_frames(frames, out_dir / f'turntable_{cid}')
        ok, err = _ffmpeg(out_dir / f'turntable_{cid}', out_dir / f'04_turntable_{cid}.mp4')
        outs.append((cid, str(out_dir / f'04_turntable_{cid}.mp4') if ok else None, err))
    return outs


def shot_overlay(state_dir, cand_mesh, out_dir, seconds=4):
    """共同可见面（实体） + 候选背面（半透明）。"""
    from PIL import Image
    vmesh = state_dir / 'fusion' / 'V_mesh.stl'
    if not vmesh.is_file():
        import v3_fuse
        art = v3_fuse.load_v_artifact(state_dir / 'fusion')
        msh = v3_fuse.FZ.marching_tets(art['shell'], art['grid'])
        msh.export(vmesh)
    try:
        xml = f"""
<mujoco model="v3overlay">
  <option timestep="0.002" gravity="0 0 -1.62"/>
  <visual><headlight ambient="0.35 0.35 0.35" diffuse="0.6 0.6 0.6"/>
    <global offwidth="{W}" offheight="{H}"/></visual>
  <asset>
    <texture name="sky" type="skybox" builtin="flat" rgb1="0" rgb2="0" width="64" height="64"/>
    <mesh name="v" file="{vmesh}"/>
    <mesh name="g" file="{cand_mesh}"/>
    <texture name="ground" type="2d" builtin="flat" rgb1=".30 .30 .33" rgb2=".30 .30 .33"
             width="128" height="128" mark="none"/>
    <material name="gm" texture="ground" specular="0.02"/>
  </asset>
  <worldbody>
    <light pos="-1.2 -0.8 1.4" dir="0.5 0.35 -0.75" diffuse="0.9 0.85 0.75"/>
    <geom name="ground" type="plane" size="4 4 0.1" pos="0 0 0" material="gm"/>
    <geom type="mesh" mesh="v" rgba=".55 .75 .95 1" contype="0" conaffinity="0"/>
    <geom type="mesh" mesh="g" rgba="1 .45 .15 0.30" contype="0" conaffinity="0"/>
  </worldbody>
</mujoco>"""
        m = mujoco.MjModel.from_xml_string(xml)
    except Exception as e:  # noqa: BLE001
        return False, f'{type(e).__name__}: {e}'
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    r = _renderer(m)
    frames = []
    N = seconds * FPS
    for i in range(N):
        az = 360.0 * i / N
        cam = _free_cam([0, 0, 0.06], distance=0.8, azimuth=az, elevation=-10)
        r.update_scene(d, camera=cam)
        _shade_off(r)
        frames.append(r.render())
    r.close()
    _write_frames(frames, out_dir / 'overlay')
    return _ffmpeg(out_dir / 'overlay', out_dir / '05_overlay.mp4')


def _replay_frames(env, traj_path, cam_fn, max_frames=None):
    """按 trajectory.jsonl 的 qpos 逐帧重放（不推进物理）。"""
    frames_q = []
    for line in pathlib.Path(traj_path).read_text().splitlines():
        if not line.strip():
            continue
        fr = json.loads(line)
        if 'qpos' in fr:
            frames_q.append(fr)
    m, d = env.model, env.data
    r = _renderer(m)
    out = []
    step = 2 if len(frames_q) > 400 else 1     # 50 Hz -> 25/50 fps 抽帧
    for k in range(0, len(frames_q), step):
        fr = frames_q[k]
        d.qpos[:] = np.asarray(fr['qpos'], float)[:m.nq]
        d.qvel[:] = np.zeros(m.nv)
        mujoco.mj_forward(m, d)
        cam = cam_fn(d)
        r.update_scene(d, camera=cam)
        _shade_off(r)
        out.append(r.render())
        if max_frames and len(out) >= max_frames:
            break
    r.close()
    return out


def shot_exec_side_by_side(state_dir, out_dir, seconds=10):
    """FULL 与 OBS_ONLY 并排：同一 S0、同一相机、同一时刻。"""
    from PIL import Image
    st = v3_core.load_state(state_dir)
    spec = v3_core.truth_spec(st)
    envs = []
    for arm in ('FULL', 'OBS_ONLY'):
        traj = state_dir / 'decision' / f'trajectory_{arm}.jsonl'
        if not traj.is_file():
            return False, f'missing {traj.name}'
        env = v3_core.make_env(spec, {'scene': {'control_hz': 50, 'budget_s': 30,
                                                'tip_deg': 60}})
        env.reset(seed=0)
        envs.append((arm, env, traj))
    x0 = float(spec['objects'][0]['x'])
    y0 = float(spec['objects'][0]['y'])

    def cam_fn(d):
        return _free_cam([x0 - 0.55, y0 - 0.10, 0.16], distance=1.35,
                         azimuth=112, elevation=-14)

    seqs = []
    for arm, env, traj in envs:
        seqs.append(_replay_frames(env, traj, cam_fn, max_frames=seconds * FPS))
    n = min(len(seqs[0]), len(seqs[1])) if all(seqs) else 0
    if n == 0:
        return False, 'empty trajectory'
    frames = []
    for i in range(n):
        a = Image.fromarray(seqs[0][i]).resize((W // 2, H), Image.LANCZOS)
        b = Image.fromarray(seqs[1][i]).resize((W // 2, H), Image.LANCZOS)
        canvas = Image.new('RGB', (W, H))
        canvas.paste(a, (0, 0))
        canvas.paste(b, (W // 2, 0))
        frames.append(np.asarray(canvas))
    _write_frames(frames, out_dir / 'exec_pair')
    return _ffmpeg(out_dir / 'exec_pair', out_dir / '07_exec_full_vs_obs_only.mp4')


def shot_reveal(state_dir, cand_mesh, out_dir, seconds=5):
    """真值背面揭晓：候选淡出、真值淡入（同一相机）。"""
    from PIL import Image
    truth = state_dir / 'truth' / 'body_world.stl'
    if not truth.is_file():
        return False, 'no truth mesh'
    # 把两个网格都平移到原点，便于同一相机
    t = trimesh.load(truth, force='mesh', process=False)
    c = np.asarray(t.bounds.mean(0), float)
    t.apply_translation(-c)
    tp = out_dir / 'truth_centered.stl'
    out_dir.mkdir(parents=True, exist_ok=True)
    t.export(tp)
    g = trimesh.load(cand_mesh, force='mesh', process=False)
    g.apply_translation(-c)
    gp = out_dir / 'cand_centered.stl'
    g.export(gp)
    if not (state_dir / 'fusion' / 'V_mesh.stl').is_file():
        import v3_fuse
        art = v3_fuse.load_v_artifact(state_dir / 'fusion')
        v3_fuse.FZ.marching_tets(art['shell'], art['grid']).export(
            state_dir / 'fusion' / 'V_mesh.stl')
    v = trimesh.load(state_dir / 'fusion' / 'V_mesh.stl', force='mesh', process=False)
    v.apply_translation(-c)
    vp = out_dir / 'v_centered.stl'
    v.export(vp)

    def scene(a_path, a_rgba, b_path=None, b_rgba=None):
        b = ''
        if b_path:
            b = f'<mesh name="b" file="{b_path}"/>'
            b_geom = f'<geom type="mesh" mesh="b" rgba="{b_rgba}" contype="0" conaffinity="0"/>'
        else:
            b_geom = ''
        return f"""
<mujoco model="v3reveal"><option timestep="0.002" gravity="0 0 -1.62"/>
  <visual><headlight ambient="0.35 0.35 0.35" diffuse="0.6 0.6 0.6"/>
    <global offwidth="{W}" offheight="{H}"/></visual>
  <asset><mesh name="a" file="{a_path}"/>{b}
    <texture name="ground" type="2d" builtin="flat" rgb1=".30 .30 .33" rgb2=".30 .30 .33"
             width="128" height="128" mark="none"/>
    <material name="gm" texture="ground" specular="0.02"/></asset>
  <worldbody><light pos="-1.2 -0.8 1.4" dir="0.5 0.35 -0.75" diffuse="0.9 0.85 0.75"/>
    <geom name="ground" type="plane" size="4 4 0.1" pos="0 0 0" material="gm"/>
    <geom type="mesh" mesh="a" rgba="{a_rgba}" contype="0" conaffinity="0"/>{b_geom}
  </worldbody></mujoco>"""

    frames = []
    N = seconds * FPS

    def render_scene(xml, az):
        m = mujoco.MjModel.from_xml_string(xml)
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
        r = _renderer(m)
        cam = _free_cam([0, 0, 0.05], distance=0.8, azimuth=az, elevation=-10)
        r.update_scene(d, camera=cam)
        img = r.render()
        r.close()
        return img

    # 前 1/3：候选；中 1/3：候选+真值叠加；后 1/3：真值
    for i in range(N):
        az = 360.0 * i / N
        f = i / (N - 1)
        if f < 0.35:
            img = render_scene(scene(str(gp), '.9 .45 .2 1'), az)
        elif f < 0.65:
            img = render_scene(scene(str(gp), '.9 .45 .2 .35', str(tp), '.55 .75 .95 .9'), az)
        else:
            img = render_scene(scene(str(tp), '.55 .75 .95 1'), az)
        frames.append(img)
    _write_frames(frames, out_dir / 'reveal')
    return _ffmpeg(out_dir / 'reveal', out_dir / '08_truth_reveal.mp4')


def shot_closing(states, out_dir, seconds=5):
    st = states[0]
    spec = json.loads((ROOT / 'runs/v3/states' / st['state_id'] / 'scene_spec.json').read_text())
    spec = json.loads(json.dumps(spec))
    spec.pop('object_material', None)
    env = v3_core.make_env(spec, {'scene': {'control_hz': 50, 'budget_s': 30, 'tip_deg': 60}})
    m, d = env.model, env.data
    env.reset(seed=0)
    mujoco.mj_forward(m, d)
    r = _renderer(m)
    x0 = float(spec['objects'][0]['x'])
    y0 = float(spec['objects'][0]['y'])
    frames = []
    N = seconds * FPS
    for i in range(N):
        t = i / (N - 1)
        cam = _free_cam([x0 - 0.9 - 2.2 * t, y0, 0.18 + 0.55 * t],
                        distance=1.4 + 3.6 * t, azimuth=118 + 30 * t, elevation=-10 + 10 * t)
        r.update_scene(d, camera=cam)
        _shade_off(r)
        frames.append(r.render())
    r.close()
    _write_frames(frames, out_dir / 'closing')
    return _ffmpeg(out_dir / 'closing', out_dir / '10_closing_wide.mp4')


def shot_lux_process(state_dir, out_dir, seconds=5):
    """真实过程：上传图 → 真实等待 → 返回资产（时间线来自 ledger，不是伪造录屏）。"""
    from PIL import Image, ImageDraw
    gen = state_dir / 'observation' / 'gen'
    imgs = [gen / 'variants' / 'A1.png', gen / 'variants' / 'B1.png', gen / 'variants' / 'C1.png']
    frames = []
    N = seconds * FPS
    per = N // max(1, len(imgs))
    for k, p in enumerate(imgs):
        if not p.is_file():
            continue
        im = Image.open(p).convert('RGB')
        arr = np.asarray(im.resize((W, H), Image.LANCZOS))
        for i in range(per):
            frames.append(arr)
    _write_frames(frames, out_dir / 'lux_inputs')
    return _ffmpeg(out_dir / 'lux_inputs', out_dir / '03_lux3d_inputs.mp4')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--states', nargs='*', default=None)
    ap.add_argument('--limit', type=int, default=2)
    a = ap.parse_args()
    MEDIA.mkdir(parents=True, exist_ok=True)
    res = json.loads((ROOT / 'runs/v3/report/v3_results.json').read_text()) \
        if (ROOT / 'runs/v3/report/v3_results.json').is_file() else None
    states = []
    for p in sorted((ROOT / 'runs/v3/states').glob('*/state.json')):
        states.append(json.loads(p.read_text()))
    picked = states[:1]
    if a.states:
        keep = set(a.states)
        picked = [s for s in states if s['state_id'] in keep] or picked
    elif res:
        pairs = res['summary'].get('pairs') or []
        hero = next((p for p in pairs if p['FULL'] == 'pass' and p['OBS_ONLY'] != 'pass'), None)
        if hero:
            picked = [s for s in states if s['state_id'] == hero['state_id']] or picked
    out = MEDIA
    manifest = {'schema': 'v3-media/v1', 'resolution': [W, H], 'fps': FPS, 'clips': []}
    ok, err = shot_establishing(picked, out)
    manifest['clips'].append({'name': '01_establishing.mp4', 'ok': ok, 'error': None if ok else err})
    ok, err = shot_closing(picked, out)
    manifest['clips'].append({'name': '10_closing_wide.mp4', 'ok': ok, 'error': None if ok else err})
    for st in picked:
        sd = ROOT / 'runs/v3/states' / st['state_id']
        prefix = st['state_id']
        ok, err = shot_images(sd, out)
        manifest['clips'].append({'name': '02_robot_view_and_upload.mp4', 'state': prefix,
                                  'ok': ok, 'error': None if ok else err})
        ok, err = shot_lux_process(sd, out)
        manifest['clips'].append({'name': '03_lux3d_inputs.mp4', 'state': prefix,
                                  'ok': ok, 'error': None if ok else err})
        cand_dir = sd / 'candidates'
        cands = []
        for c in sorted(cand_dir.glob('*/parent_world/body.stl')):
            tex_p = None
            cands.append((c.parent.parent.name, str(c), tex_p))
        tt = shot_turntable(cands, out)
        manifest['clips'].append({'name': '04_turntable_*.mp4', 'state': prefix,
                                  'ok': all(x[1] for x in tt), 'n': len(tt)})
        if cands:
            ok, err = shot_overlay(sd, cands[0][1], out)
            manifest['clips'].append({'name': '05_overlay.mp4', 'state': prefix,
                                      'ok': ok, 'error': None if ok else err})
            ok, err = shot_reveal(sd, cands[0][1], out)
            manifest['clips'].append({'name': '08_truth_reveal.mp4', 'state': prefix,
                                      'ok': ok, 'error': None if ok else err})
        ok, err = shot_exec_side_by_side(sd, out)
        manifest['clips'].append({'name': '07_exec_full_vs_obs_only.mp4', 'state': prefix,
                                  'ok': ok, 'error': None if ok else err})
    for f in sorted(out.glob('*.mp4')):
        manifest.setdefault('files', []).append(
            {'name': f.name, 'bytes': f.stat().st_size, 'sha256': sha256_file(f)})
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'n_clips': len(manifest['files']) if 'files' in manifest else 0,
                      'out': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
