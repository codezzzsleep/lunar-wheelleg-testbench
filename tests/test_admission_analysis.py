"""准入归因与门槛工作点两个分析脚本的回归（合成数据，不跑物理）。

2026-11-11 新增：`scripts/v8/v8_admission_report.py`（逐候选卡在哪条门槛 + 阈值敏感性）
与 `scripts/v7/v7_gate_report.py`（自检工作点 + 5 cm 余量的留一检验）。
这两个脚本是要写进交付文档的结论来源，必须钉住方向与口径，避免以后改坏还看不出来。

  .venv/bin/python -m unittest tests.test_admission_analysis -v
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'v8'))
sys.path.insert(0, str(ROOT / 'scripts' / 'v7'))
import v7_gate_report as GATE      # noqa: E402
import v8_admission_report as ADM  # noqa: E402


class TestNormalizedDirection(unittest.TestCase):
    """阈值方向必须归一化：ge 与 le 都要变成"≥1 即过线"，否则敏感性会算反。"""

    def test_ge(self):
        self.assertAlmostEqual(ADM.normalized('contour_iou', 'ge', 0.70, 0.70), 1.0)
        self.assertLess(ADM.normalized('contour_iou', 'ge', 0.69, 0.70), 1.0)

    def test_le(self):
        self.assertAlmostEqual(ADM.normalized('free_intrusion_frac', 'le', 0.20, 0.20), 1.0)
        self.assertLess(ADM.normalized('free_intrusion_frac', 'le', 0.30, 0.20), 1.0)

    def test_zero_threshold_is_skipped(self):
        self.assertIsNone(ADM.normalized('x', 'ge', 1.0, 0.0))


def _decision(tmp, cands, th=None):
    th = th or {'schema': 'v5-admission/v1', 'calibrated_from': 'test',
                'scale_ratio': {'min': 0.889, 'max': 1.09},
                'hidden_frac_min': 0.3578, 'shell_contact_min': 0.0486,
                'free_intrusion_max': 0.2864, 'contour_iou_min': 0.7068}
    d = pathlib.Path(tmp) / 'imagination' / 'looks' / 'look1' / 'T1' / 'decide'
    d.mkdir(parents=True)
    (d / 'target_decision.json').write_text(json.dumps(
        {'thresholds': th, 'candidates': cands, 'admitted_ids': [c['id'] for c in cands if c['admitted']]}))
    return pathlib.Path(tmp)


def _cand(cid, contour, admitted=False, scale=1.0, hidden=0.8, shell=0.3, intr=0.1):
    return {'id': cid, 'admitted': admitted, 'contour_iou': contour, 'scale_ratio': scale,
            'hidden_frac': hidden, 'shell_contact': shell, 'free_intrusion_frac': intr}


class TestAnalyseV8(unittest.TestCase):
    def test_blocking_metric_is_contour_when_only_contour_fails(self):
        with tempfile.TemporaryDirectory() as td:
            run = _decision(td, [_cand('A1', 0.70, scale=1.0)])
            rows = ADM.analyse(run)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['admitted'])
        self.assertEqual(rows[0]['blocking'], 'contour_iou')
        self.assertAlmostEqual(rows[0]['fails'][0]['shortfall_pct'], 1.0, places=0)

    def test_admitted_candidate_has_no_fails(self):
        with tempfile.TemporaryDirectory() as td:
            run = _decision(td, [_cand('B2', 0.80, admitted=True)])
            rows = ADM.analyse(run)
        self.assertTrue(rows[0]['admitted'])
        self.assertEqual(rows[0]['fails'], [])

    def test_relaxation_counts_directionally(self):
        """放宽 10% 应当让 contour 0.65 的候选过线；收紧 10% 应当让它更过不了。"""
        with tempfile.TemporaryDirectory() as td:
            run = _decision(td, [_cand('A1', 0.66, scale=1.0)])
            rows = ADM.analyse(run)
            sens = ADM.perturb(rows, run, 0.10)
        self.assertEqual(sens['放宽 10%']['admitted'], 1)
        self.assertEqual(sens['收紧 10%']['admitted'], 0)


class TestGateReport(unittest.TestCase):
    def _rows(self, td, rows):
        p = pathlib.Path(td) / 'rows.json'
        p.write_text(json.dumps(rows))
        return p

    def test_counts_and_operating_point(self):
        rows = []
        # 好的 3 份：2 采纳、1 误拒
        rows += [{'status': 'ok', 'hidden_iou': 0.9, 'admitted': True, 'contour_iou': 0.80,
                  'rear_err_m': 0.02, 'sun': 'high_side', 'rock': 'A'},
                 {'status': 'ok', 'hidden_iou': 0.8, 'admitted': True, 'contour_iou': 0.78,
                  'rear_err_m': -0.03, 'sun': 'low_side', 'rock': 'A'},
                 {'status': 'ok', 'hidden_iou': 0.7, 'admitted': False, 'contour_iou': 0.72,
                  'rear_err_m': None, 'sun': 'low_side', 'rock': 'B'}]
        # 坏的 2 份：都拒
        rows += [{'status': 'ok', 'hidden_iou': 0.3, 'admitted': False, 'contour_iou': 0.4,
                  'rear_err_m': None, 'sun': 'low_side', 'rock': 'B'},
                 {'status': 'ok', 'hidden_iou': 0.2, 'admitted': False, 'contour_iou': 0.3,
                  'rear_err_m': None, 'sun': 'high_side', 'rock': 'C'},
                 {'status': 'failed'}]
        with tempfile.TemporaryDirectory() as td:
            rep = GATE.analyse(self._rows(td, rows))
        self.assertEqual(rep['n'], 5)          # failed 的被排除
        self.assertEqual(rep['bad'], 2)
        self.assertEqual(rep['good'], 3)
        self.assertEqual(rep['bad_rejected'], 2)
        self.assertEqual(rep['good_admitted'], 2)
        self.assertEqual(rep['good_wrongly_rejected'], 1)
        self.assertEqual(rep['admitted_abs_rear_err']['max'], 0.03)

    def test_leave_one_sun_out_flags_exceedance(self):
        rows = [{'status': 'ok', 'hidden_iou': 0.9, 'admitted': True, 'contour_iou': 0.8,
                 'rear_err_m': 0.01, 'sun': 'a', 'rock': 'A'},
                {'status': 'ok', 'hidden_iou': 0.9, 'admitted': True, 'contour_iou': 0.8,
                 'rear_err_m': 0.01, 'sun': 'b', 'rock': 'A'},
                {'status': 'ok', 'hidden_iou': 0.9, 'admitted': True, 'contour_iou': 0.8,
                 'rear_err_m': 0.09, 'sun': 'b', 'rock': 'B'}]
        with tempfile.TemporaryDirectory() as td:
            rep = GATE.analyse(self._rows(td, rows))
        loo = rep['leave_one_sun_out']
        # 留出 a：其余(b)最大 0.09 → 预测 0.09，实际 0.01，不超出
        self.assertFalse(loo['a']['exceeded'])
        # 留出 b：其余(a)最大 0.01 → 预测 0.01，实际 0.09，超出
        self.assertTrue(loo['b']['exceeded'])


if __name__ == '__main__':
    unittest.main()
