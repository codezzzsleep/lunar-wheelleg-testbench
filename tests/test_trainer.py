"""
训练器回归测试：Adam、动作概率一致性、GAE 边界、RNG 隔离。

  .venv/bin/python -m unittest tests.test_trainer -v
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import ppo  # noqa: E402

PY = sys.executable


def batch_of(rng, n=8, sign=1.0):
    params = ppo.init_params(rng)
    obs = rng.normal(0, 0.5, size=(n, ppo.OBS_DIM))
    f = ppo.forward(params, obs)
    raw = f['mean'] + 0.3 * np.exp(params['log_std']) * rng.standard_normal(f['mean'].shape)
    logp = ppo.gaussian_logp(params, raw, f['mean'])
    return params, {'obs': obs, 'raw': raw, 'logp_old': logp,
                    'adv': sign * rng.uniform(0.5, 1.5, size=n),
                    'ret': rng.normal(0, 1, size=n)}


class TestAdam(unittest.TestCase):
    def test_every_param_with_gradient_updates(self):
        rng = np.random.default_rng(0)
        params, b = batch_of(rng)
        before = {k: v.copy() for k, v in params.items()}
        g, _ = ppo.ppo_grads(params, b)
        ppo.Adam(params, lr=1e-2).step(params, g)
        changed = {k for k in params if not np.allclose(params[k], before[k])}
        expected = {k for k in params if np.any(np.abs(g[k]) > 0)}
        self.assertEqual(changed, expected,
                         '不能只更新最后一个键；旧实现只动了 bv1')
        self.assertGreaterEqual(len(changed & set(ppo.ACTOR_KEYS)), 5)

    def test_zero_grad_no_change(self):
        params = ppo.init_params(np.random.default_rng(1))
        before = {k: v.copy() for k, v in params.items()}
        ppo.Adam(params, lr=1e-2).step(
            params, {k: np.zeros_like(v) for k, v in params.items()})
        for k in params:
            self.assertTrue(np.allclose(params[k], before[k]))

    def test_optimizer_state_isolated(self):
        p1, b1 = batch_of(np.random.default_rng(2))
        p2, b2 = batch_of(np.random.default_rng(3))
        o1, o2 = ppo.Adam(p1), ppo.Adam(p2)
        o1.step(p1, ppo.ppo_grads(p1, b1)[0])
        o2.step(p2, ppo.ppo_grads(p2, b2)[0])
        self.assertEqual((o1.t, o2.t), (1, 1))
        self.assertNotEqual(o1.state_checksum(), o2.state_checksum())


class TestActionProbability(unittest.TestCase):
    def test_ratio_is_one_before_update(self):
        params = ppo.init_params(np.random.default_rng(4))
        # 按实际动作维度构造必然被裁剪的 bias（不写死 3 维）
        params['bm'] = np.array([3.0, -3.0, 0.0, 3.0][:ppo.ACT_DIM])
        rng = np.random.default_rng(5)
        obs = rng.normal(0, 0.5, size=(32, ppo.OBS_DIM))
        raws, logps, execs = [], [], []
        for i in range(32):
            e, r, lp, _ = ppo.sample(params, obs[i], rng)
            execs.append(e); raws.append(r); logps.append(lp)
        f = ppo.forward(params, obs)
        recomputed = ppo.gaussian_logp(params, np.array(raws), f['mean'])
        self.assertLess(float(np.max(np.abs(recomputed - np.array(logps)))), 1e-12)
        ratio = np.exp(recomputed - np.array(logps))
        self.assertLess(float(np.max(np.abs(ratio - 1))), 1e-9)
        self.assertTrue(np.all(np.abs(np.array(execs)) <= 1.0))
        self.assertTrue(np.any(np.abs(np.array(raws)) > 1.0),
                        '样本里应当有被环境裁剪的边界情况')

    def test_sampling_reproducible(self):
        p1 = ppo.init_params(np.random.default_rng(6))
        p2 = ppo.init_params(np.random.default_rng(6))
        obs = np.zeros(ppo.OBS_DIM)
        a = ppo.sample(p1, obs, np.random.default_rng(7))
        b = ppo.sample(p2, obs, np.random.default_rng(7))
        self.assertTrue(np.allclose(a[1], b[1]))
        self.assertAlmostEqual(a[2], b[2], places=12)


class TestGAE(unittest.TestCase):
    def test_true_terminal_no_bootstrap(self):
        adv, _ = ppo.gae([1.0, 2.0], [0.5, 0.8], [1.0, 0.0], [1.0, 0.0],
                         last_value=99.0, gamma=0.5, lam=1.0)
        self.assertTrue(np.allclose(adv, [1.5, 1.2]), adv)

    def test_time_truncation_bootstraps(self):
        adv, _ = ppo.gae([1.0, 2.0], [0.5, 0.8], [1.0, 1.0], [1.0, 0.0],
                         last_value=4.0, gamma=0.5, lam=1.0)
        self.assertTrue(np.allclose(adv, [2.5, 3.2]), adv)

    def test_cross_episode_not_chained(self):
        adv, _ = ppo.gae([1.0, 2.0], [0.5, 0.8], [1.0, 0.0], [1.0, 0.0],
                         last_value=7.0, gamma=0.5, lam=1.0)
        self.assertTrue(np.allclose(adv, [1.5, 1.2]), adv)


class TestRngIsolation(unittest.TestCase):
    """评估频率改变不应改变训练轨迹（任务书第六节）。"""

    def _run(self, eval_every, td):
        cfg = json.loads((ROOT / 'configs/R_low.json').read_text())
        cfg['total_control_steps'] = 2048
        cfg['horizon'] = 512
        cfg['eval_every_updates'] = eval_every
        cfg['eval_episode_seeds'] = [0]
        p = pathlib.Path(td) / f'cfg_{eval_every}.json'
        p.write_text(json.dumps(cfg))
        out = pathlib.Path(td) / f'run_{eval_every}'
        r = subprocess.run([PY, str(ROOT / 'scripts/train.py'), '--config', str(p),
                            '--seed', '0', '--out', str(out)],
                           capture_output=True, text=True, cwd=str(ROOT))
        if r.returncode != 0:
            self.fail(f'train 失败：{r.stderr[-600:]}')
        logs = [json.loads(l) for l in (out / 'train_log.jsonl').read_text().splitlines()]
        return logs

    def test_eval_frequency_does_not_change_training(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._run(1, td)
            b = self._run(1000, td)
        n = min(len(a), len(b))
        self.assertGreater(n, 0)
        for i in range(n):
            self.assertEqual(a[i]['actor_checksum'], b[i]['actor_checksum'],
                             f'第 {i+1} 次更新的 actor 被评估频率影响')
            self.assertEqual(a[i]['critic_checksum'], b[i]['critic_checksum'])


class TestNoFakeResume(unittest.TestCase):
    def test_resume_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'run'
            r = subprocess.run([PY, str(ROOT / 'scripts/train.py'),
                                '--config', str(ROOT / 'configs/R_low.json'),
                                '--out', str(out), '--resume'],
                               capture_output=True, text=True, cwd=str(ROOT))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('不支持续训', r.stderr)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
