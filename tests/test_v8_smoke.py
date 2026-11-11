"""端到端冒烟：真的把一台车跑完一遍（需要 GL，默认跳过）。

为什么需要：2026-11-11 一天里踩过的三个坑，任何一个都能被这个测试挡住——
  1. 产物里记着沙箱绝对路径 `/workspace/lunar-lab/...`，换机器后 `trimesh.load` 直接崩；
  2. `v8_eval.py` 静默跳过没有 `summary.json` 的运行，`eval.json` 少了整台车；
  3. 重放守卫的自搬移 bug（把目录 move 到自己身上）。

默认不跑（一次约 40–90 秒且要渲染上下文）：

    RUN_V8_SMOKE=1 python -m unittest tests.test_v8_smoke -v
    # 没有 GL 的机器先： ./scripts/setup_local_gl.sh && source <(./scripts/setup_local_gl.sh --export)
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tests'))
from _gl import gl_available  # noqa: E402

ENABLED = bool(os.environ.get('RUN_V8_SMOKE'))


@unittest.skipUnless(ENABLED, '设置 RUN_V8_SMOKE=1 才跑（约 40–90 秒，需要渲染上下文）')
@unittest.skipUnless(gl_available(), 'no OpenGL context')
class TestV8Smoke(unittest.TestCase):
    """跑一次 `--policy optimistic`：它不依赖任何 Lux3D 结果，最短路径覆盖
    「建场景 → 观测 → 规划 → 执行 → 写 summary/events/traj → 复盘」。"""

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        cls.out = pathlib.Path(cls._td.name) / 'run'
        cls.proc = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/v8/v8_run.py'),
             '--policy', 'optimistic', '--out', str(cls.out)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
        cls.dir = cls.out / 'optimistic'

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_exit_code_zero(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-1200:])

    def test_summary_and_events_exist(self):
        for name in ('summary.json', 'events.jsonl', 'traj.npz'):
            self.assertTrue((self.dir / name).exists(), f'缺 {name}')

    def test_summary_is_self_describing(self):
        s = json.loads((self.dir / 'summary.json').read_text())
        for k in ('policy', 'result', 'looks', 'sim_time_s', 'looks_exceed_spec'):
            self.assertIn(k, s, f'summary 缺字段 {k}')
        self.assertIn(s['result'], ('arrived', 'stuck', 'collision', 'stopped_short'))

    def test_no_absolute_workspace_paths_in_artifacts(self):
        """产物里不应再出现别的机器上的绝对路径（2026-11-11 的移植性 bug）。"""
        bad = []
        for p in self.dir.rglob('*.json'):
            txt = p.read_text(errors='replace')
            if '/workspace/lunar-lab' in txt:
                bad.append(str(p.relative_to(self.dir)))
        self.assertEqual(bad, [], f'这些产物里还留着沙箱绝对路径：{bad}')

    def test_eval_does_not_skip_a_run_with_summary(self):
        """复盘脚本必须把这台车列进 robots（静默跳过是真出过的 bug）。"""
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/v8/v8_eval.py'),
                            '--run', str(self.out)],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        rep = json.loads((self.out / 'eval.json').read_text())
        self.assertIn('optimistic', rep['robots'])
        self.assertEqual(rep['incomplete_runs'], [])


if __name__ == '__main__':
    unittest.main()
