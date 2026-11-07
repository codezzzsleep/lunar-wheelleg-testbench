"""影子实验：影子会不会让 Lux3D 把石头想错？用深度去影子能不能纠正？

    python3 scripts/v7/v7_shadow_exp.py --prepare  --out runs/v7/shadow_exp      # 渲染观测、生成 Lux3D 请求
    （本地按 LUX3D_CALL.md 执行每个条件目录下的 lux_request.json，写回 lux_result.json）
    python3 scripts/v7/v7_shadow_exp.py --evaluate --out runs/v7/shadow_exp      # 配准、准入、与真值比较、汇总

条件 = 岩石 × 太阳角度。每个条件同一张照片、同一份观测（深度掩码），只改送进 Lux3D 的输入：
  A_naive  只看亮度的"物体"框出的紧裁剪（影子在框内）
  B_naive  只看亮度的"物体"（石头 + 相连的暗区）抠图
  B_depth  用深度判定的石头抠图（影子已去掉）
各 2 次采样。观测、配准、准入、真值比较对三种输入完全相同，差别只来自输入图。
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(HERE))
import terrain, wheelleg_env, camera_io, v3_obs, v3_register, v5_core as C, v5_metrics_ref as R  # noqa: E402
import lunar_world as LW, v7_visual as VV, v7_shadow as SH, v7_encounter as VE  # noqa: E402

ROCKS = [('moon_rock_02', 'h2', 0.2236), ('moon_rock_05', 'h2', 0.2236), ('moon_rock_07', 'h2', 0.2236)]
# 太阳方向 = 光线传播方向（世界系，机器人朝 +x 看）。月球南极太阳高度最高约 1.5°，低太阳是常态。
SUNS = {'high_side': (0.35, -0.80, -1.60),     # 对照：高太阳侧光，影子短
        'low_side': (0.30, -0.95, -0.18),      # 低太阳（约 10°）侧光：影子横向拖长，与石头暗面连成一片
        'low_front': (0.97, 0.12, -0.20),      # 低太阳在机器人身后：石头影子拖向远处，机器人自己的影子也伸向石头
        'low_behind': (-0.97, -0.10, -0.20)}   # 低太阳逆光：石头朝向相机的一面全黑
PROTO = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
RESULT_SCHEMA = {'tasks': [{'id': 'B_depth1', 'task_id': '...', 'status': 'ok|failed', 'submitted_at': '...', 'finished_at': '...',
                            'fetched_at': '...', 'glb': 'repo-relative path of tex_mesh.glb', 'glb_sha256': '...',
                            'inputs': ['repo-relative input image path']}]}


def scene(rock, level, height):
    obj, _ = LW.rock_asset_scaled(rock, level, height)
    spec = terrain.make_spec(kind='flat', seed=0, goal_x=3.0, name=f'shadow_{rock}')
    spec['objects'] = [{'mesh_file': str(obj), 'x': 1.353, 'y': 0.10}]
    spec['front_cam'] = {'pos': [0.42, 0.0, -0.00125], 'pitch_deg': -24.83, 'fovy': 70.0}
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=10); env.reset(seed=0)
    for _ in range(30):
        env.step_command(joint_targets_rad=np.array([[0, 0.85, -1.65]] * 4), wheel_brake=np.ones(4, bool))
    return env


def truth_mesh(env, body='obstacle0'):
    import mujoco
    m, d = env.model, env.data
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, body)
    parts = []
    for g in range(m.ngeom):
        if m.geom_bodyid[g] != bid or m.geom_type[g] != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        mid = m.geom_dataid[g]
        va, vn = m.mesh_vertadr[mid], m.mesh_vertnum[mid]; fa, fn = m.mesh_faceadr[mid], m.mesh_facenum[mid]
        V = m.mesh_vert[va:va + vn] @ d.geom_xmat[g].reshape(3, 3).T + d.geom_xpos[g]
        parts.append(trimesh.Trimesh(V, m.mesh_face[fa:fa + fn], process=False))
    return trimesh.util.concatenate(parts)


def write_obs(out, rgb, depth, mask, snap):
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(out / 'rgb.png'); np.save(out / 'depth.npy', depth.astype(np.float32))
    Image.fromarray(mask.astype(np.uint8) * 255).save(out / 'mask.png')
    pts, _, _ = camera_io.unproject_depth(np.where(mask, depth, np.nan).astype(np.float64), snap)
    np.save(out / 'visible_points.npy', pts)
    vis = {'x_front': float(pts[:, 0].min()), 'y_center': float((pts[:, 1].min() + pts[:, 1].max()) / 2),
           'W_vis': float(pts[:, 1].max() - pts[:, 1].min()), 'H_vis': float(pts[:, 2].max() - pts[:, 2].min())}
    (out / 'observation.json').write_text(json.dumps({'camera': snap, 'intrinsics': snap['intrinsics'], 'image': 'rgb.png',
                                                     'mask_source': 'depth'}, indent=2))
    (out / 'state.json').write_text(json.dumps({'visible': vis}, indent=2))
    return vis


def prepare(outroot):
    import mujoco
    for rock, level, height in ROCKS:
        env = scene(rock, level, height)
        tm = truth_mesh(env); tdir = outroot / rock; tdir.mkdir(parents=True, exist_ok=True); tm.export(str(tdir / 'truth_world.stl'))
        vm = VV.VisualModel(env, {'obstacle0': rock})
        cid = mujoco.mj_name2id(vm.m, mujoco.mjtObj.mjOBJ_CAMERA, 'front_cam')
        for sun, sd in SUNS.items():
            cdir = tdir / sun
            if (cdir / 'lux_request.json').exists():
                continue
            vm.set_sun(sd)
            rgb, depth, seg = vm.render_camera(env.data, 'front_cam')
            snap = camera_io.capture(vm.m, vm.d, cid, vm.W, vm.H)
            truth = np.isin(seg, vm.rock_geoms['obstacle0'])
            rock_m, h, info = SH.rock_mask_depth(depth, snap)
            shadow, med = SH.shadow_mask(rgb, h)
            naive = SH.naive_mask(rgb, rock_m, med)
            write_obs(cdir / 'obs', rgb, depth, rock_m, snap)
            hi, depth_hi = vm.render_camera(env.data, 'front_cam', depth=True, seg=False, size=(4040, 3030))
            K_hi = SH.hi_intrinsics(snap, 4040, 3030)
            rock_hi, h_hi, _ = SH.rock_mask_depth(depth_hi, snap, K=K_hi, plane=info['plane'])
            _, med_hi = SH.shadow_mask(hi, h_hi)
            naive_hi = SH.naive_mask(hi, rock_hi, med_hi)
            size = int(PROTO['inputs']['upload_px'])
            tb = lambda m: v3_obs._square_crop(v3_obs._pixel_box(m), float(PROTO['inputs']['tight_pad_frac']), 4040, 3030, 64)
            imgs = {'A_naive': v3_obs._crop_image(hi, tb(naive_hi), size),
                    'B_naive': v3_obs._masked_variant(hi, naive_hi, tb(naive_hi), size),
                    'B_depth': v3_obs._masked_variant(hi, rock_hi, tb(rock_hi), size)}
            items = []
            (cdir / 'inputs').mkdir(parents=True, exist_ok=True)
            for k, arr in imgs.items():
                for rep in (1, 2):
                    p = cdir / 'inputs' / f'{k}{rep}.png'; Image.fromarray(arr).save(p)
                    items.append({'id': f'{k}{rep}', 'variant': k, 'path': str(p.relative_to(ROOT))})
            stats = {'rock': rock, 'sun': sun, 'iou_depth_vs_render': round(SH.mask_iou(rock_m, truth), 4),
                     'iou_naive_vs_render': round(SH.mask_iou(naive, truth), 4),
                     'naive_over_truth_px': round(float(naive.sum() / max(truth.sum(), 1)), 3),
                     'rock_dark_frac': round(float(((SH.luminance(rgb) < 0.45 * med) & truth).sum() / max(truth.sum(), 1)), 3),
                     'rock_kept_by_2d_shadow_removal': round(float(((SH.luminance(rgb) >= 0.45 * med) & truth).sum() / max(truth.sum(), 1)), 3),
                     'shadow_px': int(shadow.sum())}
            (cdir / 'stats.json').write_text(json.dumps(stats, indent=2))
            (cdir / 'lux_request.json').write_text(json.dumps({'schema': 'v7-lux-request/v1', 'mode': 'img', 'version': 'G1-Turbo',
                                                              'faceCount': 30000, 'items': items,
                                                              'result_file': str((cdir / 'lux_result.json').relative_to(ROOT)),
                                                              'result_schema': RESULT_SCHEMA}, indent=2, ensure_ascii=False))
            Image.fromarray(rgb).save(cdir / 'photo.png')
            ov = rgb.astype(np.float32).copy()
            ov[naive & ~rock_m] = ov[naive & ~rock_m] * 0.35 + np.array([255, 80, 60]) * 0.65
            ov[rock_m] = ov[rock_m] * 0.45 + np.array([80, 220, 120]) * 0.55
            Image.fromarray(ov.clip(0, 255).astype(np.uint8)).save(cdir / 'overlay.png')   # 绿=深度判定的石头，红=亮度法多算进来的影子
            print(json.dumps(stats))
        vm.close()


def evaluate_one(outroot, rock, sun):
    """评估一个条件，写 <cond>/eval/rows.json。由 evaluate 以子进程调用（每个条件一个进程，避免内存累积）。"""
    tdir = outroot / rock; cdir = tdir / sun
    res_p = cdir / 'lux_result.json'
    tm = trimesh.load(str(tdir / 'truth_world.stl'), force='mesh', process=False)
    V, g, vis, st = VE.build_volume(cdir / 'obs', cdir / 'eval')
    U = (V['space'] == 0)
    T = R.column_fill_top(tm, g)
    obs = v3_register.load_observation(str(cdir / 'obs'))
    above = g['zs'][None, None, :] > 0.02
    t_fp = int((T & above).any(axis=2).sum())
    rows = []
    for t in json.loads(res_p.read_text())['tasks']:
        row = {'rock': rock, 'sun': sun, 'id': t['id'], 'variant': t['id'][:-1], 'status': t.get('status'),
               'task_id': t.get('task_id'), 'glb': t.get('glb')}
        if t.get('status') == 'ok' and t.get('glb'):
            glb = ROOT / t['glb']
            rd = cdir / 'eval' / 'reg' / t['id']; rd.mkdir(parents=True, exist_ok=True)
            rec = v3_register.register(str(glb), str(cdir / 'obs'), PROTO, rd, top_k=6)
            M = np.asarray(rec['best']['M'], float)
            mesh = trimesh.load(str(glb), force='mesh', process=False)
            ev = v3_register.evaluate_matrix(mesh, obs, M)
            m = C.admission_metrics(mesh, M, V, g, ev)
            m['scale_ratio_v5'] = m['scale_ratio']; m['scale_ratio'] = VE.scale_ratio_ground(m['P'], V, g)
            hm = R.hidden_metrics(m['P'], T, U, g)
            P = m['P']
            row.update({k: m[k] for k in ('scale_ratio', 'scale_ratio_v5', 'hidden_frac', 'shell_contact', 'free_intrusion_frac', 'contour_iou')})
            row.update({'admitted': VE.admitted(m), 'rear_err_m': hm['rear_err_m'], 'top_err_m': hm['top_err_m'],
                        'path_p95_mm': hm['path_p95_mm'],
                        'hidden_iou': round(float((P & U & T).sum() / max(1, ((P & U) | (T & U)).sum())), 4),
                        'footprint_ratio': round(float((P & above).any(axis=2).sum() / max(t_fp, 1)), 3), 'M': M.tolist()})
            del P, m, mesh
        rows.append(row); print(json.dumps({k: row.get(k) for k in ('rock', 'sun', 'id', 'admitted', 'rear_err_m', 'footprint_ratio', 'hidden_iou')}))
    (cdir / 'eval' / 'rows.json').write_text(json.dumps({'lux_result_sha256': _sha(res_p), 'metric_version': 2, 'rows': rows}, indent=2))


def _sha(p):
    import hashlib
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def evaluate(outroot, out_arg):
    import subprocess
    rows = []
    for rock, level, height in ROCKS:
        for sun in SUNS:
            cdir = outroot / rock / sun
            res_p = cdir / 'lux_result.json'
            if not res_p.exists():
                continue
            rp = cdir / 'eval' / 'rows.json'
            fresh = rp.exists() and json.loads(rp.read_text()).get('lux_result_sha256') == _sha(res_p) \
                and json.loads(rp.read_text()).get('metric_version') == 2
            if not fresh:                  # 结果文件变了（或从未评估）才重算
                subprocess.run([sys.executable, __file__, '--eval-one', f'{rock}:{sun}', '--out', out_arg], check=True)
            rows += json.loads(rp.read_text())['rows']
    (outroot / 'eval_rows.json').write_text(json.dumps(rows, indent=2))
    # 汇总：按 输入变体 × 太阳角度
    summ = {}
    for r in rows:
        if r.get('status') != 'ok' or 'admitted' not in r:
            continue
        k = f"{r['variant']}|{r['sun']}"
        s = summ.setdefault(k, {'n': 0, 'admitted': 0, 'abs_rear': [], 'footprint': [], 'hidden_iou': []})
        s['n'] += 1; s['admitted'] += int(r['admitted'])
        if r['rear_err_m'] is not None:
            s['abs_rear'].append(abs(r['rear_err_m']))
        s['footprint'].append(r['footprint_ratio']); s['hidden_iou'].append(r['hidden_iou'])
    out = {k: {'n': v['n'], 'admitted': v['admitted'],
               'median_abs_rear_m': round(float(np.median(v['abs_rear'])), 4) if v['abs_rear'] else None,
               'median_footprint_ratio': round(float(np.median(v['footprint'])), 3) if v['footprint'] else None,
               'median_hidden_iou': round(float(np.median(v['hidden_iou'])), 4) if v['hidden_iou'] else None}
           for k, v in sorted(summ.items())}
    (outroot / 'summary.json').write_text(json.dumps(out, indent=2, ensure_ascii=False)); print(json.dumps(out, indent=1))


def sheet(outroot, dst):
    """联系表：每块岩石一张。每行一个太阳角度：照片叠加（绿=深度石头，红=亮度法多算的部分）+ 三种输入。"""
    from PIL import ImageDraw, ImageFont
    try:
        F = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 22, index=2)
    except OSError:
        F = ImageFont.load_default()
    dst = pathlib.Path(dst); dst.mkdir(parents=True, exist_ok=True)
    for rock, _, _ in ROCKS:
        tdir = outroot / rock
        suns = [s for s in SUNS if (tdir / s / 'overlay.png').exists()]
        if not suns:
            continue
        S = Image.new('RGB', (800 + 3 * 410 + 40, len(suns) * 650 + 10), 'white'); d = ImageDraw.Draw(S)
        for i, sun in enumerate(suns):
            y = 10 + i * 650
            st = json.loads((tdir / sun / 'stats.json').read_text())
            S.paste(Image.open(tdir / sun / 'overlay.png').resize((800, 600)), (10, y + 40))
            d.text((10, y + 6), f"{rock} | {sun} | IoU depth {st['iou_depth_vs_render']}  naive {st['iou_naive_vs_render']}  "
                               f"2D-shadow-removal keeps {st['rock_kept_by_2d_shadow_removal']}", font=F, fill=(20, 20, 20))
            for j, k in enumerate(('A_naive', 'B_naive', 'B_depth')):
                S.paste(Image.open(tdir / sun / 'inputs' / f'{k}1.png').resize((400, 400)), (830 + j * 410, y + 140))
                d.text((830 + j * 410, y + 104), k, font=F, fill=(20, 20, 20))
        S.save(dst / f'shadow_exp_{rock}.png'); print(dst / f'shadow_exp_{rock}.png')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--prepare', action='store_true'); ap.add_argument('--evaluate', action='store_true')
    ap.add_argument('--sheet', default=None, help='联系表输出目录，例如 docs/v7')
    ap.add_argument('--eval-one', default=None, help=argparse.SUPPRESS)
    ap.add_argument('--out', default='runs/v7/shadow_exp'); ap.add_argument('--rocks', default=None)
    a = ap.parse_args()
    if a.rocks:
        ROCKS = [r for r in ROCKS if r[0] in a.rocks.split(',')]
    outroot = (ROOT / a.out).resolve(); outroot.mkdir(parents=True, exist_ok=True)
    if a.prepare:
        if len(ROCKS) > 1:              # 每块岩石一个子进程：4040×3030 渲染器在同一进程里反复创建会累积显存/内存
            import subprocess
            for r in ROCKS:
                subprocess.run([sys.executable, __file__, '--prepare', '--out', a.out, '--rocks', r[0]], check=True)
        else:
            prepare(outroot)
    if a.eval_one:
        evaluate_one(outroot, *a.eval_one.split(':'))
    if a.evaluate:
        evaluate(outroot, a.out)
    if a.sheet:
        sheet(outroot, ROOT / a.sheet)
