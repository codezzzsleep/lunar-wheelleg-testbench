"""Stage009：五画面展示（真实记录 + 带纹理三维回放）。"""
import json, pathlib, subprocess, sys
import numpy as np
import mujoco
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'runs/v3/stage009/demo'
W, H, FPS = 1280, 720, 24
TASKS = ['4632564','4632603','4632618','4632621','4632624','4632627']
FV = ROOT / 'runs/v3/stage008/formal_v2'
VIS = ROOT / 'runs/v3/stage009/vis_scene'


def font(sz):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if pathlib.Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def card(lines, out, bg=(18, 20, 24)):
    im = Image.new('RGB', (W, H), bg); d = ImageDraw.Draw(im)
    y = 70
    for text, sz, col in lines:
        d.text((70, y), text, font=font(sz), fill=col); y += int(sz * 1.7)
    im.save(out)


def setup_vis():
    import shutil, os
    VIS.mkdir(parents=True, exist_ok=True)
    src = ROOT / 'vendor/unitree_mujoco/unitree_robots/go2w'
    shutil.copy(src / 'go2w.xml', VIS / 'go2w.xml')
    if not (VIS / 'assets').exists():
        os.symlink(src / 'assets', VIS / 'assets')


def vis_xml(rock_stl, textured=True, rock_pos=(1.0, 0.0, 0.0), with_robot=True, with_walls=True, rock_euler=90):
    tex = ('<texture name="rocktex" type="2d" file="%s"/>' % (ROOT / 'assets/v3/rocks/moon_rock_05/texture.png'))
    mat = '<material name="rockmat" texture="rocktex"/>' if textured else '<material name="rockmat" rgba="0.62 0.62 0.6 1"/>'
    inc = '<include file="go2w.xml"/>' if with_robot else ''
    return f'''<mujoco>
  {inc}
  <asset>
    <mesh name="rockmesh" file="{rock_stl}"/>
    {tex if textured else ''}
    {mat}
    <texture name="grid" type="2d" builtin="checker" rgb1="0.55 0.55 0.55" rgb2="0.45 0.45 0.45" width="256" height="256"/>
    <material name="floormat" texture="grid" texrepeat="10 10"/>
  </asset>
  <worldbody>
    <geom name="floor" type="plane" size="6 6 0.1" material="floormat"/>
    <body name="rock" pos="{rock_pos[0]} {rock_pos[1]} {rock_pos[2]}" euler="0 0 {rock_euler}"><geom type="mesh" mesh="rockmesh" material="rockmat"/></body>
    {'' if not with_walls else '<geom type="box" pos="1.0 -0.55 0.16" size="0.25 0.25 0.16" rgba="0.6 0.6 0.6 1"/><geom type="box" pos="1.0 0.55 0.16" size="0.25 0.25 0.16" rgba="0.6 0.6 0.6 1"/>'}
  </worldbody>
</mujoco>'''


def render_record(rec_dir, rock_stl, out_mp4, cam=(2.0, 0.0, 0.35), dist=2.4, azimuth=130,
                  elev=-14, seconds=None, step=2):
    setup_vis()
    xmlp = VIS / 'scene.xml'; xmlp.write_text(vis_xml(rock_stl, textured=True, rock_pos=(1.0,0.0,0.0), with_robot=True))
    m = mujoco.MjModel.from_xml_path(str(xmlp)); d = mujoco.MjData(m)
    m.vis.global_.offwidth = W; m.vis.global_.offheight = H
    chunks = sorted(pathlib.Path(rec_dir).glob('chunk_*.npz'))
    q = np.concatenate([np.load(c)['qpos'] for c in chunks])
    t = np.concatenate([np.load(c)['t'] for c in chunks])
    frames = OUT / 'frames_replay'; frames.mkdir(parents=True, exist_ok=True)
    for f in frames.glob('*.png'): f.unlink()
    ren = mujoco.Renderer(m, H, W)
    cam_obj = mujoco.MjvCamera(); cam_obj.type = mujoco.mjtCamera.mjCAMERA_TRACKING
    cam_obj.trackbodyid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    cam_obj.distance = dist; cam_obj.azimuth = azimuth; cam_obj.elevation = elev
    cam_obj.lookat[:] = cam
    t_end = float(t[-1]) if seconds is None else min(float(t[-1]), float(seconds))
    n = 0
    for i, tt in enumerate(np.arange(0.0, t_end, step / FPS)):
        k = int(np.searchsorted(t, tt)); k = min(k, len(q) - 1)
        d.qpos[:] = q[k][:m.nq]
        mujoco.mj_forward(m, d)
        ren.update_scene(d, camera=cam_obj)
        Image.fromarray(ren.render()).save(frames / f'{n:05d}.png'); n += 1
    ren.close()
    subprocess.check_call(['ffmpeg', '-y', '-v', 'error', '-framerate', str(FPS / step),
                           '-i', str(frames / '%05d.png'), '-r', str(FPS),
                           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', str(out_mp4)])
    return n


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    setup_vis()
    obs = ROOT / 'runs/v3/stage008/truth_v2/observation/rgb.png'
    im = Image.open(obs).convert('RGB').resize((W, 720))
    Image.open(obs).convert('RGB').resize((W, 540)).save(OUT / 'p1_obs.png')
    # Panel 1
    p1 = Image.new('RGB', (W, H), (12, 14, 18)); p1.paste(Image.open(OUT / 'p1_obs.png'), (0, 90))
    d = ImageDraw.Draw(p1)
    d.text((40, 18), 'PANEL 1  SEEING: reconstructed RGB-D at the common S0', font=font(34), fill=(255, 255, 255))
    d.text((40, 58), 'right: shared V (observed shell) feeds both arms; walls/ground fixed', font=font(22), fill=(200, 200, 200))
    p1.save(OUT / 'p1.png')
    # Panel 2: six registered candidates, rendered geometry
    tiles = []
    for t in TASKS:
        stl = ROOT / 'runs/v3/stage008/registered' / f'task_{t}' / 'world.stl'
        x = VIS / f'scene_{t}.xml'; x.write_text(vis_xml(stl, textured=False, rock_pos=(0,0,0), with_robot=False, with_walls=False, rock_euler=0))
        m = mujoco.MjModel.from_xml_path(str(x)); dd = mujoco.MjData(m); mujoco.mj_forward(m, dd)
        m.vis.global_.offwidth = 640; m.vis.global_.offheight = 360
        ren = mujoco.Renderer(m, 360, 640)
        cam = mujoco.MjvCamera(); cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.lookat[:] = [1.0, 0, 0.15]; cam.distance = 0.85; cam.azimuth = 205; cam.elevation = -12
        ren.update_scene(dd, camera=cam); img = Image.fromarray(ren.render()); ren.close()
        dr = ImageDraw.Draw(img); dr.text((12, 8), f'Lux3D {t}', font=font(26), fill=(255, 230, 120))
        tiles.append(img)
    p2 = Image.new('RGB', (W, H), (12, 14, 18)); dr = ImageDraw.Draw(p2)
    dr.text((40, 14), 'PANEL 2  SIX IMAGINATIONS: registered generated geometry', font=font(28), fill=(255, 255, 255))
    for i, im2 in enumerate(tiles):
        p2.paste(im2, (20 + (i % 2) * 630, 70 + (i // 2) * 215))
    p2.save(OUT / 'p2.png')
    # Panel 3: per-candidate BODY trial paths
    p3 = Image.new('RGB', (W, H), (12, 14, 18)); dr = ImageDraw.Draw(p3)
    dr.text((40, 14), 'PANEL 3  TRIALS: BODY_CLEARANCE rehearsal per candidate (x vs t)', font=font(30), fill=(255, 255, 255))
    for i, t in enumerate(TASKS):
        rec = FV / (f'record_full_{t}') / 'BODY_CLEARANCE'
        chunks = sorted(rec.glob('chunk_*.npz'))
        if not chunks: continue
        q = np.concatenate([np.load(c)['qpos'] for c in chunks]); tt = np.concatenate([np.load(c)['t'] for c in chunks])
        row = json.loads((FV / f'rows_full_{t}.jsonl').read_text().splitlines()[0]) if False else None
        ox, oy = 70 + (i % 2) * 620, 90 + (i // 2) * 205
        w, h = 540, 150
        dr.rectangle([ox, oy, ox + w, oy + h], outline=(80, 80, 80))
        xs = q[:, 0]; tmax = max(tt[-1], 1e-6)
        pts = [(ox + int(w * min(1.0, x / 2.6)), oy + h - int(h * min(1.0, t / tmax))) for x, t in zip(xs, tt)]
        dr.line(pts, fill=(120, 200, 255), width=2)
        dr.text((ox, oy - 24), f'{t}: x_end={xs[-1]:.2f} m, {tmax:.1f} s', font=font(20), fill=(230, 230, 230))
    p3.save(OUT / 'p3.png')
    # Panel 4: decision
    res = json.loads((FV / 'result.json').read_text())
    p4 = Image.new('RGB', (W, H), (12, 14, 18)); dr = ImageDraw.Draw(p4)
    dr.text((50, 30), 'PANEL 4  MAJORITY DECISION', font=font(40), fill=(255, 255, 255))
    y = 120
    for arm in ('full', 'obs'):
        v = res[arm]['votes']; ch = res[arm]['chosen']
        dr.text((60, y), f'{arm.upper()} arm: ' + ', '.join(f'{k}={n}' for k, n in v.items() if n),
                font=font(24), fill=(220, 220, 220)); y += 40
        dr.text((60, y), f'chosen: {ch}   decision_sha: {res[arm]["decision_sha"]}',
                font=font(26), fill=(140, 255, 160)); y += 60
    dr.text((60, y + 10), 'both arms choose BODY_CLEARANCE on this single case; no majority tie',
            font=font(24), fill=(200, 200, 200))
    dr.text((60, y + 50), 'OBS holds raised to 2.45 m (unknown rear); FULL lowers at 1.165 m (first candidate rear)',
            font=font(22), fill=(200, 200, 200))
    p4.save(OUT / 'p4.png')
    # Panel 5 card + replay segments (textured)
    stl = ROOT / 'runs/v3/stage008/truth_v2/rock_local.stl'
    seg_a = OUT / 'p5a.mp4'; seg_b = OUT / 'p5b.mp4'
    rec = FV / 'exec_full' / 'record' / 'TRUTH_FULL'
    n1 = render_record(rec, stl, seg_a, seconds=22, step=3, dist=3.0, azimuth=200, elev=-18)
    n2 = render_record(rec, stl, seg_b, seconds=None, step=4, dist=3.0, azimuth=200, elev=-18)
    p5 = Image.new('RGB', (W, H), (12, 14, 18)); dr = ImageDraw.Draw(p5)
    dr.text((60, 40), 'PANEL 5  TRUTH EXECUTION AND REVEAL', font=font(40), fill=(255, 255, 255))
    ex = res['full']['exec']
    dr.text((60, 130), f"FULL chosen {res['full']['chosen']} -> {ex['outcome']}, {ex['t_end']:.1f} s",
            font=font(30), fill=(140, 255, 160))
    dr.text((60, 190), f"reached={ex['reached']}  chassis_contacts={ex['chassis_contacts']}  safe_pass={ex['safe_pass']}",
            font=font(26), fill=(220, 220, 220))
    dr.text((60, 250), 'textured replay uses the recorded 50 Hz qpos; actual pose and trajectory, no edits',
            font=font(22), fill=(190, 190, 190))
    p5.save(OUT / 'p5.png')
    # stitch: cards 5s, segments, skill comparison clip
    skill = ROOT / 'runs/v3/stage006/replay_fix/body_vs_stance.mp4'
    parts = []
    for name in ('p1.png', 'p2.png', 'p3.png', 'p4.png', 'p5.png'):
        v = OUT / f'{name}.mp4'
        subprocess.check_call(['ffmpeg', '-y', '-v', 'error', '-loop', '1', '-i', str(OUT / name),
                               '-t', '6', '-r', str(FPS), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                               '-vf', f'scale={W}:{H}', str(v)])
        parts.append(v)
    for v in (seg_a, seg_b):
        if v.is_file():
            parts.append(v)
    if skill.is_file():
        sv = OUT / 'skill.mp4'
        subprocess.check_call(['ffmpeg', '-y', '-v', 'error', '-stream_loop', '1', '-i', str(skill),
                               '-t', '10', '-r', str(FPS), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                               '-vf', f'scale={W}:{H}', str(sv)])
        parts.append(sv)
    lst = OUT / 'concat.txt'
    with lst.open('w') as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    subprocess.check_call(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(lst),
                           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', str(OUT / 'stage9_demo.mp4')])
    print(json.dumps({'out': str(OUT / 'stage9_demo.mp4'), 'parts': [str(p) for p in parts]}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
