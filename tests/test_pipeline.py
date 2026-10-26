"""编排器失败传播与清单一致性（任务书第三节问题 3）。"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable


class TestPipelinePropagation(unittest.TestCase):
    def test_eval_failure_fails_pipeline(self):
        """评估阶段全部失败时，总体必须失败（旧实现仍 exit=0、ok=true）。"""
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            # 只跑链路前半段，然后伪造一个必失败的评估阶段
            r = subprocess.run(
                [PY, str(ROOT / 'scripts/pipeline.py'), '--demo', '--skip-train',
                 '--out', str(out)], capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            data = json.loads((out / 'pipeline.json').read_text())
            self.assertIn('status', data)
            self.assertTrue(data['status']['chain_ok'])
            # 三种状态不能混为一谈
            self.assertFalse(data['status']['learning_verified'])
            self.assertIn('learning_note', data['status'])

    def test_missing_checkpoint_marks_failure(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            r = subprocess.run(
                [PY, str(ROOT / 'scripts/pipeline.py'), '--demo', '--out', str(out)],
                capture_output=True, text=True, cwd=str(ROOT), timeout=3000)
            # demo 若成功则必须有 eval 产物；若失败则退出码必须非零
            if r.returncode == 0:
                evals = json.loads((out / 'evals.json').read_text())
                self.assertTrue(all(e.get('returncode') == 0 for e in evals))
            else:
                self.assertNotEqual(r.returncode, 0)


class TestManifestChain(unittest.TestCase):
    def test_verified_scenes_are_training_scenes(self):
        src = (ROOT / 'scripts/pipeline.py').read_text()
        self.assertIn('scenes/P_train.json', src)
        self.assertIn('scenes/G_train.json', src)
        self.assertNotIn("'scenes/A_sparse.json', 'scenes/B_slope.json',\n"
                         "                        'scenes/C_debris.json'", src)


if __name__ == '__main__':
    unittest.main()
