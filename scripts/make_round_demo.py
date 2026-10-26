"""
重做完整演示：不按最短轨迹截断，每个回合跑完并停留终态。

  MUJOCO_GL=osmesa .venv/bin/python scripts/make_round_demo.py

四个面板（固定选择规则写死在代码里）：
  1. 新生成资产原貌（X1，本轮真实生成）
  2. 基础控制器（零残差）在同一场景同一初态
  3. 训练后策略（同场景同初态）
  4. 最终考核：X1 上的冻结策略

每个面板独立跑完整回合，跑到终止后**继续渲染 12 帧终态**，
再统一补齐到相同帧数，避免"最短面板决定时长"。
"""
import json
import pathlib
import sys

import numpy as np
import mujoco
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ppo
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
W, H, BAR = 720, 400, 46
FPS_EVERY = 6          # 每 6 个控制步取 1 帧 -> 50Hz / 6 ≈ 8.3 fps
TAIL_FRAMES = 12


def _font(size):
    for c in ('/var/lib/deepseek-harness/.fonts/NotoSansCJK-Bold.ttc',):
        if pathlib.Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()


def record(spec, params, seed, max_seconds=12.0):
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=max_seconds,
                                   v_ref=1.0, tip_deg=60.0)
    obs, _ = env.reset(seed=seed)
    m, d = env.model, env.data
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    r = mujoco.Renderer(m, H, W)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.distance, cam.elevation, cam.azimuth = 2.2, -22, 106

    frames, info = [], {}
    done = False
    i = 0
    while not done:
        a = (np.zeros(wheelleg_env.ACT_DIM) if params is None
             else ppo.deterministic_action(params, obs))
        obs, rew, te, tr, info = env.step(a)
        done = te or tr
        i += 1
        if i % FPS_EVERY == 0 or done:
            cam.lookat[:] = [float(d.qpos[0]) + 0.55, 0.0, float(d.qpos[2]) - 0.28]
            r.update_scene(d, camera=cam)
            frames.append(Image.fromarray(r.render()))
    # 终态停留：让观看者看清成功/失败发生后的状态
    for _ in range(TAIL_FRAMES):
        frames.append(frames[-1].copy())
    return frames, info


def bar(img, title, sub):
    canvas = Image.new('RGB', (img.width, img.height + BAR), (12, 11, 14))
    canvas.paste(img, (0, BAR))
    dr = ImageDraw.Draw(canvas)
    dr.text((12, 6), title, fill=(240, 234, 224), font=_font(18))
    dr.text((12, 27), sub, fill=(158, 150, 140), font=_font(14))
    return canvas


def main():
    dev = json.loads((ROOT / 'scenes/skill_devval.json').read_text())
    final = json.loads((ROOT / 'scenes/skill_final.json').read_text())
    learned = dict(np.load(ROOT / 'runs/skill_v3/R_s0/checkpoints/final.npz'))

    # 固定规则：开发集第 1 个场景；考核集第 1 个场景；初态 seed 固定为 1
    dev_scene = dev[0]
    exam_scene = final[0]

    panels = []
    f0, i0 = record(exam_scene, None, 1, max_seconds=0.35)   # 资产原貌
    panels.append((f'新生成资产：{exam_scene["family"]}',
                   'Lux3D 真实生成（本轮，13 积分）→ CoACD → 可碰撞', f0))
    f1, i1 = record(dev_scene, None, 1)
    panels.append(('基础控制器（零残差）',
                   f'结局 {i1.get("reason")}　接触 {i1.get("contact_style")}', f1))
    f2, i2 = record(dev_scene, learned, 1)
    panels.append(('训练后策略（同场景同初态）',
                   f'结局 {i2.get("reason")}　接触 {i2.get("contact_style")}'
                   f' @ {i2.get("first_contact_s")}s', f2))
    f3, i3 = record(exam_scene, learned, 1)
    panels.append((f'最终考核：{exam_scene["family"]}（未参与训练）',
                   f'结局 {i3.get("reason")}　接触 {i3.get("contact_style")}', f3))

    n = max(len(p[2]) for p in panels)
    out_frames = []
    for k in range(n):
        parts = [bar(p[2][min(k, len(p[2]) - 1)], p[0], p[1]) for p in panels]
        sheet = Image.new('RGB', (W * 2, parts[0].height * 2), (12, 11, 14))
        for j, p in enumerate(parts):
            sheet.paste(p, ((j % 2) * W, (j // 2) * p.height))
        out_frames.append(sheet.resize((900, int(900 * sheet.height / sheet.width))))

    out = ROOT / 'runs/demo'
    out.mkdir(parents=True, exist_ok=True)
    gif = out / 'round_demo_full.gif'
    out_frames[0].save(gif, save_all=True, append_images=out_frames[1:],
                       duration=120, loop=0)
    print('面板:', [(p[0], p[1]) for p in panels])
    print(f'帧数 {len(out_frames)}，约 {len(out_frames)*0.12:.1f}s -> {gif}')


if __name__ == '__main__':
    main()
