"""
第二轮缺陷的回归测试（批次隔离、续跑、输入校验、路径解析、资产指纹、异常记录）。

  .venv/bin/python -m unittest discover -s tests -v

用小型 fixture 覆盖大多数边界；需要真实 MuJoCo 的地方才跑物理。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
PY = sys.executable


def run_cli(*args, cwd=None):
    return subprocess.run([PY, *map(str, args)], capture_output=True, text=True,
                          cwd=str(cwd or ROOT))


def write_manifest(d, parts, **over):
    d = pathlib.Path(d)
    (d / 'parts').mkdir(parents=True, exist_ok=True)
    for name in parts:
        (d / 'parts' / name).write_bytes(b'solid x\n')
    man = {'parts': [f'parts/{n}' for n in parts], 'pass': True,
           'height_m': 0.13, 'width_x_m': 0.30, 'width_y_m': 0.30,
           'rel_height': 1.51, 'rel_width': 0.79, 'shape': 'box',
           'source_kind': 'procedural', 'asset_id': d.name, 'family': d.name,
           'concavity': 0.0, 'coacd_parts': 1}
    man.update(over)
    (d / 'manifest.json').write_text(json.dumps(man))
    return d


def good_rec(**kw):
    r = {'trial_id': 't1', 'status': 'ok', 'outcome': 'completed',
         'controller': 'hold', 'stance': 'low', 'contact_any': True,
         'contact_wheel': False, 'dimensions': {'rel_height': 1.0},
         'shape': 'box', 'source_kind': 'procedural', 'gravity': 1.62,
         'friction': '0.9 0.02 0.001', 'timestep': 0.002, 'control': {'kp': 150.0}}
    r.update(kw)
    return r


class TestAssetResolution(unittest.TestCase):
    """任务 4：路径约定、缺件、残留文件、空格路径。"""

    def test_relative_paths_resolve_from_manifest_dir(self):
        import runio
        with tempfile.TemporaryDirectory() as td:
            d = write_manifest(pathlib.Path(td) / 'asset_a', ['part_00.stl', 'part_01.stl'])
            r = runio.resolve_asset(d)
            self.assertTrue(r['ok'], r['reason'])
            self.assertEqual(r['path_mode'], 'relative')
            self.assertEqual(len(r['part_paths']), 2)
            self.assertTrue(all(p.is_absolute() for p in r['part_paths']))

    def test_copied_asset_has_same_fingerprint(self):
        import runio
        with tempfile.TemporaryDirectory() as td:
            a = write_manifest(pathlib.Path(td) / 'a', ['p.stl'])
            b = pathlib.Path(td) / 'b'
            shutil.copytree(a, b)
            self.assertEqual(runio.resolve_asset(a)['collision_sha'],
                             runio.resolve_asset(b)['collision_sha'])

    def test_stray_unreferenced_file_does_not_change_identity(self):
        import runio
        with tempfile.TemporaryDirectory() as td:
            a = write_manifest(pathlib.Path(td) / 'a', ['p.stl'])
            before = runio.resolve_asset(a)['collision_sha']
            (a / 'parts' / 'stray.stl').write_bytes(b'junk')
            self.assertEqual(before, runio.resolve_asset(a)['collision_sha'])

    def test_referenced_file_change_changes_identity(self):
        import runio
        with tempfile.TemporaryDirectory() as td:
            a = write_manifest(pathlib.Path(td) / 'a', ['p.stl'])
            before = runio.resolve_asset(a)['collision_sha']
            (a / 'parts' / 'p.stl').write_bytes(b'solid y\n')
            self.assertNotEqual(before, runio.resolve_asset(a)['collision_sha'])

    def test_missing_part_reports_resolved_path(self):
        import runio
        with tempfile.TemporaryDirectory() as td:
            a = write_manifest(pathlib.Path(td) / 'a', ['p.stl'])
            (a / 'parts' / 'p.stl').unlink()
            r = runio.resolve_asset(a)
            self.assertFalse(r['ok'])
            self.assertEqual(r['reason'], 'missing_part')
            self.assertTrue(r['missing'] and 'p.stl' in r['missing'][0])

    def test_path_with_spaces(self):
        import runio
        with tempfile.TemporaryDirectory() as td:
            d = write_manifest(pathlib.Path(td) / 'asset with space', ['part 00.stl'])
            r = runio.resolve_asset(d)
            self.assertTrue(r['ok'], r['reason'])

    def test_cross_cwd_same_result(self):
        import runio
        asset = ROOT / 'assets/processed/proc_box_h130'
        here = runio.resolve_asset(asset)
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(
                [PY, '-c',
                 'import sys; sys.path.insert(0, r"%s"); import runio, json;'
                 'r = runio.resolve_asset(r"%s");'
                 'print(json.dumps({"ok": r["ok"], "collision_sha": r["collision_sha"],'
                 ' "path_mode": r["path_mode"]}))' % (ROOT / 'scripts', asset)],
                capture_output=True, text=True, cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out['collision_sha'], here['collision_sha'])
            self.assertTrue(out['ok'])


class TestPrecheckRobustness(unittest.TestCase):
    """任务 2：坏资产必须返回 precheck_failed，不能二次崩溃。"""

    def _run(self, asset_dir):
        import exam
        return exam.run(str(asset_dir), stance='low', controller='hold')

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._run(td)
            self.assertEqual(r['status'], 'precheck_failed')
            self.assertEqual(r['reason'], 'manifest_missing')
            self.assertIsNotNone(r.get('asset_id'))

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / 'manifest.json').write_text('{not json')
            r = self._run(td)
            self.assertEqual(r['status'], 'precheck_failed')
            self.assertEqual(r['reason'], 'manifest_unreadable')

    def test_manifest_not_object(self):
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / 'manifest.json').write_text('[1,2,3]')
            r = self._run(td)
            self.assertEqual(r['reason'], 'manifest_not_object')

    def test_no_parts(self):
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / 'manifest.json').write_text(json.dumps({'parts': []}))
            r = self._run(td)
            self.assertEqual(r['reason'], 'no_collision_parts')

    def test_bad_dimensions(self):
        with tempfile.TemporaryDirectory() as td:
            write_manifest(td, ['p.stl'], height_m='abc')
            r = self._run(td)
            self.assertEqual(r['reason'], 'bad_dimensions')

    def test_manifest_pass_false(self):
        with tempfile.TemporaryDirectory() as td:
            write_manifest(td, ['p.stl'], pass_=False, **{'pass': False})
            r = self._run(td)
            self.assertEqual(r['reason'], 'manifest_pass_false')


class TestWorkerExceptionRecorded(unittest.TestCase):
    """任务 2：worker 异常变成 ERROR 记录，不中断整批、不冒充物理失败。"""

    def test_unknown_controller_becomes_error(self):
        import demo
        rec = demo._one({'asset_dir': str(ROOT / 'assets/processed/proc_box_h130'),
                         'controller': 'no_such_controller', 'stance': 'low',
                         'y_offset': 0.0, 'obstacle_x': 2.0, 'seconds': 1.0,
                         'asset': 'proc_box_h130'})
        self.assertEqual(rec['status'], 'ERROR')
        self.assertIn('traceback', rec['detail'])


class TestAnalyzerValidation(unittest.TestCase):
    """任务 3：输入校验与退出码。"""

    def _analyze(self, rows, extra=(), manifest=None):
        td = tempfile.mkdtemp()
        d = pathlib.Path(td)
        (d / 'results.jsonl').write_text(
            '\n'.join(json.dumps(r) if not isinstance(r, str) else r for r in rows) + '\n')
        if manifest:
            (d / 'manifest.json').write_text(json.dumps(manifest))
        r = run_cli(ROOT / 'scripts/analyze.py', '--input', d / 'results.jsonl',
                    '--out', d, *extra)
        return r, d

    def test_duplicate_trial_id_rejected(self):
        r, d = self._analyze([good_rec(), good_rec()])
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((d / 'report.md').exists())

    def test_all_error_rejected(self):
        r, d = self._analyze([good_rec(status='ERROR', outcome='ERROR')])
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((d / 'diagnostics.json').exists())
        self.assertFalse((d / 'report.md').exists())

    def test_non_object_line_rejected(self):
        r, d = self._analyze(['[1,2,3]'])
        self.assertNotEqual(r.returncode, 0)

    def test_missing_field_rejected(self):
        bad = {'trial_id': 'x', 'status': 'ok'}   # 缺 controller / stance / outcome
        r, d = self._analyze([bad])
        self.assertNotEqual(r.returncode, 0)

    def test_missing_planned_id_detected(self):
        manifest = {'trial_ids': ['t1', 't2'], 'planned_trials': 2}
        r, d = self._analyze([good_rec()], manifest=manifest)
        self.assertNotEqual(r.returncode, 0)

    def test_allow_partial_marks_report(self):
        manifest = {'trial_ids': ['t1', 't2'], 'planned_trials': 2}
        r, d = self._analyze([good_rec()], extra=('--allow-partial',), manifest=manifest)
        self.assertIn(r.returncode, (0, 3))
        txt = (d / 'report.md').read_text()
        self.assertIn('partial', txt.lower())

    def test_exploratory_single_record_ok(self):
        r, d = self._analyze([good_rec()])
        self.assertEqual(r.returncode, 0)
        txt = (d / 'report.md').read_text()
        self.assertIn('探索性报告', txt)
        self.assertNotIn('| step |', txt)


class TestBatchIsolation(unittest.TestCase):
    """任务 1：新建/续跑与身份校验。"""

    def _run(self, suite, out, *extra):
        return run_cli(ROOT / 'scripts/demo.py', '--suite', suite, '--out', out,
                       '--limit', '2', '--workers', '2', *extra)

    def test_cross_suite_refused_and_files_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            self.assertEqual(self._run('smoke', out).returncode, 0)
            before = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
            r = self._run('canonical', out)
            self.assertNotEqual(r.returncode, 0)
            after = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
            for k in ('manifest.json', 'environment.json', 'results.jsonl'):
                if k in before:
                    self.assertEqual(before[k], after[k], f'{k} 被改动')

    def test_resume_only_fills_missing(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            self.assertEqual(self._run('smoke', out).returncode, 0)
            p = out / 'results.jsonl'
            lines = p.read_text().splitlines()
            p.write_text(lines[0] + '\n')          # 模拟中断
            r = self._run('smoke', out, '--resume')
            self.assertEqual(r.returncode, 0, r.stderr)
            ids = [json.loads(x)['trial_id'] for x in p.read_text().splitlines()]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(len(ids), 2)

    def test_source_change_refused(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            self.assertEqual(self._run('smoke', out).returncode, 0)
            ctrl = ROOT / 'scripts/controllers.py'
            backup = ctrl.read_bytes()
            try:
                ctrl.write_bytes(backup + b'\n# identity probe\n')
                r = self._run('smoke', out, '--resume')
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('身份', r.stderr)
            finally:
                ctrl.write_bytes(backup)

    def test_duplicate_id_in_results_refused(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            self.assertEqual(self._run('smoke', out).returncode, 0)
            p = out / 'results.jsonl'
            lines = p.read_text().splitlines()
            p.write_text('\n'.join([lines[0], lines[0]]) + '\n')
            r = self._run('smoke', out, '--resume')
            self.assertNotEqual(r.returncode, 0)

    def test_lock_blocks_second_writer(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            self.assertEqual(self._run('smoke', out).returncode, 0)
            (out / '.run.lock').write_text('{}')
            r = self._run('smoke', out, '--resume')
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('拒绝写入', r.stderr)


class TestManifestCompleteness(unittest.TestCase):
    """任务 1B：清单完整、计数不混淆。"""

    def test_full_trial_list_and_counts(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            r = run_cli(ROOT / 'scripts/demo.py', '--suite', 'smoke', '--out', out,
                        '--limit', '3', '--workers', '2')
            self.assertEqual(r.returncode, 0, r.stderr)
            man = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(len(man['trials']), 3)
            self.assertEqual(len(man['trial_ids']), 3)
            self.assertEqual(man['planned_trials'], 3)
            self.assertIn('available_asset_count', man)
            self.assertIn('selected_asset_count', man)
            self.assertNotIn('...', json.dumps(man['trial_ids']))
            fps = man['asset_fingerprints']
            flat = [v for k, v in fps.items() if k == 'flat']
            self.assertTrue(flat and flat[0]['collision_sha'] is None)


if __name__ == '__main__':
    unittest.main()
