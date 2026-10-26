"""生成训练前/训练后/陌生考核的对比演示（固定选择规则，不只挑成功）。"""
import json, pathlib, sys
import numpy as np, mujoco
from PIL import Image, ImageDraw, ImageFont
import os, glob

def _font(size):
    cands = [os.environ.get('RLL_FONT', ''), '/var/lib/deepseek-harness/.fonts/NotoSansCJK-Bold.ttc',
             '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    cands += sorted(glob.glob('/usr/share/fonts/**/*CJK*', recursive=True))
    for c in cands:
        if c and pathlib.Path(c).exists():
            try: return ImageFont.truetype(c, size)
            except Exception: pass
    return ImageFont.load_default()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ppo, wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
W, H, PANEL_H = 900, 420, 52

def record(spec, params, seed, max_frames=34):
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=12.0, v_ref=1.0, tip_deg=60.0)
    obs, _ = env.reset(seed=seed)
    m, d = env.model, env.data
    m.vis.global_.offwidth = W; m.vis.global_.offheight = H
    r = mujoco.Renderer(m, H, W)
    cam = mujoco.MjvCamera(); mujoco.mjv_defaultCamera(cam)
    cam.distance, cam.elevation, cam.azimuth = 3.0, -20, 105
    frames, info, every = [], {}, max(1, env.substeps * 2)
    for i in range(1500):
        a = np.zeros(wheelleg_env.ACT_DIM) if params is None else ppo.deterministic_action(params, obs)
        obs, rew, te, tr, info = env.step(a)
        if i % every == 0 and len(frames) < max_frames:
            cam.lookat[:] = [float(d.qpos[0]) + 0.6, 0.0, float(d.qpos[2]) - 0.3]
            r.update_scene(d, camera=cam)
            frames.append(Image.fromarray(r.render()))
        if te or tr: break
    return frames, info

def label(img, text, sub=''):
    canvas = Image.new('RGB', (img.width, img.height + PANEL_H), (12, 11, 14))
    canvas.paste(img, (0, PANEL_H))
    dr = ImageDraw.Draw(canvas)
    dr.text((14, 8), text, fill=(240, 234, 224), font=_font(17))
    if sub: dr.text((14, 28), sub, fill=(160, 152, 142), font=_font(14))
    return canvas

def main():
    tr = json.loads((ROOT/'scenes/skill_train.json').read_text())
    te = json.loads((ROOT/'scenes/skill_test.json').read_text())
    init = ppo.init_params(np.random.default_rng(0))
    learned = dict(np.load(ROOT/'runs/skill_v2/S_s0/checkpoints/final.npz'))

    # 固定选择规则（写死在代码里，不按结果临时挑）：
    #   成功例 = 训练清单中**按顺序第一个**训练后成功的场景
    #   失败例 = 考核清单中**按顺序第一个**场景
    def ok(spec, params):
        _, info = record(spec, params, 1, max_frames=1)
        return info.get('reason') == 'success'
    s_learn = next((s for s in tr if ok(s, learned)), tr[0])
    s_fail = next((s for s in tr if not ok(s, learned)), None)
    s_exam = te[0]

    panels = []
    f1, i1 = record(s_learn, init, 1)
    panels.append(('训练前（未训练策略）', f"结局 {i1.get('reason')}  横向 {i1.get('lateral_offset')}", f1))
    f2, i2 = record(s_learn, learned, 1)
    panels.append(('训练后（同一场景、同一初态）', f"结局 {i2.get('reason')}  接触 {i2.get('contact_style')} @ {i2.get('first_contact_s')}s", f2))
    f3, i3 = record(s_exam, learned, 1)
    panels.append((f"陌生考核（{s_exam['family']}，未参与训练）",
                   f"结局 {i3.get('reason')}  横向 {i3.get('lateral_offset')}", f3))
    if s_fail is not None:
        f4, i4 = record(s_fail, learned, 1)
        panels.append((f"失败例（{s_fail['name']}，训练后仍失败）",
                       f"结局 {i4.get('reason')}  横向 {i4.get('lateral_offset')}", f4))

    n = min(len(p[2]) for p in panels)
    out_frames = []
    for k in range(n):
        parts = [label(p[2][k], p[0], p[1]) for p in panels]
        sheet = Image.new('RGB', (W, sum(p.height for p in parts)))
        y = 0
        for p in parts:
            sheet.paste(p, (0, y)); y += p.height
        out_frames.append(sheet.resize((640, int(640*sheet.height/W))))
    out = ROOT/'runs/demo'; out.mkdir(parents=True, exist_ok=True)
    gif = out/'skill_before_after_exam.gif'
    out_frames[0].save(gif, save_all=True, append_images=out_frames[1:], duration=90, loop=0)
    print('panels:', [(p[0], p[1]) for p in panels])
    print('frames', n, '->', gif)

if __name__ == '__main__':
    main()
