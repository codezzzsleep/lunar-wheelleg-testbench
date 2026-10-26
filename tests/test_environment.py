"""
环境层回归测试：地形米制、轴向、落地、条件化、P/G 可比性。

  .venv/bin/python -m unittest tests.test_environment -v
"""
import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import mujoco  # noqa: E402
import scene_compiler as C  # noqa: E402
import terrain  # noqa: E402
import wheelleg_env  # noqa: E402


def ray(m, d, gid, x, y, z0=6.0):
    out = np.array([-1], dtype=np.int32)
    dist = mujoco.mj_ray(m, d, np.array([x, y, z0]), np.array([0., 0., -1.]),
                         None, 1, -1, out)
    return None if dist < 0 or out[0] != gid else z0 - dist


class TestTerrainMeters(unittest.TestCase):
    """缺陷 2：1 度与 10 度必须编译出不同的物理地面。"""

    def test_slope_scale_is_physical(self):
        peaks = {}
        for deg in (1.0, 10.0):
            spec = terrain.make_spec(kind='slope', seed=0, slope_deg=deg)
            env = wheelleg_env.WheelLegEnv(spec)
            peaks[deg] = env._terrain_meta['zmax']
        self.assertGreater(peaks[10.0], peaks[1.0] * 5,
                           f'10 度峰高应远大于 1 度，实际 {peaks}')
        self.assertAlmostEqual(peaks[1.0], np.tan(np.deg2rad(1.0)) * 8, delta=0.02)

    def test_measured_slope_matches_declared(self):
        for deg in (2.0, 5.0):
            spec = terrain.make_spec(kind='slope', seed=1, slope_deg=deg)
            env = wheelleg_env.WheelLegEnv(spec)
            m, d = env.model, env.data
            gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'terrain')
            z0 = ray(m, d, gid, -2.0, 2.5)
            z1 = ray(m, d, gid, 2.0, 2.5)
            measured = np.degrees(np.arctan((z1 - z0) / 4.0))
            self.assertAlmostEqual(measured, deg, delta=0.35,
                                   msg=f'声明 {deg}°，实测 {measured}°')

    def test_roughness_changes_surface(self):
        outs = []
        for amp in (0.01, 0.06):
            spec = terrain.make_spec(kind='bumpy', seed=3, roughness=amp)
            env = wheelleg_env.WheelLegEnv(spec)
            m, d = env.model, env.data
            gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'terrain')
            zs = [ray(m, d, gid, x, 1.5) or 0.0 for x in np.linspace(-2, 2, 21)]
            outs.append(float(np.ptp(np.diff(zs))))
        self.assertGreater(outs[1], outs[0] * 2,
                           f'粗糙度 0.06 的局部起伏应明显大于 0.01，实际 {outs}')

    def test_ridge_orientation(self):
        """行沿 y、列沿 x：把 x 高端抬高，只应影响 +x 一侧。"""
        h = np.zeros((terrain.N, terrain.N))
        h[:, -8:] = 0.3                      # 最靠 +x 的 8 列
        self.assertGreater(terrain.ground_height_at(h, 3.7, 0.0), 0.25)
        self.assertLess(terrain.ground_height_at(h, -3.7, 0.0), 1e-6)
        self.assertLess(terrain.ground_height_at(h, 0.0, 3.7), 1e-6)
        # 同时验证行方向是翻转的：+y 对应 row 0
        h2 = np.zeros((terrain.N, terrain.N))
        h2[:8, :] = 0.3
        self.assertGreater(terrain.ground_height_at(h2, 0.0, 3.7), 0.25)


class TestPlacement(unittest.TestCase):
    """缺陷 3：生成资产不能埋进地形，也不能整体悬空。"""

    def test_no_burial_on_slope_and_mixed(self):
        for kind, kw in (('slope', {'slope_deg': 5.0}),
                         ('mixed', {'slope_deg': 3.0, 'roughness': 0.04,
                                    'pits': 1, 'pit_depth': 0.04})):
            spec = terrain.make_spec(kind=kind, seed=5, objects=[
                {'asset': 'crate_lid_w300', 'x': 1.8, 'y': 0.12, 'yaw_deg': 12.0,
                 'target_height_m': 0.06}], goal_x=6.0, **kw)
            env = wheelleg_env.WheelLegEnv(spec)
            p = env.placements[0]
            self.assertLessEqual(p['min_clearance_m'], 1e-6,
                                 f'{kind}: 有顶点低于地形（被埋）')
            self.assertGreaterEqual(p['min_clearance_m'], -1e-6)
            self.assertGreater(p['body_z'], 0.05,
                               f'{kind}: 物体应被抬到地形之上，实际 {p["body_z"]}')

    def test_target_height_scaling_matches(self):
        heights = []
        for asset in ('crate_lid_w300', 'boulder_w300', 'proc_box_h043'):
            spec = terrain.make_spec(kind='flat', objects=[
                {'asset': asset, 'x': 1.8, 'y': 0.12, 'yaw_deg': 0.0,
                 'target_height_m': 0.06}], goal_x=6.0)
            env = wheelleg_env.WheelLegEnv(spec)
            import runio
            res = runio.resolve_asset(env.asset_root / asset)['part_paths']
            v = wheelleg_env._world_vertices([str(x) for x in res], 1.8, 0.12, 0.0,
                                             scale=env.placements[0]['mesh_scale'])
            heights.append(float(v[:, 2].max() - v[:, 2].min()))
        for h in heights:
            self.assertAlmostEqual(h, 0.06, delta=0.003,
                                   msg=f'缩放后高度应等于目标 0.06，实际 {heights}')


class TestConditioning(unittest.TestCase):
    """工作包 1：改条件必须改物理场景。"""

    def test_different_conditions_differ(self):
        c1 = {'scenario': '坡地', 'slope': 2.0, 'obstacles': 1}
        c2 = {'scenario': '坡地', 'slope': 8.0, 'obstacles': 1, 'roughness': 0.05}
        s1 = C.compile_scenes(c1, 500, 1)[0]
        s2 = C.compile_scenes(c2, 500, 1)[0]
        self.assertNotEqual(terrain.scene_identity(s1), terrain.scene_identity(s2))
        e1 = wheelleg_env.WheelLegEnv(s1)
        e2 = wheelleg_env.WheelLegEnv(s2)
        self.assertGreater(e2._terrain_meta['zmax'], e1._terrain_meta['zmax'] * 2)

    def test_same_condition_same_scene(self):
        c = {'scenario': '巡检区', 'obstacles': 2, 'height': '低'}
        a = C.compile_scenes(c, 700, 3)
        b = C.compile_scenes(c, 700, 3)
        self.assertEqual([terrain.scene_identity(x) for x in a],
                         [terrain.scene_identity(x) for x in b])
        ids = {terrain.scene_identity(x) for x in a}
        self.assertEqual(len(ids), 3, '不同 seed 应得到不同场景')

    def test_parse_reports_unknown_lines(self):
        cond, unknown = C.parse_task('scenario: 坡地\nnonsense line here\n')
        self.assertEqual(cond['scenario'], '坡地')
        self.assertTrue(unknown, '未识别行必须被报告，不能静默忽略')


class TestPGComparability(unittest.TestCase):
    """工作包 4：P/G 只能差在几何来源。"""

    def test_terrain_identical_between_groups(self):
        for split in ('train', 'validation', 'test'):
            p = json.loads((ROOT / f'scenes/P_{split}.json').read_text())
            g = json.loads((ROOT / f'scenes/G_{split}.json').read_text())
            self.assertEqual([s['terrain'] for s in p], [s['terrain'] for s in g],
                             f'{split} 的 P/G 地形不一致')
            self.assertEqual([o['target_height_m'] for s in p for o in s['objects']],
                             [o['target_height_m'] for s in g for o in s['objects']],
                             f'{split} 的 P/G 目标高度不一致')

    def test_family_splits_disjoint(self):
        for grp in ('P', 'G'):
            fams = {}
            for split in ('train', 'validation', 'test'):
                specs = json.loads((ROOT / f'scenes/{grp}_{split}.json').read_text())
                fams[split] = {o['asset'] for s in specs for o in s['objects']}
            self.assertFalse(fams['train'] & fams['validation'])
            self.assertFalse(fams['train'] & fams['test'])
            self.assertFalse(fams['validation'] & fams['test'])


class TestContactEvidence(unittest.TestCase):
    """接触必须来自真实仿真，不能硬编码。"""

    def test_contact_is_recorded_from_simulation(self):
        spec = terrain.make_spec(kind='flat', seed=2, objects=[
            {'asset': 'proc_box_h050', 'x': 1.8, 'y': 0.12, 'yaw_deg': 0.0,
             'target_height_m': 0.06}], goal_x=6.0)
        env = wheelleg_env.WheelLegEnv(spec)
        obs, _ = env.reset(seed=0)
        info = {}
        for _ in range(600):
            obs, r, te, tr, info = env.step([0.0] * wheelleg_env.ACT_DIM)
            if te or tr:
                break
        self.assertTrue(info['contact_any'])
        self.assertIsNotNone(info['first_contact_s'])
        self.assertGreater(info['contact_substeps'], 0)

    def test_compiled_scenes_always_contact(self):
        """
        编译器生成的所有场景都必须发生真实接触。

        背景：不缩放时 0.30 m 宽的箱子与轮线（y=±0.142）几乎相切，y=0 会让机器人
        直接跨过去；缩放放大宽度后又会变宽。因此布局统一给一个横向偏移，
        这里守住"不许出现无接触场景"这条线。
        """
        specs = (json.loads((ROOT / 'scenes/A_sparse.json').read_text())[:2]
                 + json.loads((ROOT / 'scenes/C_debris.json').read_text())[:2])
        for spec in specs:
            env = wheelleg_env.WheelLegEnv(spec)
            obs, _ = env.reset(seed=0)
            info = {}
            for _ in range(700):
                obs, r, te, tr, info = env.step([0.0] * wheelleg_env.ACT_DIM)
                if te or tr:
                    break
            self.assertTrue(info['contact_any'],
                            f'{spec["name"]}: 未发生接触，几何没进入任务路径')


if __name__ == '__main__':
    unittest.main()
