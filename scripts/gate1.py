"""
第 1 关验收：四项检查，全部用**函数返回值**判定，不读任何历史文件。

  python scripts/gate1.py [--out runs/gate1_<ts>] [--inject-failure ITEM 3]

与旧实现的区别（复查意见任务 3）：
  · 不再忽略子进程返回码、不再读固定路径的 JSON —— 旧文件不可能让本次判 PASS
  · 不强制改 PYTHONPATH；使用当前进程已有的环境
  · 先建输出目录再跑检查，失败时也能留下报告
  · 「稳定站立」改名为「模型加载与重力冒烟」，因为它只验证加载、自由度与重力方向
"""
import argparse
import json
import pathlib
import sys
import tempfile
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import build_scene
import check_collision
import exam

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROCESSED = ROOT / 'assets/processed'


def check_model_load_and_gravity():
    """模型加载 + 自由度 + 重力方向 + 能连续推进（不声称"稳定站立"）。"""
    import mujoco
    m = mujoco.MjModel.from_xml_string(build_scene.moon_scene_xml())
    d = mujoco.MjData(m)
    for _ in range(500):
        mujoco.mj_step(m, d)
    ok = (abs(m.opt.gravity[2] + 1.62) < 1e-9 and m.nu == 16 and m.nq == 23
          and all(abs(x) < 1e6 for x in d.qpos))
    return ok, {'gravity': [round(float(g), 6) for g in m.opt.gravity],
                'nq': m.nq, 'nu': m.nu, 'ngeom': m.ngeom,
                'body_z_after_1s': round(float(d.qpos[2]), 3),
                'note': '仅验证加载/自由度/重力方向，不代表姿态稳定'}


def check_collision_contrast(tmp):
    r = check_collision.run_check(tmpdir=tmp)
    return r['pass'], r


def check_lux3d_object_contact(tmp):
    asset = PROCESSED / 'cargo_crate_w300'
    if not (asset / 'manifest.json').exists():
        return False, {'error': 'asset_missing', 'asset': str(asset)}
    rec = exam.run(str(asset), stance='low', controller='hold', y_offset=0.0)
    ok = rec.get('status') == 'ok' and rec.get('contact_any') is True
    return ok, {k: rec.get(k) for k in
                ('status', 'outcome', 'contact_any', 'contact_wheel',
                 'first_contact_s', 'first_wheel_contact_s', 'final_x', 'finish_x')}


def check_scripted_drive(tmp):
    """平地驱动：两种站姿各跑一次，必须越过终点且不倾覆。"""
    out, ok = {}, True
    for stance in ('low', 'high'):
        rec = exam.run(None, stance=stance, controller='hold', y_offset=0.0)
        out[stance] = {k: rec.get(k) for k in
                       ('outcome', 'final_x', 'finish_x', 'max_tilt_deg', 'sim_seconds')}
        ok = ok and rec.get('outcome') == 'completed'
    return ok, out


CHECKS = [
    ('ITEM 1 · 模型加载与重力冒烟', check_model_load_and_gravity, False),
    ('ITEM 2 · 几何碰撞对照（凸包 vs CoACD）', check_collision_contrast, True),
    ('ITEM 3 · Lux3D 资产进入考场并接触', check_lux3d_object_contact, True),
    ('ITEM 4 · 平地驱动（两种站姿越过终点）', check_scripted_drive, True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    ap.add_argument('--inject-failure', default=None,
                    help='故意让匹配该前缀的检查抛异常，用于验证失败会被正确传播')
    a = ap.parse_args()

    run_dir = pathlib.Path(a.out or
                           (ROOT / 'runs' / f'gate1_{time.strftime("%Y%m%d_%H%M%S")}'))
    run_dir.mkdir(parents=True, exist_ok=True)      # 先建目录，失败也能留下报告

    results, log, all_pass = {}, [], True
    for name, fn, needs_tmp in CHECKS:
        t0 = time.time()
        try:
            if a.inject_failure and name.startswith(a.inject_failure):
                raise RuntimeError(f'注入的失败（验证用）：{name}')
            with tempfile.TemporaryDirectory() as td:
                ok, detail = fn(td) if needs_tmp else fn()
        except Exception:
            ok, detail = False, {'traceback': traceback.format_exc()[-1200:]}
        elapsed = round(time.time() - t0, 2)
        results[name] = {'pass': bool(ok), 'seconds': elapsed, **detail}
        all_pass = all_pass and ok
        log.append(f'{"PASS" if ok else "FAIL"}  {name}  ({elapsed}s)')
        print(log[-1], flush=True)

    report = {'gate': 1, 'all_pass': all_pass,
              'injected_failure': a.inject_failure, 'checks': results}
    (run_dir / 'gate1_report.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False))
    (run_dir / 'gate1_log.txt').write_text('\n'.join(log) + '\n')
    print(f'\nGATE 1: {"PASS" if all_pass else "FAIL"}  -> {run_dir}')
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
