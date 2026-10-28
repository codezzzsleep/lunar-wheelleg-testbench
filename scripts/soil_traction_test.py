"""
单轮牵引上限判别测试：验证 H = A*c + W*tanφ 真的限制可提供的切向牵引。

  MUJOCO_GL=osmesa .venv/bin/python scripts/soil_traction_test.py --out runs/unseen/recovery_r3/soil

与"改参数后 x 不同"相比更有判别力：
  · 单轮、平地、初始静止、无其他水平驱动力；
  · c=0 且 phi=0 时 H=0 -> 不应产生持续水平牵引（轮子只原地打滑）；
  · 固定轮载下逐步加大驱动扭矩，测**实际接触切向力**，与声明的 H 比较；
  · 改变 c/phi，检查允许的最大牵引是否按公式变化。
"""
import argparse, json, pathlib, sys
import numpy as np, mujoco
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from soil import SoilParams, VERSION as SOIL_VERSION

MOON_G = 1.62
R, BW = 0.086, 0.0526


def build(pm, load_n):
    return f"""
<mujoco model="tw"><option gravity="0 0 -{MOON_G}" timestep="0.0005" integrator="implicitfast"/>
  <worldbody>
    <geom name="ground" type="plane" size="3 3 .1" friction="0.9 0.02 0.001"/>
    <body name="carrier" pos="0 0 0.5">
      <joint name="slide_x" type="slide" axis="1 0 0"/>
      <joint name="slide_z" type="slide" axis="0 0 1"/>
      <geom name="ballast" type="sphere" size="0.01" mass="0.5" contype="0" conaffinity="0"/>
      <body name="wheel" pos="0 0 0">
        <joint name="spin" type="hinge" axis="0 1 0"/>
        <geom name="tyre" type="cylinder" size="{R} {BW/2}"
              quat="0.7071067811865476 0.7071067811865476 0 0"
              mass="0.4" friction="0.9 0.02 0.001"/>
      </body>
    </body>
  </worldbody>
</mujoco>"""


def run(pm, load_n, torque, seconds=1.0):
    m = mujoco.MjModel.from_xml_string(build(pm, load_n))
    d = mujoco.MjData(m)
    wid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'wheel')
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'carrier')
    m.body_pos[cid][2] = R
    mujoco.mj_forward(m, d)
    tid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'tyre')
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'ground')
    mu0 = float(m.geom_friction[tid][0])
    n = int(seconds / m.opt.timestep)
    ft_hist, x_hist, mu_hist = [], [], []
    z_t = pm.sinkage(load_n, BW, R)
    A_c = BW * float(np.sqrt(max(2 * R * z_t, 1e-9)))
    H_rule = pm.traction_limit(load_n, A_c)
    mu_eff = float(np.clip(H_rule / max(load_n, 1e-9), 0.0, mu0))
    for _ in range(n):
        d.xfrc_applied[wid][2] = -load_n            # 轮载（力）
        d.qfrc_applied[2] = torque                  # 驱动扭矩（绕轮轴；qvel[0]=x, 1=z, 2=spin）
        # 与整机同一土壤规则：等效摩擦上限 mu_eff = H / W（替换，不叠加）
        # MuJoCo 的接触摩擦取两个 geom 的**逐元素较大值**，所以两边都要设
        m.geom_friction[tid][0] = mu_eff
        m.geom_friction[gid][0] = mu_eff
        mujoco.mj_step(m, d)
        mu_hist.append(mu_eff)
        ft = 0.0
        for c in range(d.ncon):
            buf = np.zeros(6)
            mujoco.mj_contactForce(m, d, c, buf)
            ft += np.hypot(buf[1], buf[2])
        ft_hist.append(ft); x_hist.append(float(d.qpos[0]))
        _ = d.qvel
    tail = ft_hist[-int(0.5 * n):]
    return {'mu_eff': round(float(mu_eff), 4),
            'ft_max_n': float(np.max(tail)) if tail else 0.0,
            'ft_p50_n': float(np.median(tail)) if tail else 0.0,
            'ft_p95_n': float(np.percentile(tail, 95)) if tail else 0.0,
            'ft_mean_n': float(np.mean(tail)) if tail else 0.0,
            'dx_m': float(x_hist[-1] - x_hist[0]),
            'spin_rad_s': float(d.qvel[2])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--load', type=float, default=30.0)
    ap.add_argument('--torques', type=float, nargs='+', default=[0.2, 0.5, 1.0, 2.0, 4.0])
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for c_pa, phi in ((0.0, 0.0), (170.0, 0.0), (0.0, 35.0), (170.0, 35.0)):
        pm = SoilParams(kc=1400.0, kphi=820000.0, n=1.0, cohesion_pa=c_pa,
                        phi_deg=phi, k_shear=0.018)
        A = BW * np.sqrt(max(2 * R * pm.sinkage(a.load, BW, R), 1e-9))
        H = pm.traction_limit(a.load, A)
        for tq in a.torques:
            r = run(pm, a.load, tq)
            rows.append({'cohesion_pa': c_pa, 'phi_deg': phi, 'H_n': round(H, 4),
                         'contact_area_m2': round(float(A), 6),
                         'torque_nm': tq, 'drive_force_n': round(tq / R, 3),
                         **{k: round(v, 4) for k, v in r.items()}})
    (out / 'traction_test.json').write_text(json.dumps({
        'version': 'soil-traction/v1', 'soil_version': SOIL_VERSION,
        'wheel_radius_m': R, 'wheel_width_m': BW, 'load_n': a.load,
        'rule': 'H = A*c + W*tan(phi)；等效摩擦 mu_eff = H/W',
        'note': ('单轮平地静置；驱动扭矩逐步加大；测实际接触切向力与 H 比较。'
                 '这不是整机动力学，也不证明月壤物理正确'),
        'rows': rows}, indent=2, ensure_ascii=False))
    print(f"{'c':>6s}{'phi':>5s}{'H':>7s}{'tq':>6s}{'Fdrive':>8s}"
          f"{'Ft_p50':>8s}{'Ft_p95':>8s}{'dx':>8s}{'p95>H':>7s}")
    for r in rows:
        over = 'YES' if r['ft_p95_n'] > r['H_n'] + 1e-3 else 'no'
        print(f"{r['cohesion_pa']:>6.1f}{r['phi_deg']:>5.1f}{r['H_n']:>7.2f}"
              f"{r['torque_nm']:>6.2f}{r['drive_force_n']:>8.2f}{r['ft_p50_n']:>8.2f}"
              f"{r['ft_p95_n']:>8.2f}{r['dx_m']:>8.4f}{over:>7s}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
