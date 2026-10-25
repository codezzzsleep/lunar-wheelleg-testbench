"""
第 1 关（生死关）一键验收。

四项：
  1. MuJoCo + go2w 在月球重力下能跑
  2. 碰撞对照：原始网格被当成凸包；CoACD 拆块后孔洞真实存在
  3. 一个 Lux3D 物体：生成 → 定尺度 → 拆凸块 → 进场景 → 被轮子碰到
  4. 脚本控制器让 Go2W 在平地上开出 5 m 不倒

用法：python scripts/gate1.py [--skip-generate]
"""
import json, pathlib, subprocess, sys, time
import mujoco

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
RESULTS = {}


def step(name, fn):
    print(f'\n=== {name} ' + '=' * (58 - len(name)))
    t0 = time.time()
    try:
        ok, detail = fn()
    except SystemExit as e:
        ok, detail = (e.code == 0), {}
    except Exception as e:
        ok, detail = False, {'error': repr(e)[:300]}
    RESULTS[name] = {'pass': bool(ok), 'seconds': round(time.time() - t0, 1), **detail}
    print(f'-> {"PASS" if ok else "FAIL"}  ({RESULTS[name]["seconds"]}s)')
    return ok


def check_robot():
    import build_scene
    p = build_scene.build()
    m = mujoco.MjModel.from_xml_path(str(p))
    d = mujoco.MjData(m)
    for _ in range(2000):
        mujoco.mj_step(m, d)
    ok = abs(m.opt.gravity[2] + 1.62) < 1e-6 and m.nu == 16 and m.nq == 23 and d.qpos[2] > 0
    return ok, {'gravity': list(map(float, m.opt.gravity)), 'nu': m.nu,
                'nq': m.nq, 'body_z_after_4s': round(float(d.qpos[2]), 3)}


def check_collision():
    subprocess.run([sys.executable, 'scripts/check_collision.py'], cwd=ROOT,
                   env={'PYTHONPATH': '/tmp/robolib', 'PATH': '/usr/bin:/bin'}, capture_output=True)
    r = json.loads((ROOT / 'runs/gate1_collision.json').read_text())
    return r['gate2_pass'], r


def check_lux3d_object():
    subprocess.run([sys.executable, 'scripts/exam.py', '--asset',
                    'assets/processed/cargo_crate', '--stance', 'low'],
                   cwd=ROOT, env={'PYTHONPATH': '/tmp/robolib', 'PATH': '/usr/bin:/bin'},
                   capture_output=True)
    r = json.loads((ROOT / 'runs/gate1_exam.json').read_text())
    return r['first_contact_s'] is not None, {
        'first_contact_s': r['first_contact_s'], 'outcome': r['outcome'],
        'rel_height': r['obstacle']['rel_height'], 'parts': r['obstacle']['coacd_parts']}


def check_controller():
    subprocess.run([sys.executable, 'scripts/drive_test.py'], cwd=ROOT,
                   env={'PYTHONPATH': '/tmp/robolib', 'PATH': '/usr/bin:/bin'}, capture_output=True)
    r = json.loads((ROOT / 'runs/gate1_drive.json').read_text())
    ok = all(v['passed_5m'] for v in r.values())
    return ok, {k: {'distance_m': v['distance_m'], 'max_tilt_deg': v['max_tilt_deg'],
                    'ride_height_m': v['final_z']} for k, v in r.items()}


if __name__ == '__main__':
    step('ITEM 1 · go2w 月球重力', check_robot)
    step('ITEM 2 · 碰撞对照 raw vs CoACD', check_collision)
    step('ITEM 3 · Lux3D 物体进考场并接触', check_lux3d_object)
    step('ITEM 4 · 脚本控制器 5 m 不倒', check_controller)

    allpass = all(v['pass'] for v in RESULTS.values())
    out = ROOT / 'runs/gate1_report.json'
    out.write_text(json.dumps({'gate': 1, 'all_pass': allpass, 'checks': RESULTS}, indent=2, ensure_ascii=False))
    print('\n' + '=' * 62)
    for k, v in RESULTS.items():
        print(f'{"PASS" if v["pass"] else "FAIL"}  {k}')
    print(f'\nGATE 1: {"PASS" if allpass else "FAIL"}   -> {out}')
    raise SystemExit(0 if allpass else 1)
