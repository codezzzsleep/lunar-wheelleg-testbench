"""
月壤单轮标定：Bekker 目标下陷 vs MuJoCo 实测下陷。

  MUJOCO_GL=osmesa .venv/bin/python scripts/soil_single_wheel.py \
      --out runs/unseen/recovery_r3/soil

做法（明确的近似，写在这里而不是藏起来）：
  1. 用 soil.SoilParams 由轮载 W 求目标下陷 z_target（刚性轮 L=sqrt(2Rz) 迭代）；
  2. 把轮–土接触建成**显式刚度弹簧-阻尼**：MuJoCo 的 solref 首项取负值时
     直接解释为 (stiffness, damping)，因此可以按 Bekker 的切线刚度设定，
     不必把 kc/kphi 硬塞进 solref 的时间常数语义；
  3. 单轮（圆柱 + 竖直滑轨 + 砝码）在月球重力下静置，测稳态下陷；
  4. 五个载荷档位各测一次，报目标/实测/相对误差；单参数拟合刚度使误差最小。

局限（必须如实写）：
  · 这是**单轮静置下陷**，不是整机、不是滑转/牵引；
  · MuJoCo 的接触是凸-凸离散接触点，Bekker 是平板压力分布，两者不是同一模型；
  · 因此本标定给出的是"在该弹簧近似下可达到的匹配程度"，不证明月壤物理正确。
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import mujoco

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from soil import SoilParams, VERSION as SOIL_VERSION

MOON_G = 1.62
WHEEL_R = 0.09
WHEEL_B = 0.10


def single_wheel_xml(stiffness, damping, load_n):
    """竖直滑轨上的单轮；载荷以等效力施加在轮轴上。"""
    return f"""
<mujoco model="soil_single_wheel">
  <option gravity="0 0 -{MOON_G}" timestep="0.0005" integrator="implicitfast"/>
  <worldbody>
    <geom name="ground" type="plane" size="2 2 0.1" rgba=".4 .35 .3 1"
          solref="-{stiffness:.6g} -{damping:.6g}" solimp="0.99 0.995 0.001"
          friction="0.9 0.02 0.001"/>
    <body name="carrier" pos="0 0 0.5">
      <joint name="slide" type="slide" axis="0 0 1" limited="false"
             damping="0.5" armature="0"/>
      <geom name="axle" type="sphere" size="0.02" mass="0.02" contype="0" conaffinity="0"/>
      <body name="wheel" pos="0 0 0">
        <joint name="spin" type="hinge" axis="0 1 0" damping="0.002"/>
        <geom name="tyre" type="cylinder" size="{WHEEL_R} {WHEEL_B/2}"
              quat="0.7071067811865476 0.7071067811865476 0 0"
              mass="0.4" friction="0.9 0.02 0.001"
              solref="-{stiffness:.6g} -{damping:.6g}" solimp="0.99 0.995 0.001"/>
      </body>
    </body>
  </worldbody>
</mujoco>"""


def measure_sinkage(stiffness, damping, load_n, seconds=4.0):
    """返回稳态下陷（米）与是否稳定。"""
    m = mujoco.MjModel.from_xml_string(single_wheel_xml(stiffness, damping, load_n))
    d = mujoco.MjData(m)
    wid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'wheel')
    # 轮心从刚好触地（z=R）开始；slide 轴位移从 0 起算
    d.qpos[0] = 0.0
    mujoco.mj_forward(m, d)
    carrier_start = WHEEL_R
    d.qpos[0] = 0.0
    d.qpos[1] = 0.0
    mujoco.mj_forward(m, d)
    # 把 carrier 放到轮心 z=R 的位置
    m.body_pos[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'carrier')][2] = carrier_start
    mujoco.mj_forward(m, d)
    z0 = float(d.xpos[wid][2])
    n = int(seconds / m.opt.timestep)
    for _ in range(n):
        d.xfrc_applied[wid][2] = -load_n      # 竖直向下的轮载（力，不是压力）
        mujoco.mj_step(m, d)
        if not np.isfinite(d.xpos[wid][2]):
            return None, False
    z = z0 - float(d.xpos[wid][2])     # 轮心下沉量
    # 稳定性：最后 1/4 时间内的速度
    v_slide = abs(float(d.qvel[0]))
    return max(0.0, z), v_slide < 5e-3


def tangent_stiffness(pm, z, b):
    """Bekker 压力对下陷的导数 ds/dz，乘以接触面积得到 N/m 量级刚度。"""
    if z <= 0:
        z = 1e-4
    dpdz = pm.n * (pm.kc / b + pm.kphi) * z ** (pm.n - 1)
    L = np.sqrt(max(2 * WHEEL_R * z, 1e-9))
    return float(dpdz * b * L)          # N/m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--loads', type=float, nargs='+',
                    default=[20.0, 40.0, 60.0, 80.0, 100.0])
    ap.add_argument('--fit', action='store_true', help='单参数拟合刚度系数')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pm = SoilParams.moon_nominal()

    rows = []
    for W in a.loads:
        z_t = pm.sinkage(W, WHEEL_B, WHEEL_R)
        k0 = tangent_stiffness(pm, z_t, WHEEL_B)
        damping = 0.9 * 2 * np.sqrt(max(k0, 1e-6) * 0.4)
        z_m, stable = measure_sinkage(k0, damping, W)
        rows.append({'load_n': W, 'z_target_mm': round(z_t * 1000, 3),
                     'z_measured_mm': (round(z_m * 1000, 3) if z_m is not None else None),
                     'rel_err': (round(abs(z_m - z_t) / max(z_t, 1e-9), 4)
                                 if z_m is not None else None),
                     'stable': stable, 'k_used': round(k0, 2),
                     'damping': round(damping, 3)})

    def eval_factor(factor, seconds=3.0):
        errs = []
        for W in a.loads:
            z_t = pm.sinkage(W, WHEEL_B, WHEEL_R)
            k0 = tangent_stiffness(pm, z_t, WHEEL_B) * factor
            dm = 0.9 * 2 * np.sqrt(max(k0, 1e-6) * 0.4)
            z_m, _ = measure_sinkage(k0, dm, W, seconds=seconds)
            if z_m is not None:
                errs.append(abs(z_m - z_t) / max(z_t, 1e-9))
        return (float(np.mean(errs)) if errs else None), (float(np.max(errs)) if errs else None)

    best = None
    if a.fit:
        # 一个**全局**系数 c：k_solref = c * k_bekker；5 档载荷共同验证，残差非构造为零
        # 对数网格扫描：刚度越小下陷越深，最优 c 通常在 1e-3..1 量级
        grid = [10 ** e for e in np.arange(-3.0, 0.51, 0.25)]
        for cand in grid:
            mean_err, max_err = eval_factor(cand)
            if mean_err is None:
                continue
            rec = {'factor': round(float(cand), 5),
                   'mean_rel_err': round(mean_err, 4),
                   'max_rel_err': round(max_err, 4)}
            if best is None or rec['mean_rel_err'] < best['mean_rel_err']:
                best = rec
        # 在最优点附近细化
        if best:
            c0 = best['factor']
            for cand in (c0 * 0.7, c0 * 0.85, c0 * 1.15, c0 * 1.4):
                mean_err, max_err = eval_factor(cand)
                if mean_err is not None and mean_err < best['mean_rel_err']:
                    best = {'factor': round(float(cand), 5),
                            'mean_rel_err': round(mean_err, 4),
                            'max_rel_err': round(max_err, 4)}

    if a.fit and best:
        calib = []
        for W in a.loads:
            z_t = pm.sinkage(W, WHEEL_B, WHEEL_R)
            k0 = tangent_stiffness(pm, z_t, WHEEL_B) * best['factor']
            dm = 0.9 * 2 * np.sqrt(max(k0, 1e-6) * 0.4)
            z_m, stable = measure_sinkage(k0, dm, W)
            calib.append({'load_n': W, 'z_target_mm': round(z_t * 1000, 3),
                          'z_measured_mm': (round(z_m * 1000, 3) if z_m is not None else None),
                          'rel_err': (round(abs(z_m - z_t) / max(z_t, 1e-9), 4)
                                      if z_m is not None else None),
                          'stable': stable, 'k_used': round(k0, 4)})
        summary_calib = calib
    else:
        summary_calib = None

    summary = {
        'calibrated_rows': summary_calib,
        'version': 'soil-single-wheel/v1', 'soil_version': SOIL_VERSION,
        'wheel_radius_m': WHEEL_R, 'wheel_width_m': WHEEL_B,
        'gravity': MOON_G, 'params': pm.as_dict(),
        'rows': rows,
        'fit': best,
        'tolerance': {'target_rel_err': 0.30},
        'limitation': ('单轮静置下陷；MuJoCo 凸-凸离散接触 vs Bekker 平板压力分布，'
                       '不是同一模型；不证明月壤物理正确，也不含滑转/牵引/整机'),
    }
    (out / 'single_wheel.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({'rows': [{k: r[k] for k in ('load_n', 'z_target_mm',
                                                  'z_measured_mm', 'rel_err', 'stable')}
                               for r in rows], 'fit': best}, ensure_ascii=False, indent=1))
    ok = [r for r in rows if r['rel_err'] is not None and r['rel_err'] <= 0.30]
    print(f'在 ±30% 内的档位：{len(ok)}/{len(rows)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
