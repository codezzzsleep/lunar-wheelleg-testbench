"""V8 眼数规范一致性（静态/单元级：不建 MuJoCo 场景、不调 Lux3D、不需要 GL）。

规范来源：`docs/v8/SPEC_V8.md` §0.4:64「两眼之后还不行，就停车。」
覆盖：
  (a) SPEC 里的停车眼数就是 2，且脚本默认眼数直接取它——文档改动会让测试报警；
  (b) `MAX_EXTRA_LOOKS` 与 `MAX_LOOKS_BY_SPEC` 一致（旧值 2 会默认跑出第三眼）；
  (c) argparse 默认值 == SPEC 值；显式 `--max-looks 3` 必须带出 `looks_exceed_spec`
      标记并往 stderr 打警告，即"第三眼只能人为显式要求"。

导入 `v8_run` 只会 import numpy/scipy/mujoco 等，不创建渲染上下文，无 GL 环境下也安全。
"""
import contextlib
import io
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'v8'))

import v8_run  # noqa: E402

SPEC = ROOT / 'docs' / 'v8' / 'SPEC_V8.md'
CN_NUM = {'一': 1, '两': 2, '二': 2, '三': 3, '四': 4, '五': 5,
          '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def spec_max_looks():
    """从 SPEC 的「N 眼之后……停车」一句里解析出 N（阿拉伯数字或中文数字）。"""
    hits = re.findall(r'([一二两三四五六七八九十]|\d+)\s*眼\s*之后', SPEC.read_text())
    if not hits:
        raise AssertionError('SPEC 里找不到“N 眼之后……停车”的规定')
    vals = {int(x) if x.isdigit() else CN_NUM[x] for x in hits}
    if len(vals) != 1:
        raise AssertionError(f'SPEC 里出现互相矛盾的停车眼数：{sorted(vals)}')
    return vals.pop()


def parse_args(*argv):
    return v8_run.build_parser().parse_args(
        ['--policy', 'conservative', '--out', '/tmp/v8_looks_test', *argv])


class TestDefaultLooksMatchSpec(unittest.TestCase):
    def test_spec_parking_limit_is_two_looks(self):
        self.assertEqual(spec_max_looks(), 2,
                         f'SPEC 改动后请同步脚本：{SPEC}:64 的停车眼数不再是 2')

    def test_default_max_looks_equals_spec(self):
        self.assertEqual(v8_run.MAX_LOOKS_BY_SPEC, spec_max_looks(),
                         'MAX_LOOKS_BY_SPEC 必须等于 SPEC 里的停车眼数')

    def test_extra_looks_is_one_less_than_spec(self):
        self.assertEqual(v8_run.MAX_EXTRA_LOOKS, v8_run.MAX_LOOKS_BY_SPEC - 1)
        self.assertEqual(v8_run.MAX_EXTRA_LOOKS, 1, '默认只允许在第二眼之后停车')

    def test_argparse_default_is_spec_value(self):
        self.assertEqual(parse_args().max_looks, spec_max_looks(),
                         '--max-looks 默认值必须取规范值，不能是 1+旧常量')


class TestExplicitOverSpecLooks(unittest.TestCase):
    def test_default_run_not_flagged(self):
        _, exceed = v8_run.resolve_max_looks(v8_run.MAX_LOOKS_BY_SPEC)
        self.assertFalse(exceed, '默认两眼不应带 looks_exceed_spec 标记')

    def test_explicit_three_looks_is_flagged_and_warns(self):
        a = parse_args('--max-looks', '3')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            a.max_looks, exceed = v8_run.resolve_max_looks(a.max_looks)
        self.assertTrue(exceed, '--max-looks 3 必须带 looks_exceed_spec=true')
        self.assertEqual(a.max_looks, 3)
        self.assertIn('--max-looks 3', err.getvalue(), '超规范时必须在 stderr 明确警告')
        self.assertIn('SPEC', err.getvalue())

    def test_explicit_five_looks_is_flagged(self):
        # SPEC §2 的老运行用 --max-looks 5 复现 conservative 停车行为，也必须被标记
        _, exceed = v8_run.resolve_max_looks(parse_args('--max-looks', '5').max_looks)
        self.assertTrue(exceed)

    def test_fewer_looks_is_not_flagged(self):
        _, exceed = v8_run.resolve_max_looks(1)
        self.assertFalse(exceed)


if __name__ == '__main__':
    unittest.main()
