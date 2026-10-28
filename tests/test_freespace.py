"""
B2 自由空间回归（align-metric/v2.1）。

  MUJOCO_GL=osmesa .venv/bin/python -m unittest tests.test_freespace -v
"""
import json, pathlib, subprocess, sys, tempfile
import unittest
import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import align                                            # noqa: E402

OX = 1.80


def _obs_with_base(tmp):
    base = trimesh.creation.box(extents=[0.20, 0.40, 0.30])
    base.apply_translation([0, 0, 0.15])
    p = tmp / 'base_local.stl'; base.export(p)
    case = tmp / 'case.json'
    case.write_text(json.dumps({'case_id': 'fs', 'seed': 0, 'H': 0.30, 'W': 0.40,
                                'goal_x': 2.8, 'channel_half': 1.2,
                                'obstacle_x': OX, 'mesh': str(p)}))
    subprocess.run([sys.executable, str(ROOT / 'scripts/observe.py'),
                    '--case', str(case), '--out', str(tmp / 'obs')],
                   check=True, cwd=str(ROOT))
    return base, tmp / 'obs'


class TestFreespaceV21(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        cls.base, cls.obs = _obs_with_base(cls.tmp)

    def test_truth_self_alignment_passes(self):
        m = self.base.copy(); m.apply_translation([OX, 0, 0])
        p = self.tmp / 'truth.stl'; m.export(p)
        ev = align.render_eval(m, str(self.obs), tmpdir=p, want_vis_pt=True)
        self.assertGreater(ev['mask_iou'], 0.85)
        self.assertLess(ev['vis_pt_p95_mm'], 2.0)
        self.assertLess(ev['freespace_violation'], 0.05)

    def test_intrusion_beyond_silhouette_is_detected(self):
        """候选伸到原轮廓外、遮住已观测地面 -> 必须被判侵入。"""
        prot = trimesh.creation.box(extents=[0.12, 0.16, 0.30])
        prot.apply_translation([1.74 - OX, 0.28, 0.15])
        cand = trimesh.util.concatenate([self.base, prot])
        cand.apply_translation([OX, 0, 0])
        p = self.tmp / 'cand_out.stl'; cand.export(p)
        ev = align.render_eval(cand, str(self.obs), tmpdir=p, want_vis_pt=True)
        self.assertGreater(ev['freespace_violation'], 0.05,
                           f'轮廓外侵入应被检出：{ev["freespace_violation"]}')
        # 旧口径只看 obs_mask 内，必然漏检
        self.assertGreater(ev['freespace_outside_mask'], 0)

    def test_intrusion_in_front_of_object_is_detected(self):
        """候选比观测表面更靠近相机 -> 必须被判侵入。"""
        m = trimesh.creation.box(extents=[0.20, 0.40, 0.30])
        m.apply_translation([OX - 0.10, 0, 0.15])       # 整体前移 10 cm
        p = self.tmp / 'cand_front.stl'; m.export(p)
        ev = align.render_eval(m, str(self.obs), tmpdir=p, want_vis_pt=True)
        self.assertGreater(ev['freespace_violation'], 0.05)

    def test_identical_input_recomputes_identically(self):
        m = self.base.copy(); m.apply_translation([OX, 0, 0])
        p = self.tmp / 'det.stl'; m.export(p)
        a = align.render_eval(m, str(self.obs), tmpdir=p, want_vis_pt=True)
        b = align.render_eval(m, str(self.obs), tmpdir=p, want_vis_pt=True)
        for k in ('mask_iou', 'vis_pt_med_mm', 'vis_pt_p95_mm',
                  'freespace_violation', 'depth_med_mm'):
            self.assertEqual(a[k], b[k], f'{k} 两次不一致')

    def test_sky_region_not_counted_as_known_airspace(self):
        """天空/远裁剪像素不计入已知空域，不制造伪违例。"""
        m = self.base.copy(); m.apply_translation([OX, 0, 0])
        p = self.tmp / 'sky.stl'; m.export(p)
        ev = align.render_eval(m, str(self.obs), tmpdir=p, want_vis_pt=True)
        # 真值自对齐时侵入必须很小；若把天空当已知空域，这个值会被抬高
        self.assertLess(ev['freespace_violation'], 0.05)


if __name__ == '__main__':
    unittest.main()
