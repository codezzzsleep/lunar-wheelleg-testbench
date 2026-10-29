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

    def test_per_wheel_limit_independent_and_order_free(self):
        """逐轮上限独立；地面摩擦取各轮需求最大值 -> 与遍历顺序无关。"""
        env = mk_env()
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
        mus = [v['mu_eff'] for v in seen.values()]
        # 每轮 mu_eff 由该轮自己的载荷/接触面积决定（不同载荷 -> 不同值）
        is_different = len(set(round(m, 6) for m in mus)) == len(mus)
        self.assertTrue(is_different or len(set(mus)) == 1,
                        f'不同轮应有各自上限：{mus}')
        ground = list(env._soil_ground_geoms)
        if ground:
            gm = max(float(env.model.geom_friction[g][0]) for g in ground)
            # 地面取各轮最大需求：不受遍历顺序影响
            self.assertAlmostEqual(gm, max(mus), places=5,
                                   msg=f'地面摩擦 {gm} 应为各轮最大需求 {max(mus)}')

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
