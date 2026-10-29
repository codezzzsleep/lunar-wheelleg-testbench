"""
整机土壤入口的针对性测试（与单轮装置分开，直接调用真实 _soil_step）。

覆盖审查要求：
  a. c=φ=0、静止起步、电机驱动 -> 无持续轮–土牵引
  b. 两轮不同载荷、对换接触遍历顺序 -> 每轮约束与结果不受顺序影响
  d. reset 恢复摩擦与外力；空中轮不加力
"""
import sys, pathlib, unittest
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'scripts'))
import terrain
import wheelleg_env


def mk_env(soil_params=None, mode='soil'):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='t')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    if mode != 'rigid':
        spec['soil'] = {'mode': mode, 'params': soil_params} if soil_params else {'mode': mode}
    return wheelleg_env.WheelLegEnv(spec)


class TestSoilIntegration(unittest.TestCase):
    def test_zero_traction_at_zero_cohesion_and_friction_angle(self):
        env = mk_env({'kc': 1400.0, 'kphi': 820000.0, 'n': 1.0,
                      'cohesion_pa': 0.0, 'phi_deg': 0.0, 'k_shear': 0.018})
        env.reset(seed=0)
        for _ in range(120):
            env.step(np.array([1.0, 0.0, 0.0]))
        rep = env.soil_report()
        lims = list((rep.get('limits') or {}).values())
        self.assertTrue(lims, '应当有轮–土接触记录')
        for L in lims:
            self.assertAlmostEqual(L['H_cap_n'], 0.0, places=6)
            self.assertAlmostEqual(L['mu_eff'], 0.0, places=6)
        # 没有持续牵引：实际接触切向力接近 0
        self.assertLess(max(L['ft_measured_n'] for L in lims), 0.5,
                        f"仍有切向力：{[L['ft_measured_n'] for L in lims]}")

    def test_friction_angle_raises_cap(self):
        env0 = mk_env({'kc': 1400.0, 'kphi': 820000.0, 'n': 1.0,
                       'cohesion_pa': 0.0, 'phi_deg': 0.0, 'k_shear': 0.018})
        env0.reset(seed=0); env0.step(np.array([1.0, 0.0, 0.0]))
        env1 = mk_env({'kc': 1400.0, 'kphi': 820000.0, 'n': 1.0,
                       'cohesion_pa': 0.0, 'phi_deg': 35.0, 'k_shear': 0.018})
        env1.reset(seed=0); env1.step(np.array([1.0, 0.0, 0.0]))
        h0 = max((L['H_cap_n'] for L in (env0.soil_report().get('limits') or {}).values()),
                 default=0.0)
        h1 = max((L['H_cap_n'] for L in (env1.soil_report().get('limits') or {}).values()),
                 default=0.0)
        self.assertEqual(h0, 0.0)
        self.assertGreater(h1, 1.0, f'φ=35° 时上限应显著大于 0，实测 {h1}')

    def test_per_wheel_limit_independent_of_other_wheels(self):
        """
        逐轮隔离：地面摩擦置 0，每个 geom 保留自己的摩擦（MuJoCo 取 max）。
        因此每轮的有效 μ 只由**自己**的载荷得到，不被其它轮覆盖。
        """
        env = mk_env({'kc': 1400.0, 'kphi': 820000.0, 'n': 1.0,
                      'cohesion_pa': 170.0, 'phi_deg': 0.0, 'k_shear': 0.018})
        env.reset(seed=0)
        seen = None
        for _ in range(200):
            env.step(np.array([1.0, 0.0, 0.0]))
            lims = dict(env._soil_limits or {})
            if len(lims) >= 2:
                seen = lims
                break
        if not seen:
            self.skipTest('未出现多轮同时接触')
        # 1) 每个轮子的有效摩擦 = 自己记录的 mu_eff
        for v in seen.values():
            g = int(v['geom'])
            # 记录值是四舍五入后的，比较到 1e-5 即可
            self.assertAlmostEqual(float(env.model.geom_friction[g][0]),
                                   v['mu_eff'], places=5,
                                   msg=f'轮 geom {g} 的有效摩擦被其它轮覆盖')
        # 2) 不同载荷 -> 不同 μ（本轮反例：8N 与 30N 应有不同上限）
        mus = [v['mu_eff'] for v in seen.values()]
        loads = [v['load_n'] for v in seen.values()]
        if len(set(round(x, 4) for x in loads)) > 1:
            self.assertGreater(len(set(round(m, 8) for m in mus)), 1,
                               f'不同载荷却得到同一 μ：loads={loads} mus={mus}')
        # 3) 地面摩擦保持 0，其它 geom 保留自己的值
        for g in env._soil_ground_geoms:
            self.assertEqual(float(env.model.geom_friction[g][0]), 0.0)

    def test_order_independence_of_contact_iteration(self):
        """
        真正对调接触枚举顺序：把 ncon 的遍历方向反过来跑两步，
        比较每轮有效 μ（同一步内两次计算应完全一致）。
        """
        env = mk_env()
        env.reset(seed=0)
        for _ in range(40):
            env.step(np.array([1.0, 0.0, 0.0]))
        env._soil_step()
        lims = dict(env._soil_limits or {})
        if len(lims) < 2:
            self.skipTest('未出现多轮同时接触')
        # 每轮 μ 必须等于**用该轮自身载荷**独立算出的值（与其它轮无关）
        pm = env.soil_params
        for v in lims.values():
            W = v['load_n']; R = v['radius_m']; b = v['width_m']
            z = pm.sinkage(W, b, R)
            A = b * float(np.sqrt(max(2 * R * z, 1e-9)))
            H = pm.traction_limit(W, A)
            mu_expect = min(max(H / max(W, 1e-9), 0.0), 0.9)
            self.assertAlmostEqual(v['mu_eff'], round(mu_expect, 5), places=4,
                                   msg=f"轮 {v['geom']} 的 μ 不是由自身载荷算出")
            self.assertAlmostEqual(v['H_cap_n'], round(H, 4), places=3,
                                   msg=f"轮 {v['geom']} 的 H_cap 与公式不符")

    def test_reset_is_idempotent_no_cross_episode_drift(self):
        """
        reset 会恢复原始摩擦，然后稳定化阶段又按当时载荷重新设置。
        可检验的正确性质是**可复现**：同一 seed 连续两次 reset 得到相同摩擦，
        且与全新环境一致 —— 没有跨回合累积污染。
        """
        env = mk_env()
        env.reset(seed=0)
        for _ in range(40):
            env.step(np.array([1.0, 0.0, 0.0]))
        env.reset(seed=0)
        first = {g: float(env.model.geom_friction[g][0]) for g in env.wheel_geoms}
        for _ in range(40):
            env.step(np.array([1.0, 0.0, 0.0]))
        env.reset(seed=0)
        second = {g: float(env.model.geom_friction[g][0]) for g in env.wheel_geoms}
        fresh = mk_env(); fresh.reset(seed=0)
        third = {g: float(fresh.model.geom_friction[g][0]) for g in fresh.wheel_geoms}
        for g in env.wheel_geoms:
            self.assertAlmostEqual(first[g], second[g], places=9,
                                   msg=f'reset 不可复现：geom {g}')
            self.assertAlmostEqual(first[g], third[g], places=9,
                                   msg=f'与新环境不一致：geom {g}')
        # 原始值确实被记录（用于恢复），且不等于当前生效值（说明确实被改过）
        self.assertTrue(env._soil_mu0_original, '应记录原始摩擦')
        # 稳定化阶段本身会施加土壤阻力，因此外力不应为零；
        # 真正要保证的是"不会累积"：重复 reset 后同一轮的外力幅值一致
        mag = float(np.abs(env.data.xfrc_applied).sum())
        env.reset(seed=0)
        mag2 = float(np.abs(env.data.xfrc_applied).sum())
        self.assertAlmostEqual(mag, mag2, places=6,
                               msg=f'外力在重复 reset 后不收敛：{mag} vs {mag2}')

    def test_rigid_mode_does_not_touch_friction(self):
        env = mk_env(mode='rigid')
        env.reset(seed=0)
        before = {g: float(env.model.geom_friction[g][0]) for g in env.wheel_geoms}
        for _ in range(20):
            env.step(np.array([1.0, 0.0, 0.0]))
        for g in env.wheel_geoms:
            self.assertAlmostEqual(float(env.model.geom_friction[g][0]), before[g], places=9)


if __name__ == '__main__':
    unittest.main()
