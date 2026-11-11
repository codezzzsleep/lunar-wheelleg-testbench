"""预算可审计回归：声明的 time_limit 与 env.max_seconds 必须一起落盘。

背景（2026-11-11 审查）：`common_planner.plan_action` 一直把 `budget` 传给
`eval_six.run_episode_from_env`，但该函数体从不使用它，结果里也不留痕——
"同预算比较"因此不可审计。修复后每行带 `budget` 块：
`declared_s`（调用方声明）/ `env_max_seconds`（真正生效）/ `enforced`（两者是否一致）。

本测试不跑物理，只验证这段记录逻辑本身不撒谎。

  .venv/bin/python -m unittest tests.test_budget_audit -v
"""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import eval_six     # noqa: E402


class _FakeEnv:
    def __init__(self, max_seconds):
        self.max_seconds = float(max_seconds)
        self.t = 1.5
        self.n_physics = 75
        self.resets = 0

    def reset(self, seed=None):
        self.resets += 1


class _FakeRunner:
    """替身：只返回 run_episode_from_env 需要读取的字段。"""

    def __init__(self, env, skill, visible, seed):
        self.env = env

    def run(self):
        return {'reason': 'arrived', 'success': True, 'abort': False, 't_end': 1.5,
                'final_x': 2.8, 'max_tilt': 0.02, 'contact': 'wheel', 'triggered': False,
                'phases': [], 'action_fingerprint': 'fake', 'steps': 75, 'q0': [0.0] * 7,
                't_start': 0.0, 'initial_full_hash': 'deadbeef'}

    def run_from_state(self, snapshot, mode='project'):
        return self.run()


def _run(max_seconds, declared):
    with mock.patch.object(eval_six.runner, 'EpisodeRunner', _FakeRunner), \
         mock.patch.object(eval_six.skills, 'make_skill', lambda option: None):
        return eval_six.run_episode_from_env(
            _FakeEnv(max_seconds), 'R1', 0, {}, 2.8, time_limit=declared)[0]


class TestBudgetAudit(unittest.TestCase):
    def test_budget_block_present_and_honest(self):
        row = _run(max_seconds=12.0, declared=15.0)
        self.assertIn('budget', row, '每行必须带 budget 块，否则预算不可审计')
        b = row['budget']
        self.assertEqual(b['declared_s'], 15.0)
        self.assertEqual(b['env_max_seconds'], 12.0)
        self.assertFalse(b['enforced'], '声明 15 s、实际 12 s 时不能声称预算已生效')

    def test_enforced_when_equal(self):
        row = _run(max_seconds=15.0, declared=15.0)
        self.assertTrue(row['budget']['enforced'])

    def test_missing_max_seconds_is_not_claimed_enforced(self):
        env = _FakeEnv(15.0)
        del env.max_seconds
        with mock.patch.object(eval_six.runner, 'EpisodeRunner', _FakeRunner), \
             mock.patch.object(eval_six.skills, 'make_skill', lambda option: None):
            row = eval_six.run_episode_from_env(env, 'R1', 0, {}, 2.8, time_limit=15.0)[0]
        self.assertIsNone(row['budget']['env_max_seconds'])
        self.assertFalse(row['budget']['enforced'])


if __name__ == '__main__':
    unittest.main()
