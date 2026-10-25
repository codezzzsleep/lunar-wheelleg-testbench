"""
关键回归测试（对应任务书第十节 A–D、F）。

  python -m unittest discover -s tests -v

只覆盖会真正影响结论正确性的点，不追求覆盖率。
需要渲染/干净安装的项（H、I）不在此文件内，见 README 的验证范围说明。
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))


def _write_results(dirpath, rows):
    p = pathlib.Path(dirpath) / 'results.jsonl'
    p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
    return p


def _rec(**kw):
    base = {
        'status': 'ok', 'shape': 'box', 'source_kind': 'procedural', 'controller': 'hold',
        'stance': 'low', 'outcome': 'completed', 'contact_any': True, 'contact_wheel': False,
        'dimensions': {'rel_height': 1.0}, 'asset_id': 'proc_box_h090',
        'final_x': 3.0, 'max_tilt_deg': 5.0, 'trial_id': 't' + str(kw.get('i', 0)),
    }
    base.update(kw)
    return base


class TestGroupingIsolation(unittest.TestCase):
    """A. 形状与考生不得混组。"""

    def test_shape_not_merged(self):
        import demo
        rows = [
            _rec(shape='box', outcome='tipped', i=1),
            _rec(shape='cylinder', outcome='completed', i=2),
            _rec(shape='ramp', outcome='completed', i=3),
        ]
        groups = demo.summarize(rows)
        shapes = {(g['shape'], g['outcomes'].get('completed', 0)) for g in groups}
        self.assertIn(('box', 0), shapes, '方块组必须保持 0 完成，不能被圆柱/斜坡拉高')
        self.assertIn(('cylinder', 1), shapes)
        self.assertIn(('ramp', 1), shapes)
        # 方块单独成组后完成率必须是 0%，不能变成 67%
        box = [g for g in groups if g['shape'] == 'box'][0]
        self.assertEqual(box['completed'], 0)

    def test_controller_not_merged(self):
        import demo
        rows = [
            _rec(controller='hold', outcome='tipped', i=1),
            _rec(controller='step', outcome='completed', i=2),
        ]
        groups = {(g['shape'], g['controller']): g for g in demo.summarize(rows)}
        self.assertEqual(groups[('box', 'hold')]['completed'], 0)
        self.assertEqual(groups[('box', 'step')]['completed'], 1)
        # 不能出现一个 50% 的合并组
        self.assertNotEqual(len(groups), 1)

    def test_counts_separate_contact_and_outcome(self):
        import analyze
        rows = [
            _rec(contact_any=False, outcome='completed', i=1),
            _rec(contact_any=True, contact_wheel=True, outcome='tipped', i=2),
            {'status': 'precheck_failed', 'outcome': 'precheck_failed', 'i': 3},
        ]
        c = analyze.counts(rows)
        self.assertEqual(c['records'], 3)
        self.assertEqual(c['executed'], 2)
        self.assertEqual(c['precheck_failed'], 1)
        self.assertEqual(c['not_contacted'], 1)
        self.assertEqual(c['contact_any'], 1)


class TestReportTruthfulness(unittest.TestCase):
    """B/C. 报告只能用指定输入，不能凭空产生别的考生结论。"""

    def test_single_hold_record_only(self):
        with tempfile.TemporaryDirectory() as td:
            _write_results(td, [_rec(controller='hold', outcome='completed')])
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/analyze.py'),
                                '--input', str(pathlib.Path(td) / 'results.jsonl'),
                                '--out', td], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            report = (pathlib.Path(td) / 'report.md').read_text()
            self.assertIn('| hold |', report)
            # 断言的是"结果表里没有 step/adapt 的行"，而不是正文里不出现这两个词
            self.assertNotIn('| step |', report)
            self.assertNotIn('| adapt |', report)
            self.assertNotIn('24%', report, '不得出现硬编码的 24%')
            self.assertNotIn('0.12 m', report)

    def test_empty_input_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / 'results.jsonl'
            p.write_text('\n')
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/analyze.py'),
                                '--input', str(p), '--out', td],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, '空输入必须拒绝生成成功报告')

    def test_only_specified_input_read(self):
        with tempfile.TemporaryDirectory() as td:
            _write_results(td, [_rec(controller='hold', outcome='completed')])
            # 同目录放一个"旧批次"，内容含 step 成功；报告不应受其影响
            (pathlib.Path(td) / 'batch_old.jsonl').write_text(
                json.dumps(_rec(controller='step', outcome='completed')) + '\n')
            subprocess.run([sys.executable, str(ROOT / 'scripts/analyze.py'),
                            '--input', str(pathlib.Path(td) / 'results.jsonl'),
                            '--out', td], capture_output=True, text=True, check=True)
            report = (pathlib.Path(td) / 'report.md').read_text()
            self.assertNotIn('| step |', report)
            self.assertNotIn('| adapt |', report)


class TestGateNotStale(unittest.TestCase):
    """D. 预置旧成功报告 + 本次失败 → 必须 FAIL。"""

    def test_stale_success_cannot_mask_failure(self):
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / 'gate1_report.json').write_text(
                json.dumps({'gate': 1, 'all_pass': True}))
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/gate1.py'),
                                '--out', td, '--inject-failure', 'ITEM 3'],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, '注入失败时退出码必须非零')
            rep = json.loads((pathlib.Path(td) / 'gate1_report.json').read_text())
            self.assertFalse(rep['all_pass'], '旧的成功报告不得让本次判 PASS')


class TestCollisionContrast(unittest.TestCase):
    """F. 凸包与凸分解在孔洞任务上行为必须不同。"""

    def test_hole_behaviour_differs(self):
        import check_collision
        with tempfile.TemporaryDirectory() as td:
            r = check_collision.run_check(tmpdir=td)
        self.assertTrue(r['raw_blocked'], '原始闭合网格应被当作凸包挡住小球')
        self.assertTrue(r['decomposed_passes'], '拆凸块后小球应穿过孔洞')
        self.assertGreaterEqual(r['coacd_parts'], 2)


if __name__ == '__main__':
    unittest.main()
