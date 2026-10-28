"""
月壤半经验模型（Bekker–Wong），纯公式 + 明确单位。不做颗粒系统。

  from soil import SoilModel, SoilParams
  pm = SoilParams.moon_nominal()
  z = pm.sinkage(wheel_load_n=120.0, wheel_width_m=0.10, wheel_radius_m=0.09)
  Rc = pm.compaction_resistance(z, b=0.10)

单位约定（易错点，写死在这里）：
  · p 是**压力** Pa = N/m²；W 是**力** N，不是压力。
  · kc 单位 N/m^(n+1)；kphi 单位 N/m^(n+2)；b 单位 m。
    因为 p = (kc/b + kphi) * z^n，量纲上 (N/m^(n+1))/m = N/m^(n+2)，与 kphi 一致。
  · n 无量纲（>=1 时 z^n 才有 Pa 量纲）。
  · 压实阻力 Rc = (kc + b*kphi) * z^(n+1) / (n+1)，单位 N。

与 MuJoCo 的关系：
  solref/solimp **不是** Bekker 参数。本模块只给目标下陷 z 与阻力 Rc，
  由单轮标定实验确定软度映射（见 soil_calibrate.py），不直接把 kc/kphi 填进 solref。
"""
from dataclasses import dataclass, asdict
import numpy as np

VERSION = 'soil/v1'


@dataclass
class SoilParams:
    kc: float          # N/m^(n+1)
    kphi: float        # N/m^(n+2)
    n: float           # 无量纲
    cohesion_pa: float  # c, Pa
    phi_deg: float      # 内摩擦角
    k_shear: float      # Janosi–Hanamoto 剪切模量 K, m
    source: str = '纲领名义参数（实验不确定性设定，不是月面统计分布）'

    def __post_init__(self):
        if self.n <= 0:
            raise ValueError('n 必须 > 0')
        if self.kc < 0 or self.kphi < 0:
            raise ValueError('kc/kphi 必须非负')

    # ---------- 压力 / 下陷 ----------
    def pressure(self, z, b):
        """p = (kc/b + kphi) z^n，单位 Pa。"""
        if b <= 0:
            raise ValueError('轮宽 b 必须 > 0')
        return (self.kc / b + self.kphi) * np.power(np.maximum(z, 0.0), self.n)

    def sinkage(self, wheel_load_n, wheel_width_m, wheel_radius_m=None,
                contact_len_m=None):
        """
        由轮载求下陷 z。
        W 是力 (N)。用轮–土接触面积 A = b * L 把力换成压力：
            p = W / (b * L)
            z = (p / (kc/b + kphi))^(1/n)
        L 给出时直接用；否则用刚性轮近似 L = sqrt(2 R z)，迭代求解（3 次足够）。
        """
        if wheel_load_n < 0:
            raise ValueError('轮载不能为负')
        if wheel_load_n == 0:
            return 0.0
        b = float(wheel_width_m)
        denom = self.kc / b + self.kphi
        if contact_len_m is not None:
            L = float(contact_len_m)
            p = wheel_load_n / (b * L)
            return float((p / denom) ** (1.0 / self.n))
        if wheel_radius_m is None:
            raise ValueError('需要 contact_len_m 或 wheel_radius_m')
        R = float(wheel_radius_m)
        z = 0.01
        for _ in range(60):
            L = np.sqrt(max(2 * R * z, 1e-9))
            p = wheel_load_n / (b * L)
            z_new = (p / denom) ** (1.0 / self.n)
            if abs(z_new - z) < 1e-10:
                z = z_new
                break
            z = 0.5 * (z + z_new)
        return float(z)

    # ---------- 阻力 ----------
    def compaction_resistance(self, z, b):
        """Rc = (kc + b*kphi) z^(n+1)/(n+1)，单位 N。"""
        return float((self.kc + b * self.kphi) *
                     np.power(max(z, 0.0), self.n + 1) / (self.n + 1.0))

    def traction_limit(self, wheel_load_n, contact_area_m2):
        """A*c + W*tan(phi)，单位 N（等效摩擦的实现由调用方保证不与 MuJoCo 双算）。"""
        if contact_area_m2 <= 0:
            raise ValueError('接触面积必须 > 0')
        return float(contact_area_m2 * self.cohesion_pa
                     + wheel_load_n * np.tan(np.deg2rad(self.phi_deg)))

    def shear_stress(self, j, sigma):
        """Janosi–Hanamoto: tau = (c + sigma tan phi) * (1 - exp(-j/K))；j 单位 m。"""
        tau_max = self.cohesion_pa + sigma * np.tan(np.deg2rad(self.phi_deg))
        return float(tau_max * (1.0 - np.exp(-np.maximum(j, 0.0) / max(self.k_shear, 1e-9))))

    def as_dict(self):
        d = asdict(self)
        d['version'] = VERSION
        d['units'] = {'kc': 'N/m^(n+1)', 'kphi': 'N/m^(n+2)', 'n': '-',
                      'cohesion_pa': 'Pa', 'phi_deg': 'deg', 'k_shear': 'm'}
        return d

    @classmethod
    def moon_nominal(cls):
        """纲领名义参数（典型值量级），仅作实验设定的中心，不是实测月壤。"""
        return cls(kc=1400.0, kphi=820000.0, n=1.0,
                   cohesion_pa=170.0, phi_deg=35.0, k_shear=0.018)

    @classmethod
    def sample(cls, rng, ranges=None):
        """在公开范围内抽样（预演用有限样本，不读执行真值参数）。"""
        r = ranges or default_ranges()
        return cls(kc=float(rng.uniform(*r['kc'])),
                   kphi=float(rng.uniform(*r['kphi'])),
                   n=float(rng.uniform(*r['n'])),
                   cohesion_pa=float(rng.uniform(*r['cohesion_pa'])),
                   phi_deg=float(rng.uniform(*r['phi_deg'])),
                   k_shear=float(rng.uniform(*r['k_shear'])),
                   source='sampled from default_ranges')


def default_ranges():
    return {'kc': (700.0, 2500.0), 'kphi': (4.0e5, 1.6e6), 'n': (0.8, 1.3),
            'cohesion_pa': (80.0, 300.0), 'phi_deg': (28.0, 42.0),
            'k_shear': (0.010, 0.030)}
