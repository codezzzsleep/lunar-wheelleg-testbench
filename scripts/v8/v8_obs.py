"""V8 观测目录：一次看（机器人相机 RGB-D）-> 每块目标石头一个 v3/v7 格式的观测目录（局部坐标系）。

和 V7 的区别只有两处：
  1. 黑影：亮度低于门限的像素没有深度（depth.npy 里记为 NaN，另存 dark.png）。配准与自检只在亮处判断。
  2. 一眼里有几块石头：先在地图上把"看到的石头"连成块（轨道图禁行区里的不算），每块一个目标。
局部坐标系 = 停车位姿（x0, y0, yaw0）为原点，与 v3/v7 的约定相同，下游模块原样使用。

每个目标的目录：
  rgb.png  depth.npy（黑影为 NaN）  dark.png  mask.png（该石头亮处的像素）  visible_points.npy（局部）
  observation.json  camera_world.json  state.json  rgb_gen.png  gen/variants/{A1,A2,B1,B2,C1,C2}.png（Lux3D 输入）
"""
import hashlib
import json
import pathlib
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(ROOT / 'scripts/v7'))
import camera_io  # noqa: E402
import v3_obs  # noqa: E402
import v8_nav as N  # noqa: E402
import v8_vis as VZ  # noqa: E402

HI = (4040, 3030)
PROTO = json.loads((ROOT / 'plans/v3_protocol.json').read_text())


def _sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def targets_from_map(state, min_cells=20):
    """地图上看到的石头连成块；去掉轨道图禁行区里的（大石堆）。返回 [bool 网格]，按 x 排序。"""
    rock = (state == N.ROCK) & ~N.prior_nogo()
    lab, n = ndimage.label(ndimage.binary_dilation(rock, iterations=2), structure=np.ones((3, 3)))
    out = []
    for k in range(1, n + 1):
        m = (lab == k) & rock
        if m.sum() >= min_cells:
            out.append(m)
    out.sort(key=lambda m: float(N.GX[m].min()))
    return out


def _render(vm, cam, W, H):
    if (W, H) == HI:
        return VZ.render_cam(vm, cam, hi=True)
    return VZ.camera_rgbd(vm, cam)


def world_points(depth, snap_w):
    """(H, W, 3) 世界点；没有深度的像素为 NaN。"""
    pts, ys, xs = camera_io.unproject_depth(depth, snap_w)
    P = np.full(depth.shape + (3,), np.nan)
    P[ys, xs] = pts
    return P


def capture(vm, env, out_root, look_label, state, dark_thr=0.10, cam='front_cam', W=1600, H=1200):
    """返回 [{'target': 'T1', 'dir': ..., 'cells': bool 网格}]。vm 的离屏缓冲须 ≥ 4040×3030。"""
    import mujoco
    out_root = pathlib.Path(out_root).resolve(); out_root.mkdir(parents=True, exist_ok=True)
    vm.sync(env.data.qpos)
    cid = mujoco.mj_name2id(vm.m, mujoco.mjtObj.mjOBJ_CAMERA, cam)
    rgb, depth = _render(vm, cam, W, H)
    hi, depth_hi = _render(vm, cam, *HI)
    dark = VZ.dark_mask(rgb, dark_thr); dark_hi = VZ.dark_mask(hi, dark_thr)
    snap_w = camera_io.capture(vm.m, vm.d, cid, W, H)
    snap_hi = camera_io.capture(vm.m, vm.d, cid, *HI)
    q = env.data.qpos
    w_, x_, y_, z_ = q[3:7]
    yaw0 = float(np.arctan2(2 * (w_ * z_ + x_ * y_), 1 - 2 * (y_ * y_ + z_ * z_)))
    x0, y0 = float(q[0]), float(q[1])
    c, s = np.cos(-yaw0), np.sin(-yaw0)
    Rl = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]); tl = -Rl @ np.array([x0, y0, 0.0])
    def to_local(snap):
        sl = dict(snap)
        sl['world_pos'] = [float(v) for v in (Rl @ np.asarray(snap['world_pos']) + tl)]
        sl['R_world_from_camera'] = (Rl @ np.asarray(snap['R_world_from_camera'])).tolist()
        sl['frame'] = 'local'; sl['local_frame'] = {'x0': x0, 'y0': y0, 'yaw0': yaw0}
        return sl
    snap_l, snap_hil = to_local(snap_w), to_local(snap_hi)
    Pw = world_points(np.where(dark, np.nan, depth).astype(np.float64), snap_w)
    depth_hi_valid = np.where(dark_hi, np.nan, depth_hi).astype(np.float32)
    del depth_hi
    out = []
    for k, cells in enumerate(targets_from_map(state)):
        tid = f'T{k + 1}'
        d = out_root / tid; d.mkdir(parents=True, exist_ok=True)
        grow = ndimage.binary_dilation(cells, iterations=3) & ~N.prior_nogo()     # 不把旁边大石堆的像素算进来
        def mask_of(P):
            fin = np.isfinite(P).all(-1)
            Px = np.nan_to_num(P[..., 0], nan=-99.0); Py = np.nan_to_num(P[..., 1], nan=-99.0); Pz = np.nan_to_num(P[..., 2], nan=-99.0)
            ok = fin & (Pz >= N.ROCK_Z) & (Px > N.X0) & (Px < N.X1) & (Py > N.Y0) & (Py < N.Y1)
            ix = np.clip(((Px - N.X0) / N.RES).astype(np.int32), 0, N.NX - 1)
            iy = np.clip(((Py - N.Y0) / N.RES).astype(np.int32), 0, N.NY - 1)
            return ok & grow[ix, iy]
        def mask_of_depth_rows(dep, snap, rows=192):
            """高分辨率按行分块反投影，避免一次性生成上亿个浮点数。"""
            Hh, Ww = dep.shape
            m = np.zeros((Hh, Ww), bool)
            for r0 in range(0, Hh, rows):
                blk = dep[r0:r0 + rows].astype(np.float64)
                pts, ys, xs = camera_io.unproject_depth(blk, dict(snap, intrinsics=dict(snap['intrinsics'], cy=snap['intrinsics']['cy'] - r0)))
                Pb = np.full(blk.shape + (3,), np.nan); Pb[ys, xs] = pts
                m[r0:r0 + rows] = mask_of(Pb)
            return m
        mask = mask_of(Pw); mask_hi = mask_of_depth_rows(depth_hi_valid, snap_hi)
        if mask.sum() < 2000:
            continue
        Image.fromarray(rgb).save(d / 'rgb.png')
        Image.fromarray(mask.astype(np.uint8) * 255).save(d / 'mask.png')
        Image.fromarray(dark.astype(np.uint8) * 255).save(d / 'dark.png')
        np.save(d / 'depth.npy', np.where(dark, np.nan, depth).astype(np.float32))
        pts_l = (Pw[mask] @ Rl.T) + tl
        np.save(d / 'visible_points.npy', pts_l)
        vis = {'x_front': float(pts_l[:, 0].min()), 'y_center': float((pts_l[:, 1].min() + pts_l[:, 1].max()) / 2),
               'W_vis': float(np.ptp(pts_l[:, 1])), 'H_vis': float(pts_l[:, 2].max()),
               'source': 'visible_points (local frame, lit pixels of this target)'}
        (d / 'observation.json').write_text(json.dumps({
            'schema': 'observation/v8', 'label': f'{look_label}_{tid}', 'camera': snap_l, 'intrinsics': snap_l['intrinsics'],
            'image': 'rgb.png', 'target': tid, 'mask_px': int(mask.sum()), 'dark_px': int(dark.sum()),
            'mask_source': 'lit pixels with depth, >= 4 cm above ground, inside this rock blob on the map',
            'dark_rule': f'luminance < {dark_thr}: no depth (passive camera in black shadow)'}, indent=2))
        (d / 'camera_world.json').write_text(json.dumps(snap_w, indent=2))
        Image.fromarray(hi).save(d / 'rgb_gen.png')
        box = v3_obs._pixel_box(mask_hi)
        native = box[3] - box[1] + 1
        rec = v3_obs._variants(hi, mask_hi, box, d / 'gen', native, PROTO)
        st = {'schema': 'v8-target-state/v1', 'target': tid, 'look': look_label, 'visible': vis,
              'local_frame': {'x0': x0, 'y0': y0, 'yaw0': yaw0},
              'robot_qpos_world': [float(v) for v in q], 't_sim': float(env.t),
              'crop_native_px': int(native), 'native_ok': bool(rec.get('native_ok')), 'crops': rec['variants'],
              'cells_world': {'x': [float(N.GX[cells].min()), float(N.GX[cells].max())],
                              'y': [float(N.GY[cells].min()), float(N.GY[cells].max())], 'n': int(cells.sum())},
              'observation_sha256': {k2: _sha(d / k2) for k2 in ('rgb.png', 'depth.npy', 'mask.png', 'dark.png')}}
        (d / 'state.json').write_text(json.dumps(st, indent=2))
        np.save(d / 'cells.npy', cells)
        out.append({'target': tid, 'dir': d, 'cells': cells, 'state': st})
    return out
