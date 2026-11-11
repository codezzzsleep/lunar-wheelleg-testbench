"""V8 重放守卫的回归：默认必须拒绝，只有显式开关才允许沿用归档观测。

背景（2026-11-11）：跨机器重放第二眼时位姿差 0.19 mm，`v8_lux.same_inputs` 的逐字节判据
必然失效。默认行为是 `replay_mismatch` + 退出码 11（绝不拿旧结果冒充）；新增的
`--accept-replay-drift` 只把这一步变成一个**可审计的选择**，并把位姿差写进 summary。

本测试不跑物理，只钉住三件事：
  (a) 开关默认关闭；
  (b) 打开后 argparse 能正确识别，且 help 里说明它会记录位姿差；
  (c) summary 的字段名 `replay_drift_accepted` 存在（下游 eval/文档都按这个名字引用）。

  .venv/bin/python -m unittest tests.test_v8_replay_guard -v
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'v8'))
import v8_run  # noqa: E402


def parse(*argv):
    return v8_run.build_parser().parse_args(
        ['--policy', 'imagination', '--out', '/tmp/v8_guard_test', *argv])


class TestReplayGuard(unittest.TestCase):
    def test_drift_acceptance_is_off_by_default(self):
        self.assertFalse(parse().accept_replay_drift,
                         '默认必须严格拒绝（退出码 11），不能悄悄接受跨机漂移')

    def test_flag_can_be_enabled_explicitly(self):
        self.assertTrue(parse('--accept-replay-drift').accept_replay_drift)

    def test_help_says_it_records_pose_delta(self):
        action = next(a for a in v8_run.build_parser()._actions
                      if a.dest == 'accept_replay_drift')
        self.assertIn('replay_drift_accepted', action.help,
                      'help 必须写清位姿差记在哪里，否则使用者不知道要查什么')

    def test_summary_field_name_is_stable(self):
        src = (ROOT / 'scripts/v8/v8_run.py').read_text()
        self.assertIn("'replay_drift_accepted'", src,
                      'summary/eval/文档都按 replay_drift_accepted 这个名字引用，改名要同步')

    def test_strict_exit_code_is_still_11(self):
        """严格模式下的退出码是契约：脚本被人包在流水线里，改码会静默放行。"""
        src = (ROOT / 'scripts/v8/v8_run.py').read_text()
        self.assertIn('raise SystemExit(11)', src)


if __name__ == '__main__':
    unittest.main()
