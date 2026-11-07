"""预演可复现性检查：同一观测、同一份计划，把 OBS_CONS 实心几何上的 R1 预演（3 种扰动）重跑若干次，
逐帧对比轨迹，并与已有运行的记录对比。

    MUJOCO_GL=egl python3 scripts/v7/v7_determinism.py --obs runs/v7/route_full_r2/E1/look1 \
        --out runs/v7/determinism_e1_span32 --span 32 --repeat 2 \
        --ref runs/v7/route_full_r2/E1/decide_look1/OBS_CONS/solid \
        --ref runs/v7/route_full_r2_v72/E1/decide_look1/OBS_CONS/solid

每次重跑在独立进程里完成。--span 设预演平地高度场的半边长（terrain.SPAN；路线进程里是 32，单独运行时默认 4）。产出 summary.json：
  platform      CPU 型号、指令集、mujoco/numpy 版本
  runs          每个来源（rep0、rep1、各 ref）每种扰动的结果：是否成功、代价、时长、各块轨迹的 sha256
  compare       rep 与 rep、rep 与 ref：轨迹是否逐位相同；不同时给出第一帧出现差异的位置与该帧的最大差值
不调用 Lux3D，不改动任何已有运行目录。
"""
import argparse
import json
import os
import pathlib
import platform
import subprocess
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(HERE))


def rel(p):
    p = pathlib.Path(p)
    return p if p.is_absolute() else ROOT / p


def platform_info():
    info = {'python': platform.python_version(), 'machine': platform.machine(), 'cpu_count': os.cpu_count()}
    try:
        txt = pathlib.Path('/proc/cpuinfo').read_text()
        info['cpu_model'] = next((l.split(':', 1)[1].strip() for l in txt.splitlines() if l.startswith('model name')), None)
        flags = next((l.split(':', 1)[1].split() for l in txt.splitlines() if l.startswith('flags')), [])
        info['simd'] = sorted(f for f in flags if f in ('sse4_2', 'avx', 'avx2', 'fma', 'avx512f', 'avx512dq', 'avx512vl'))
    except OSError:
        pass
    import mujoco
    info['mujoco'] = mujoco.__version__; info['numpy'] = np.__version__
    return info


def one(obs, out):
    import v3_register, v5_core as C, v5_eval as E  # noqa: E401
    import v7_encounter as VE
    out.mkdir(parents=True, exist_ok=True)
    V, g, vis, st = VE.build_volume(obs, out)
    o = v3_register.load_observation(str(obs))
    sh = C.shadow_mask(V, g, o)
    snap, ref = VE.local_snapshot(st, 1.2, V, out)
    solid = V['shell'] | sh
    det = E.plan_detour(solid, V, vis, 1.2)
    plan = VE.plan_for('OBS_CONS', 2.45, det)
    E.robust_arm(solid, V, snap, ref, vis, plan, ['R1'], out / 'solid', 1.2, tag='obs_solid')
    (out / 'plan.json').write_text(json.dumps(plan, indent=2))


def cells(arm_dir):
    """arm_dir/rehearsal_3of3.json + p{i}/R1/index.json -> 每种扰动的结果与轨迹块哈希。"""
    arm_dir = rel(arm_dir)
    rh = json.loads((arm_dir / 'rehearsal_3of3.json').read_text())
    res = {}
    for e in rh['entries']:
        if e['action'] != 'R1':
            continue
        p = int(e['perturb']); idx = arm_dir / f'p{p}' / 'R1' / 'index.json'
        ch = json.loads(idx.read_text())['chunks'] if idx.exists() else []
        res[p] = {'success': e['success'], 'contacts': e['contacts'], 'cost': e['cost'], 't_end': e['t_end'],
                  'chunks': [c['arrays_sha256'] for c in ch], 'dir': str(idx.parent)}
    return res


def first_diff(da, db):
    """逐块读取 qpos，返回第一帧出现差异的序号与该帧的最大差值；块文件缺失（例如只有 LFS 指针）时返回 None。"""
    fa = sorted(pathlib.Path(da).glob('chunk_*.npz')); fb = sorted(pathlib.Path(db).glob('chunk_*.npz'))
    k = 0
    for a, b in zip(fa, fb):
        try:
            qa, qb = np.load(a)['qpos'], np.load(b)['qpos']
        except Exception:  # noqa: BLE001
            return None
        n = min(len(qa), len(qb)); d = np.abs(qa[:n] - qb[:n]).max(axis=1)
        nz = np.nonzero(d > 0)[0]
        if len(nz):
            i = int(nz[0]); return {'frame': k + i, 'max_abs_diff': float(d[i]),
                                    'max_abs_diff_after_50_frames': float(d[min(i + 50, n - 1)])}
        k += n
    return {'frame': None, 'max_abs_diff': 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--repeat', type=int, default=2); ap.add_argument('--ref', action='append', default=[])
    ap.add_argument('--one', type=int, default=None); ap.add_argument('--span', type=float, default=None)
    a = ap.parse_args()
    if a.span is not None:
        import terrain
        terrain.SPAN = a.span
    obs, out = rel(a.obs), rel(a.out)
    if a.one is not None:
        one(obs, out / f'rep{a.one}'); return
    out.mkdir(parents=True, exist_ok=True)
    for i in range(a.repeat):
        if not (out / f'rep{i}' / 'solid' / 'rehearsal_3of3.json').exists():
            subprocess.run([sys.executable, __file__, '--obs', str(obs), '--out', str(out), '--one', str(i)]
                           + ([] if a.span is None else ['--span', str(a.span)]), check=True)
    src = {f'rep{i}': out / f'rep{i}' / 'solid' for i in range(a.repeat)}
    src.update({f'ref{j}': rel(r) for j, r in enumerate(a.ref)})
    runs = {k: cells(v) for k, v in src.items()}
    keys = list(src); cmp = []
    for i, ka in enumerate(keys):
        for kb in keys[i + 1:]:
            for p in sorted(set(runs[ka]) & set(runs[kb])):
                ra, rb = runs[ka][p], runs[kb][p]
                same = ra['chunks'] == rb['chunks'] and bool(ra['chunks'])
                cmp.append({'a': ka, 'b': kb, 'perturb': p, 'identical': same,
                            'success': [ra['success'], rb['success']], 'cost': [ra['cost'], rb['cost']],
                            'first_diff': None if same else first_diff(ra['dir'], rb['dir'])})
    summ = {'schema': 'v7-determinism/v1', 'obs': str(a.obs), 'span': a.span, 'sources': {k: str(v) for k, v in src.items()},
            'platform': platform_info(), 'runs': runs, 'compare': cmp}
    (out / 'summary.json').write_text(json.dumps(summ, indent=2, ensure_ascii=False))
    for c in cmp:
        print(json.dumps({k: c[k] for k in ('a', 'b', 'perturb', 'identical', 'success', 'first_diff')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
