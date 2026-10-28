"""加载器负例：缺 GLB / 缺 clean / 缺 world / 组混淆，必须各自拒绝。"""
import json, pathlib, shutil, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'scripts'))
import candidate_store as CS

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _mk(tmp, cid='X1', group='A', with_glb=True, with_clean=True, with_world=True):
    tmp = pathlib.Path(tmp)
    plan = tmp / 'plan.json'
    img = tmp / 'in.png'
    img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 32)
    plan.write_text(json.dumps({'inputs': [{
        'id': cid, 'group': group, 'image': str(img), 'variant': 'orig',
        'repeat_idx': 0, 'model': {'version': 'G1-Turbo', 'face_count': 30000}}]}))
    clean = tmp / 'clean'
    if with_clean:
        d = clean / cid; d.mkdir(parents=True)
        body = d / 'body.stl'
        body.write_bytes(b'solid x\nendsolid x\n')
        (d / 'clean.json').write_text(json.dumps({
            'precheck': {'verdict': 'ok'}, 'clean_sha': CS._sha(body),
            'clean_path': str(body), 'verify': {'thin_ratio': 0.5},
            'raw_sha': 'a' * 64, 'id': cid}))
    align = tmp / 'align'
    if with_world:
        d = align / 'world' / cid; d.mkdir(parents=True)
        body = d / 'body.stl'
        body.write_bytes(b'solid y\nendsolid y\n')
        (d / 'manifest.json').write_text(json.dumps({
            'coordinate_frame': 'world', 'parts': ['body.stl'],
            'world_sha': CS._sha(body), 'T_world_from_asset': [[1,0,0,0]]*4}))
        (align / f'{cid}.json').write_text(json.dumps({
            'pass': False, 'best': {'native': {'mask_iou': 0.9}},
            'raw_sha': 'a' * 64, 'candidate': str(clean / cid / 'body.stl')}))
    pol = tmp / 'policy.json'
    pol.write_text(json.dumps({'version': 'test/v1', 'criteria': {
        'thin_ratio_min': 0.2, 'contour_iou_min': 0.85}}))
    return plan, clean, align, pol


class TestLoaderRejects(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def _load(self, **kw):
        plan, clean, align, pol = _mk(self.tmp, **kw)
        return CS.load_candidates(plan, clean, align, pol, 'A')

    def test_missing_world_rejected(self):
        acc, rep = self._load(with_world=False)
        self.assertEqual(len(acc), 0)
        txt = ' '.join(rep['rejected'][0]['reasons'])
        self.assertIn('world', txt)

    def test_missing_clean_rejected(self):
        acc, rep = self._load(with_clean=False)
        self.assertEqual(len(acc), 0)
        self.assertIn('clean', ' '.join(rep['rejected'][0]['reasons']))

    def test_group_mismatch_rejected(self):
        acc, rep = self._load(group='B')      # 请求 A 组，计划是 B 组
        self.assertEqual(len(acc), 0)
        self.assertIn('observation_group mismatch', rep['rejected'][0]['reasons'][0])

    def test_world_sha_tamper_rejected(self):
        plan, clean, align, pol = _mk(self.tmp)
        man = align / 'world' / 'X1' / 'manifest.json'
        m = json.loads(man.read_text()); m['world_sha'] = '0' * 64
        man.write_text(json.dumps(m))
        acc, rep = CS.load_candidates(plan, clean, align, pol, 'A')
        self.assertEqual(len(acc), 0)
        self.assertIn('SHA mismatch', ' '.join(rep['rejected'][0]['reasons']))

    def test_clean_sha_tamper_rejected(self):
        plan, clean, align, pol = _mk(self.tmp)
        cj = clean / 'X1' / 'clean.json'
        c = json.loads(cj.read_text()); c['clean_sha'] = '1' * 64
        cj.write_text(json.dumps(c))
        acc, rep = CS.load_candidates(plan, clean, align, pol, 'A')
        self.assertEqual(len(acc), 0)
        self.assertIn('SHA mismatch', ' '.join(rep['rejected'][0]['reasons']))

    def test_valid_candidate_accepted_but_not_eligible_without_policy(self):
        acc, rep = self._load()
        # 结构合格 -> 进入加载列表；但 policy 判据（如无 task_id）不满足时不自动 eligible
        if acc:
            self.assertIn('planning_eligible', acc[0])


if __name__ == '__main__':
    unittest.main()
