"""
动作接线回归：D1/D2 必须真正产生横向位移（>= 0.3 m），R1 不得偏移。

  .venv/bin/python -m unittest tests.test_detour -v
"""
import pathlib, sys, unittest
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import runner, skills, terrain, wheelleg_env     # noqa: E402


def _spec():
    s = terrain.make_spec(kind='flat', objects=[], goal_x=2.8)
    s['channel'] = {'center_y': 0.0, 'half_width': 1.2}
    s['skill_cfg'] = {'task': 'M'}
    s['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    return s


def _run(name, capture=False):
    env = wheelleg_env.WheelLegEnv(_spec())
    r = runner.EpisodeRunner(env, skills.make_skill(name),
                             visible={'x_front': 1.65}, seed=0)
    ys = []
    orig_step = env.step
    def step(a):
        out = orig_step(a)
        ys.append(float(env.data.qpos[1]))
        return out
    env.step = step
    out = r.run_with_seed(0)
    return out, np.array(ys) if ys else np.zeros(0)


class TestDetour(unittest.TestCase):
    def test_d1_shifts_left_over_30cm(self):
        out, ys = _run('D1')
        self.assertGreater(len(ys), 10)
        self.assertGreaterEqual(float(np.abs(ys).max()), 0.30,
                                f'D1 最大横向偏移 {np.abs(ys).max():.3f} < 0.30')

    def test_d2_shifts_right_over_30cm(self):
        out, ys = _run('D2')
        self.assertGreaterEqual(float(np.abs(ys).max()), 0.30)

    def test_d1_d2_opposite_directions(self):
        _, y1 = _run('D1'); _, y2 = _run('D2')
        self.assertGreater(float(y1[np.argmax(np.abs(y1))]), 0.2)
        self.assertLess(float(y2[np.argmax(np.abs(y2))]), -0.2)

    def test_r1_keeps_near_center(self):
        out, ys = _run('R1')
        self.assertLess(float(np.abs(ys).max()), 0.10,
                        f'R1 不应横移：{np.abs(ys).max():.3f}')

    def test_nav_target_reset_between_runs(self):
        env = wheelleg_env.WheelLegEnv(_spec())
        r = runner.EpisodeRunner(env, skills.make_skill('D1'), seed=0)
        r.run_with_seed(0)
        env2 = wheelleg_env.WheelLegEnv(_spec())
        r2 = runner.EpisodeRunner(env2, skills.make_skill('R1'), seed=0)
        self.assertEqual(env2.nav_target_y, env2.channel_center,
                         'reset 后导航目标必须回到通道中心')

    def test_detour_returns_toward_center(self):
        """回位阶段必须真的把 |y| 拉回来（受目标点约束，未必完全回到 0）。"""
        out, ys = _run('D1')
        peak = float(np.abs(ys).max())
        final = float(abs(ys[-1]))
        self.assertLess(final, peak * 0.92,
                        f'回位不足：峰值 {peak:.3f} -> 终值 {final:.3f}')
        self.assertIn('return', [p['phase'] for p in out['phases']],
                      '必须进入 return 阶段')


if __name__ == '__main__':
    unittest.main()
