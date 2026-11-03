"""v3 再看一眼：真实移动到第二观察位，比较三臂的信息增量与净价值。

  A：真实移动到 S1，但只用 V0 的信息规划/续行
  B：同一个 S1，用 V0+V1 更新观测体后规划/续行
  C：从 S0 用 V0 直接行动（= 主表的 OBS_ONLY 臂）

触发规则（先写进协议，运行前不看结果）：FULL 多数出现"预演安全但真值失败"优先，
其次"安全停下但真值可通行"，再按状态 ID 排序；最多 4 个状态。

  python scripts/v3_look_again.py --protocol plans/v3_protocol.json --max 2
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mujoco

import camera_io
import v3_core
import v3_fuse
import v3_obs

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'runs/v3/look_again'


def _capture_at(env, out_dir, proto, tag):
    """在当前位置采集规划相机观测（与主观测同一相机/分辨率/噪声种子）。"""
    from PIL import Image
    model, data = env.model, env.data
    cam_id = v3_obs.observe.cam_id_of(env)
    plan = proto['cameras']['planning']
    W, H = int(plan['width']), int(plan['height'])
    model.cam_fovy[cam_id] = float(plan['fovy_deg'])
    mujoco.mj_forward(model, data)
    rgb, depth = v3_obs._render(model, data, cam_id, W, H)
    mask = v3_obs._mask_by_segmentation(model, data, cam_id, W, H)
    snap = camera_io.capture(model, data, cam_id, W, H)
    rng = np.random.default_rng(int(proto['visibility']['depth_noise_seed']) + 7)
    sigma = float(proto['visibility']['depth_noise_sigma_m'])
    d = np.asarray(depth, dtype=np.float32).copy()
    valid = np.isfinite(d) & (d > 0) & (d < 100)
    d[valid] = np.maximum(d[valid] + rng.normal(0, sigma, int(valid.sum())).astype(np.float32),
                          1e-4)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / 'depth.npy', d)
    Image.fromarray(rgb).save(out_dir / 'rgb.png')
    Image.fromarray((mask * 255).astype(np.uint8)).save(out_dir / 'mask.png')
    pts = v3_obs._unproject_masked(d, mask, snap)
    np.save(out_dir / 'visible_points.npy', pts)
    obs = {'schema': 'v3-observation/v1', 'observation_id': tag, 'case_id': tag,
           'observation_protocol': 'v3-look-again/v1',
           'camera_schema': camera_io.SCHEMA, 'camera': snap,
           'image': {'W': W, 'H': H}, 'intrinsics': snap['intrinsics'],
           'visible': {'n_pixels': int(len(pts)),
                       'x_front': float(pts[:, 0].min()),
                       'y_center': float((pts[:, 1].min() + pts[:, 1].max()) / 2),
                       'W_vis': float(pts[:, 1].max() - pts[:, 1].min()),
                       'H_vis': float(pts[:, 2].max() - pts[:, 2].min())},
           'truth_hidden_read': False}
    (out_dir / 'observation.json').write_text(json.dumps(obs, ensure_ascii=False, indent=2))
    return obs


def _combine_volume(obs_dirs, grid, proto):
    """V01：两个视角的公共观测合并（free 取或，band/shell 取或，其余未知）。"""
    space = None
    shell = None
    stats = []
    for d in obs_dirs:
        sp, sh, st, _ = v3_fuse.observe_volume(d, grid, proto)
        stats.append(st)
        if space is None:
            space, shell = sp.copy(), sh.copy()
        else:
            space = np.maximum(space, sp)       # 2=free 优先，其次 band
            shell = shell | sh
    return space, shell, stats


def drive_to_second_view(env, proto, lateral=0.12, seconds=1.4):
    """真实行驶到第二观察位（用现有物理入口推进，不直接改 qpos）。"""
    env.nav_target_y = env.channel_center + float(lateral)
    n = int(seconds / (1.0 / float(proto['scene']['control_hz'])))
    for _ in range(n):
        env.step_drive(v_forward_mps=0.07)
    for _ in range(60):
        env.brake_step()
        if abs(float(env.data.qvel[0])) < 0.02:
            break
    return env


def run_state(state_dir, proto, out_root=OUT):
    state_dir = pathlib.Path(state_dir)
    st = v3_core.load_state(state_dir)
    sid = st['state']['state_id']
    out = out_root / sid
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    # --- 真实移动到 S1（真值场景） ---
    spec = v3_core.truth_spec(st)
    env = v3_core.make_env(spec, proto)
    env.reset(seed=0)
    env.restore_state(st['snapshot'], mode='same_scene')
    t_s0 = float(env.t)
    drive_to_second_view(env, proto)
    s1 = env.save_state()
    t_s1 = float(env.t)
    (out / 'state_snapshot_s1.json').write_text(json.dumps(s1, ensure_ascii=False))
    obs1 = _capture_at(env, out / 'observation_v1', proto, f'{sid}_v1')
    del env
    # --- V01 ---
    art = v3_fuse.load_v_artifact(state_dir / 'fusion')
    space01, shell01, stats = _combine_volume([state_dir / 'observation', out / 'observation_v1'],
                                              art['grid'], proto)
    np.savez_compressed(out / 'V01.npz', shell=shell01, space=space01,
                        origin=art['grid']['origin'], pitch=art['grid']['pitch'],
                        dims=art['grid']['dims'])
    np.savez_compressed(out / 'obs01_occ.npz', occupied=shell01,
                        origin=np.asarray(art['grid']['origin'], float),
                        pitch=np.float64(art['grid']['pitch']),
                        dims=np.asarray(art['grid']['dims'], int),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    coll01 = out / 'coll01'
    r = v3_core.build_collision(out / 'obs01_occ.npz', coll01,
                                pitch=proto['collision']['pitch_m'],
                                downsample=int(proto['collision'].get('box_downsample', 1)))
    # --- 三臂 ---
    core1 = dict(st)
    core1['snapshot'] = s1
    rows_a, app = v3_core.rehearse(core1, {'v0': str(state_dir / 'obs_only' / 'coll')},
                                   s1, proto)
    dec_a = v3_core.aggregate(rows_a, ['v0'], {}, 'majority', proto,
                              applic={k: tuple(v) for k, v in app.items()})
    rows_b, app = v3_core.rehearse(core1, {'v01': str(coll01)}, s1, proto)
    dec_b = v3_core.aggregate(rows_b, ['v01'], {}, 'majority', proto,
                              applic={k: tuple(v) for k, v in app.items()})
    ex_a = v3_core.truth_execute(core1, dec_a['chosen'], proto, out, 'A',
                                 mode='same_scene')
    ex_b = v3_core.truth_execute(core1, dec_b['chosen'], proto, out, 'B',
                                 mode='same_scene')
    # C：主表的 OBS_ONLY 臂（从 S0 用 V0），若没有则现场跑
    c_dec_p = state_dir / 'decision' / 'decision_OBS_ONLY.json'
    c_ex_p = state_dir / 'decision' / 'execution_OBS_ONLY.json'
    dec_c = json.loads(c_dec_p.read_text())['decision'] if c_dec_p.is_file() else None
    ex_c = json.loads(c_ex_p.read_text()) if c_ex_p.is_file() else None
    if ex_c is None:
        dec_c = dec_a
        ex_c = v3_core.truth_execute(st, dec_c['chosen'], proto, out, 'C',
                                     mode='same_scene')
    rec = {'schema': 'v3-look-again/v1', 'state_id': sid,
           'trigger': {'rule': proto['observe']['trigger_rule'],
                       'priority': proto['observe']['priority'],
                       'selected_because': 'pre-registered priority order'},
           'baseline': {'t_s0': round(t_s0, 3), 't_s1': round(t_s1, 3),
                        'lateral_m': 0.12, 'forward_s': 1.4,
                        'observed_pixels_v1': obs1['visible']['n_pixels'],
                        'v01_shell_voxels': int(shell01.sum())},
           'A': {'info': 'V0 only, state S1', 'chosen': dec_a['chosen'],
                 'reason': dec_a['reason'], 'votes': dec_a['votes'],
                 'outcome': ex_a.get('outcome'), 'exec_reason': ex_a.get('reason'),
                 'final_x': ex_a.get('final_x'), 't_end': ex_a.get('t_end'),
                 'total_from_s0_s': ex_a.get('t_end')},
           'B': {'info': 'V0+V1, state S1', 'chosen': dec_b['chosen'],
                 'reason': dec_b['reason'], 'votes': dec_b['votes'],
                 'outcome': ex_b.get('outcome'), 'exec_reason': ex_b.get('reason'),
                 'final_x': ex_b.get('final_x'), 't_end': ex_b.get('t_end'),
                 'total_from_s0_s': ex_b.get('t_end')},
           'C': {'info': 'V0 only, state S0', 'chosen': (dec_c or {}).get('chosen'),
                 'outcome': (ex_c or {}).get('outcome'),
                 'exec_reason': (ex_c or {}).get('reason'),
                 'final_x': (ex_c or {}).get('final_x'),
                 'total_from_s0_s': (ex_c or {}).get('t_end')},
           'info_gain_A_to_B': {'action_changed': dec_a['chosen'] != dec_b['chosen'],
                                'outcome_changed': ex_a.get('outcome') != ex_b.get('outcome')},
           'net_value_B_vs_C': {'outcome_changed': (ex_b.get('outcome')
                                                    != (ex_c or {}).get('outcome')),
                                'extra_time_s': (round(float(ex_b.get('t_end') or 0)
                                                       - float((ex_c or {}).get('t_end') or 0), 3))},
           'wall_s': round(time.time() - t0, 2),
           'observation_failure': False,
           'note': 'A/B 从同一个 S1 恢复；C 从 S0；三臂都用真实物理推进，不重置时钟'}
    (out / 'look_again.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def pick_states(proto, max_n=4):
    res_p = ROOT / 'runs/v3/report/v3_results.json'
    if not res_p.is_file():
        return []
    res = json.loads(res_p.read_text())
    pairs = res['summary'].get('pairs') or []
    # 优先级 1：FULL 预演认为安全但真值失败（risk underestimate）
    pri = []
    for p in pairs:
        if p['FULL'] == 'physical_failure':
            pri.append((0, p['state_id']))
        elif p['OBS_ONLY'] == 'pass' and p['FULL'] != 'pass':
            pri.append((1, p['state_id']))
        elif p['FULL'] == 'safe_stop':
            pri.append((2, p['state_id']))
    pri.sort()
    return [sid for _, sid in pri[:int(max_n)]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    ap.add_argument('--state', nargs='*', default=None)
    ap.add_argument('--max', type=int, default=4)
    a = ap.parse_args()
    proto = json.loads((ROOT / a.protocol).read_text())
    ids = a.state or pick_states(proto, a.max)
    rows = []
    for sid in ids:
        try:
            r = run_state(ROOT / 'runs/v3/states' / sid, proto)
            rows.append({k: r[k] for k in ('state_id', 'A', 'B', 'C',
                                           'info_gain_A_to_B', 'net_value_B_vs_C')})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001
            rows.append({'state_id': sid, 'error': f'{type(e).__name__}: {e}'})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'index.json').write_text(json.dumps({'schema': 'v3-look-again-index/v1',
                                                'n': len(rows), 'rows': rows},
                                               ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
