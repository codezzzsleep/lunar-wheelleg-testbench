"""产物路径可移植性回归（2026-11-11 修复）。

背景：`target_decision.json` 里记的是沙箱绝对路径 `/workspace/lunar-lab/assets/...`。
换一台机器（仓库在别处）后，`trimesh.load` 会直接
`ValueError: string is not a file`，V8 §3.3 的补跑就是这样断的。
修复：`v8_imagine.resolve_path()` 做多路解析，新写入的路径改记仓库相对路径。

  .venv/bin/python -m unittest tests.test_v8_portability -v
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'v8'))
import v8_imagine as IM  # noqa: E402


class TestResolvePath(unittest.TestCase):
    def setUp(self):
        self.real = ROOT / 'docs' / 'v8' / 'STATUS.md'
        self.assertTrue(self.real.exists(), '测试依赖 docs/v8/STATUS.md 存在')

    def test_foreign_absolute_path_is_rebased(self):
        """沙箱绝对路径 -> 本机 ROOT 下的同名文件。"""
        foreign = '/workspace/lunar-lab/docs/v8/STATUS.md'
        self.assertEqual(pathlib.Path(IM.resolve_path(foreign)).resolve(),
                         self.real.resolve())

    def test_repo_relative_path_resolves(self):
        self.assertEqual(pathlib.Path(IM.resolve_path('docs/v8/STATUS.md')).resolve(),
                         self.real.resolve())

    def test_local_absolute_path_passes_through(self):
        self.assertEqual(pathlib.Path(IM.resolve_path(str(self.real))).resolve(),
                         self.real.resolve())

    def test_unknown_path_is_returned_unchanged(self):
        """解析不出来就原样返回，让调用方报原始错误——不猜、不静默。"""
        bogus = '/workspace/lunar-lab/no/such/file.glb'
        self.assertEqual(IM.resolve_path(bogus), bogus)

    def test_repo_rel_prefers_relative(self):
        self.assertEqual(IM.repo_rel(self.real), 'docs/v8/STATUS.md')

    def test_repo_rel_keeps_outside_paths_absolute(self):
        outside = pathlib.Path('/tmp/definitely-not-in-repo.glb')
        self.assertEqual(IM.repo_rel(outside), str(outside))


if __name__ == '__main__':
    unittest.main()
