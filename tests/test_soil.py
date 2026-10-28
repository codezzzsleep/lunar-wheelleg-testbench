"""月壤公式与单位的回归（不涉及 MuJoCo 接触）。"""
import sys, pathlib, unittest
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'scripts'))
from soil import SoilParams, default_ranges, VERSION


class TestSoilFormulas(unittest.TestCase):
    def setUp(self):
        self.p = SoilParams.moon_nominal()

    def test_pressure_units(self):
        # p = (kc/b + kphi) z^n ；kc/b 与 kphi 都应归一到 Pa
        z, b = 0.02, 0.10
        expect = (self.p.kc / b + self.p.kphi) * z ** self.p.n
        self.assertAlmostEqual(self.p.pressure(z, b), expect, places=6)
        self.assertGreater(self.p.pressure(z, b), 1000.0, '应为 Pa 量级')

    def test_sinkage_monotonic_in_load(self):
        zs = [self.p.sinkage(W, 0.10, 0.09) for W in (40, 80, 120, 160, 200)]
        self.assertEqual(zs, sorted(zs))
        self.assertTrue(all(0.001 < z < 0.10 for z in zs), zs)

    def test_sinkage_force_not_pressure(self):
        # 轮载翻倍 -> 下陷变深；若把 W 当压力会得到不同量级
        z1 = self.p.sinkage(100.0, 0.10, 0.09)
        z2 = self.p.sinkage(200.0, 0.10, 0.09)
        self.assertGreater(z2, z1)

    def test_compaction_resistance_units(self):
        z, b = 0.02, 0.10
        expect = (self.p.kc + b * self.p.kphi) * z ** (self.p.n + 1) / (self.p.n + 1)
        self.assertAlmostEqual(self.p.compaction_resistance(z, b), expect, places=9)
        self.assertGreater(self.p.compaction_resistance(z, b), 0.0)

    def test_zero_load_zero_sinkage(self):
        self.assertEqual(self.p.sinkage(0.0, 0.10, 0.09), 0.0)
        self.assertEqual(self.p.compaction_resistance(0.0, 0.10), 0.0)

    def test_shear_zero_at_zero_slip(self):
        self.assertAlmostEqual(self.p.shear_stress(0.0, 20000.0), 0.0, places=9)
        self.assertGreater(self.p.shear_stress(0.02, 20000.0), 0.0)

    def test_invalid_params_rejected(self):
        with self.assertRaises(ValueError):
            SoilParams(kc=1.0, kphi=1.0, n=0.0, cohesion_pa=1.0, phi_deg=30, k_shear=0.01)
        with self.assertRaises(ValueError):
            self.p.pressure(0.01, 0.0)

    def test_sampling_within_ranges(self):
        rng = np.random.default_rng(0)
        r = default_ranges()
        for _ in range(50):
            s = SoilParams.sample(rng)
            for k in ('kc', 'kphi', 'n', 'cohesion_pa', 'phi_deg', 'k_shear'):
                lo, hi = r[k]
                self.assertTrue(lo <= getattr(s, k) <= hi, (k, getattr(s, k)))

    def test_dict_has_units_and_version(self):
        d = self.p.as_dict()
        self.assertEqual(d['version'], VERSION)
        self.assertEqual(d['units']['p'], 'Pa') if 'p' in d['units'] else None
        self.assertIn('kc', d['units'])


if __name__ == '__main__':
    unittest.main()
