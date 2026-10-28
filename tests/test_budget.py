"""
工作包 A 回归：预算、恢复、模式（A3 全部 9 项）。

  .venv/bin/python -m unittest tests.test_budget -v
"""
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import budget as B          # noqa: E402
import imagine              # noqa: E402

BUDGET_20_1 = {'hard_cap': 20, 'per_task_cap': 20,
               'max_create_tasks': 1, 'scope': 'test'}
BUDGET_300_15 = {'hard_cap': 300, 'per_task_cap': 20,
                 'max_create_tasks': 15, 'scope': 'test'}


def tmp_ledger():
    return B.BudgetLedger(pathlib.Path(tempfile.mkdtemp()) / 'ledger.jsonl')


class TestReserve(unittest.TestCase):
    def test_1_first_planned_blocks_second(self):
        led = tmp_ledger()
        ok1, _ = led.reserve('a' * 64, 'at1', 20, BUDGET_20_1)
        ok2, why = led.reserve('b' * 64, 'at2', 20, BUDGET_20_1)
        self.assertTrue(ok1)
        self.assertFalse(ok2, why)

    def test_2_downloaded_does_not_free_budget(self):
        led = tmp_ledger()
        led.reserve('a' * 64, 'at1', 20, BUDGET_20_1)
        led.mark('at1', B.ST_DOWNLOADED, task_id=1)
        ok2, why = led.reserve('b' * 64, 'at2', 20, BUDGET_20_1)
        self.assertFalse(ok2, why)
        self.assertEqual(led.report(BUDGET_20_1)['created_tasks'], 1)

    def test_3_pending_uncertain_invalid_failed_still_held(self):
        for st in (B.ST_PENDING, B.ST_UNCERTAIN, B.ST_INVALID, B.ST_FAILED,
                   B.ST_SUCCEEDED):
            led = tmp_ledger()
            led.reserve('a' * 64, 'at1', 20, BUDGET_20_1)
            led.mark('at1', st, task_id=7)
            ok, why = led.reserve('b' * 64, 'at2', 20, BUDGET_20_1)
            self.assertFalse(ok, f'{st} 应仍占额度：{why}')

    def test_release_only_when_planned(self):
        led = tmp_ledger()
        led.reserve('a' * 64, 'at1', 20, BUDGET_20_1)
        led.release('at1', 'upload_failed')
        ok, _ = led.reserve('b' * 64, 'at2', 20, BUDGET_20_1)
        self.assertTrue(ok)
        # 已创建的不能释放
        led2 = tmp_ledger()
        led2.reserve('c' * 64, 'at3', 20, BUDGET_20_1)
        led2.mark('at3', B.ST_CREATED, task_id=9)
        with self.assertRaises(RuntimeError):
            led2.release('at3', 'try')

    def test_4_same_identity_two_task_ids_kept(self):
        led = tmp_ledger()
        ident = 'a' * 64
        led.reserve(ident, 'at1', 20, BUDGET_300_15)
        led.mark('at1', B.ST_DOWNLOADED, task_id=111)
        led.reserve(ident, 'at2', 20, BUDGET_300_15)
        led.mark('at2', B.ST_DOWNLOADED, task_id=222)
        rows = [r for r in led.rows() if r['identity'] == ident]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['task_id'] for r in rows}, {111, 222})
        self.assertEqual(led.used_credits(), 40)
        # 更新一条不污染另一条
        led.mark('at1', B.ST_FAILED, note='x')
        rows2 = {r['attempt_id']: r for r in led.rows() if r['identity'] == ident}
        self.assertEqual(rows2['at2']['status'], B.ST_DOWNLOADED)
        self.assertEqual(rows2['at2']['task_id'], 222)

    def test_5_concurrent_reserve_single_slot(self):
        led = tmp_ledger()
        results = []
        barrier = threading.Barrier(2)

        def worker(i):
            barrier.wait()
            ok, _ = led.reserve(f'{i:064x}', f'at{i}', 20, BUDGET_20_1)
            results.append(ok)

        ts = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sum(results), 1, f'应只有一个成功：{results}')

    def test_6_reject_invalid_numbers(self):
        led = tmp_ledger()
        for bad in (float('nan'), float('inf'), -5, '20', None):
            ok, why = led.reserve('a' * 64, 'at1', bad, BUDGET_20_1)
            self.assertFalse(ok, f'{bad!r} 应被拒绝')
        ok, why = led.reserve('a' * 64, 'at2', 20, {'hard_cap': float('nan'),
                                                    'per_task_cap': 20,
                                                    'max_create_tasks': 1})
        self.assertFalse(ok)

    def test_identity_must_be_64_hex(self):
        led = tmp_ledger()
        ok, why = led.reserve('short', 'at1', 20, BUDGET_20_1)
        self.assertFalse(ok)
        ok, _ = led.reserve('g' * 64, 'at2', 20, BUDGET_20_1)
        self.assertTrue(ok)      # 只校验长度；内容由 request_identity 生成

    def test_corrupt_ledger_detected(self):
        p = pathlib.Path(tempfile.mkdtemp()) / 'ledger.jsonl'
        p.write_text('{"ok":1}\nnot json\n')
        led = B.BudgetLedger(p)
        with self.assertRaises(RuntimeError):
            led.rows()


class TestModes(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.img = self.tmp / 'in.png'
        self.img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        self.plan = self.tmp / 'plan.json'
        self.plan.write_text(json.dumps({'credits_upper_per_task': 20, 'inputs': [
            {'id': 'X1', 'image': str(self.img), 'variant': 'orig', 'repeat_idx': 0,
             'model': {'version': 'G1-Turbo', 'face_count': 30000}}]}))
        self.budgetp = self.tmp / 'budget.json'
        self.budgetp.write_text(json.dumps(BUDGET_300_15))
        self.ledger = self.tmp / 'ledger.jsonl'
        self.cache = self.tmp / 'cache'

    def _argv(self, *flags):
        return ['imagine.py', '--plan', str(self.plan), '--budget', str(self.budgetp),
                '--ledger', str(self.ledger), '--cache', str(self.cache), *flags]

    def test_7_resume_never_creates(self):
        with mock.patch.object(sys, 'argv', self._argv('--resume')), \
             mock.patch.object(imagine, 'upload_image') as up, \
             mock.patch.object(imagine, 'submit_img_to_3d') as cr, \
             mock.patch.dict('os.environ', {'AHOLO_API_KEY': 'k'}):
            rc = imagine.main()
        self.assertEqual(up.call_count, 0, 'resume 不应上传')
        self.assertEqual(cr.call_count, 0, 'resume 不应 create')
        self.assertEqual(rc, 0)

    def test_8_dry_run_no_network(self):
        with mock.patch.object(sys, 'argv', self._argv('--dry-run')), \
             mock.patch.object(imagine, 'upload_image') as up, \
             mock.patch.object(imagine, 'submit_img_to_3d') as cr:
            rc = imagine.main()
        self.assertEqual((up.call_count, cr.call_count), (0, 0))
        self.assertEqual(rc, 0)

    def test_9_mode_conflict_rejected(self):
        with mock.patch.object(sys, 'argv', self._argv('--submit', '--resume')):
            with self.assertRaises(SystemExit):
                imagine.main()

    def test_10_cached_only_missing_returns_nonzero(self):
        with mock.patch.object(sys, 'argv', self._argv('--cached-only')):
            rc = imagine.main()
        self.assertEqual(rc, 2, 'cached-only 缺缓存应返回未满足')

    def test_11_corrupt_cache_not_hit(self):
        ident = imagine._identity_of(json.loads(self.plan.read_text())['inputs'][0])
        d = imagine.cache_path(self.cache, ident)
        d.mkdir(parents=True)
        (d / 'model.glb').write_bytes(b'not a glb')
        (d / 'meta.json').write_text(json.dumps({'glb_sha': 'x'}))
        self.assertFalse(imagine.cache_valid(self.cache, ident))

    def test_12_submit_timeout_marks_uncertain_and_keeps_budget(self):
        with mock.patch.object(sys, 'argv', self._argv('--submit')), \
             mock.patch.object(imagine, 'upload_image', return_value='http://x/y.png'), \
             mock.patch.object(imagine, 'submit_img_to_3d',
                               side_effect=TimeoutError('boom')), \
             mock.patch.dict('os.environ', {'AHOLO_API_KEY': 'k'}):
            imagine.main()
        led = B.BudgetLedger(self.ledger)
        rows = led.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], B.ST_UNCERTAIN)
        self.assertEqual(led.used_credits(), 20, 'uncertain 仍占额度')

    def test_13_upload_failure_releases_and_does_not_create(self):
        with mock.patch.object(sys, 'argv', self._argv('--submit')), \
             mock.patch.object(imagine, 'upload_image', side_effect=OSError('net')), \
             mock.patch.object(imagine, 'submit_img_to_3d') as cr, \
             mock.patch.dict('os.environ', {'AHOLO_API_KEY': 'k'}):
            imagine.main()
        self.assertEqual(cr.call_count, 0)
        led = B.BudgetLedger(self.ledger)
        self.assertEqual(led.used_credits(), 0, '确定未发出应释放')


if __name__ == '__main__':
    unittest.main()
