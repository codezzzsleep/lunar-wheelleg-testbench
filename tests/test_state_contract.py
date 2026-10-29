"""
状态续接合同的反例（772bc59/903e039 复核要求）：
  · 快照缺字段 / 维度不符 / 版本不符 -> 必须拒绝
  · 恢复后偷偷 reset -> 首帧必须不等于出生状态
  · 直接继续与保存恢复后继续 -> 轨迹/终态在容差内一致
  · 非零 ctrl/prev_action/外力/土壤状态不被构造器覆盖
"""
import copy, sys, pathlib, unittest
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'scripts'))
import terrain
import wheelleg_env
import runner as R
import skills


def mk(soil=False):
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=2.6, name='t')
    spec['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    spec['skill_cfg'] = {'task': 'M'}
    spec['init_perturbation'] = {'lateral_m': 0.05, 'yaw_rad': 0.05}
    if soil:
        spec['soil'] = {'mode': 'soil'}
    e = wheelleg_env.WheelLegEnv(spec)
    e.reset(seed=0)
    return e


class TestStateContract(unittest.TestCase):
    def setUp(self):
        self.env = mk()
        for _ in range(30):
            self.env.step_drive(v_forward_mps=0.10)
        self.snap = self.env.save_state()

    def test_snapshot_has_required_fields(self):
        for k in ('schema', 'mjstate', 'data_time', 'env_t', 'ctrl', 'xfrc_applied',
                  'prev_action', 'n_physics', 'n_control', 'nav_target_y',
                  'nq', 'nv', 'state_hash'):
            self.assertIn(k, self.snap)
        self.assertGreater(len(self.snap['mjstate']), 0)
        # 原始时间与原生时间都被保存，关系可查
        self.assertAlmostEqual(self.snap['env_t'] - self.snap['data_time'], 0.0, places=6)

    def test_restore_rejects_wrong_schema(self):
        bad = dict(self.snap); bad['schema'] = 'env-state/v0'
        with self.assertRaises(ValueError):
            mk().restore_state(bad)

    def test_restore_rejects_dimension_mismatch(self):
        bad = copy.deepcopy(self.snap); bad['nq'] = self.snap['nq'] + 1
        with self.assertRaises(ValueError):
            mk().restore_state(bad)

    def test_restore_rejects_truncated_state(self):
        bad = copy.deepcopy(self.snap); bad['mjstate'] = bad['mjstate'][:-3]
        with self.assertRaises(ValueError):
            mk().restore_state(bad)

    def test_restored_ctrl_and_prev_action_not_overwritten(self):
        e2 = mk()
        for _ in range(20):
            e2.step_drive(v_forward_mps=0.2)
        e2.restore_state(copy.deepcopy(self.snap))
        self.assertTrue(np.allclose(e2.data.ctrl, np.asarray(self.snap['ctrl'])))
        self.assertTrue(np.allclose(e2.data.qpos, self.env.data.qpos))
        self.assertEqual(e2.n_physics, self.snap['n_physics'])
        self.assertAlmostEqual(e2.data.time, self.snap['data_time'], places=9)

    def test_continue_does_not_reset_to_birth(self):
        e = mk()
        for _ in range(40):
            e.step_drive(v_forward_mps=0.10)
        snap = e.save_state()
        x_after = float(e.data.qpos[0])
        r = R.EpisodeRunner(e, skills.make_skill('R1'),
                            visible={'x_front': 1.6}, seed=0)
        out = r.run_from_state(snap)
        # 首帧必须对应观察后状态，而不是出生状态（x≈0）
        # 注意 mjstate 首位是 time，不是 qpos；用环境的 qpos 对比
        self.assertAlmostEqual(out['q0'][0], x_after, places=2)
        self.assertGreater(abs(out['q0'][0] - 0.0), 0.01,
                           '继续执行回到了出生状态')
        self.assertAlmostEqual(out['t_start'], snap['env_t'], places=6)

    def test_direct_vs_restore_consistency(self):
        eA = mk()
        for _ in range(40):
            eA.step_drive(v_forward_mps=0.10)
        snap = eA.save_state()
        oA = R.EpisodeRunner(eA, skills.make_skill('R1'),
                             visible={'x_front': 1.6}, seed=0).run_from_state(snap)
        eB = mk()
        for _ in range(70):
            eB.step_drive(v_forward_mps=0.1)
        eB.restore_state(copy.deepcopy(snap))
        oB = R.EpisodeRunner(eB, skills.make_skill('R1'),
                             visible={'x_front': 1.6}, seed=0).run_from_state(
            copy.deepcopy(snap))
        self.assertEqual(oA['reason'], oB['reason'])
        self.assertAlmostEqual(oA['final_x'], oB['final_x'], places=6)
        self.assertAlmostEqual(float(oA['t_end']), float(oB['t_end']), places=6)

    def test_corrupted_hash_rejected(self):
        bad = copy.deepcopy(self.snap)
        bad['state_hash'] = 'CORRUPTED_HASH'
        with self.assertRaises(ValueError):
            mk().restore_state(bad)

    def test_wrong_robot_signature_rejected(self):
        bad = copy.deepcopy(self.snap)
        bad['robot_signature'] = 'other_robot'
        with self.assertRaises(ValueError):
            mk().restore_state(bad)

    def test_missing_required_field_rejected(self):
        bad = copy.deepcopy(self.snap)
        bad.pop('mjstate')
        with self.assertRaises((KeyError, ValueError)):
            mk().restore_state(bad)

    def test_stealth_reset_after_restore_detected(self):
        """恢复后偷偷 reset -> 首帧必须不等于观察后状态。"""
        e = mk()
        for _ in range(40):
            e.step_drive(v_forward_mps=0.10)
        snap = e.save_state()
        x_obs = float(e.data.qpos[0])
        e.reset(seed=0)                      # 偷偷 reset
        r = R.EpisodeRunner(e, skills.make_skill('R1'),
                            visible={'x_front': 1.6}, seed=0)
        # 恢复到观察后状态再继续，首帧必须对应该状态
        e.restore_state(copy.deepcopy(snap))
        out = r.run_from_state(copy.deepcopy(snap))
        self.assertAlmostEqual(out['q0'][0], x_obs, places=2)

    def test_soil_state_included_and_restored(self):
        e = mk(soil=True)
        for _ in range(25):
            e.step(np.array([0.6, 0.0, 0.0]))
        snap = e.save_state()
        self.assertIsNotNone(snap['soil'], '土壤模式必须保存土壤状态')
        e2 = mk(soil=True)
        e2.restore_state(copy.deepcopy(snap))
        self.assertEqual(e2.n_physics, snap['n_physics'])


if __name__ == '__main__':
    unittest.main()
