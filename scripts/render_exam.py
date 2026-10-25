"""
把考场渲染出来：既出单帧图，也出视频。

无显卡机器上走 MuJoCo 的 OSMesa 软件渲染（实测可用）。运行前需要：
    export LD_LIBRARY_PATH=/tmp/sysroot/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH
    export MUJOCO_GL=osmesa
"""
import os, sys, json, pathlib, argparse
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ.setdefault('MUJOCO_GL', 'osmesa')
import mujoco

from exam import compose_xml, obstacle_geom_ids
from drive_test import ids, LEG, STANCE, STANCE_HIGH
import controllers

WHEEL_R = 0.086
W, H = 960, 540


def render_exam(asset_dir, stance='low', seconds=8.0, fps=30, out_dir='runs/render',
                follow=True, target_x=2.0, controller='hold', y_offset=0.0):
    xml_path, man = compose_xml(asset_dir, None, y_offset=y_offset)
    m = mujoco.MjModel.from_xml_path(str(xml_path))
    d = mujoco.MjData(m)
    J = ids(m)
    obs = obstacle_geom_ids(m)
    st = STANCE if stance == 'low' else STANCE_HIGH
    brain = controllers.make(controller, st)

    for leg in LEG:
        d.qpos[J[f'{leg}_thigh_joint']['qadr']] = st['thigh']
        d.qpos[J[f'{leg}_calf_joint']['qadr']] = st['calf']
    d.qpos[2] = 0.50
    mujoco.mj_forward(m, d)

    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    for f in out.glob('*.png'):
        f.unlink()

    # OSMesa 默认 framebuffer 640x480，不放大就渲染不了 960x540
    m.vis.global_.offwidth = W
    m.vis.global_.offheight = H
    renderer = mujoco.Renderer(m, H, W)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.distance, cam.elevation, cam.azimuth = 3.2, -18, 105

    kp, kd = 150.0, 5.0
    dt = m.opt.timestep
    every = max(1, int(round(1.0 / (fps * dt))))
    frames = 0
    contact = None
    for i in range(int(seconds / dt)):
        t = i * dt
        tg = brain.targets(t, d.qpos, d.qvel, False)
        for leg in LEG:
            for p in ('hip', 'thigh', 'calf'):
                e = J[f'{leg}_{p}_joint']
                d.ctrl[e['act']] = np.clip(kp * (tg[leg][p] - d.qpos[e['qadr']]) - kd * d.qvel[e['vadr']], -45, 45)
            e = J[f'{leg}_wheel_joint']
            vt = 1.0 * min(1.0, t / 2.0)
            d.ctrl[e['act']] = np.clip(1.2 * (vt / WHEEL_R - d.qvel[e['vadr']]), -15, 15)

        mujoco.mj_step(m, d)

        if contact is None:
            for c in d.contact[:d.ncon]:
                if c.geom1 in obs or c.geom2 in obs:
                    contact = round(t, 3); break

        if i % every == 0:
            cam.lookat[:] = ([float(d.qpos[0]) + 0.6, 0.35, 0.0] if follow else [1.2, 0.3, 0.0])
            renderer.update_scene(d, camera=cam)
            img = renderer.render()
            _write_png(out / f'f{frames:04d}.png', np.ascontiguousarray(img))
            frames += 1

    renderer.close()
    return {'frames': frames, 'fps': fps, 'first_contact_s': contact, 'dir': str(out)}



def _write_png(path, rgb):
    import struct, zlib
    h, w = rgb.shape[:2]
    raw = b''.join(b'\x00' + rgb[y].tobytes() for y in range(h))
    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 6))
           + chunk(b'IEND', b''))
    path.write_bytes(png)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--asset', default='assets/processed/cargo_crate')
    ap.add_argument('--stance', default='low')
    ap.add_argument('--seconds', type=float, default=8.0)
    ap.add_argument('--controller', default='hold', choices=['hold','step'])
    a = ap.parse_args()
    print(json.dumps(render_exam(a.asset, a.stance, a.seconds, controller=a.controller), indent=2))
