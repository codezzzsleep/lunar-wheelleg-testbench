"""
薄编排入口：一条命令串起"条件 → 场景 → 校验 → 训练 → 共同评估"。

  .venv/bin/python scripts/pipeline.py --demo --out runs/pipeline_demo

各阶段复用已有脚本，不重复实现：
  1. scene_compiler  : 任务条件 -> 场景集
  2. verify_scenes   : 物理有效性检查（射线实测 + 落地 + 真实接触）
  3. run_experiments : 按 plan 训练（记录退出码）
  4. evaluate        : 在**同一份**测试清单上评估各 checkpoint
  5. 汇总报告

--demo 用较短预算跑通整条链路；--full 用冻结预算。
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable


def sh(args, log_path=None, timeout=7200):
    t0 = time.time()
    if log_path:
        pathlib.Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'w') as fh:
            rc = subprocess.run([PY] + [str(a) for a in args], cwd=str(ROOT),
                                stdout=fh, stderr=subprocess.STDOUT,
                                timeout=timeout).returncode
    else:
        rc = subprocess.run([PY] + [str(a) for a in args], cwd=str(ROOT),
                            timeout=timeout).returncode
    return rc, round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--demo', action='store_true')
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--out', required=True)
    ap.add_argument('--skip-train', action='store_true')
    a = ap.parse_args()
    if not (a.demo or a.full):
        raise SystemExit('需要 --demo 或 --full 指定预算')

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    steps = {'stage': [], 'ok': True}

    def step(name, args, logname):
        print(f'== {name} ==', flush=True)
        rc, sec = sh(args, out / 'logs' / f'{logname}.log')
        steps['stage'].append({'name': name, 'returncode': rc, 'seconds': sec,
                               'log': f'logs/{logname}.log'})
        print(f'   rc={rc} {sec}s', flush=True)
        if rc != 0:
            steps['ok'] = False
        return rc

    # 1. 条件 -> 场景（P/G 两组，同地形不同几何来源）
    step('生成场景集', ['scripts/make_pg_scenes.py'], 'scenes')
    step('条件敏感性验收', ['scripts/verify_conditions.py', '--out', out / 'conditions'],
         'conditions')
    # 校验的就是训练/评估用的那几份清单（此前的 A/B/C 与 P/G 不是同一份）
    step('场景物理有效性', ['scripts/verify_scenes.py',
                        '--scenes', 'scenes/P_train.json', 'scenes/G_train.json',
                        'scenes/P_test.json', 'scenes/G_test.json',
                        '--out', out / 'verify'], 'verify')
    step('成本账本', ['scripts/cost_ledger.py', '--conditions', 'tasks/A_sparse.txt',
                 'tasks/B_slope.txt', 'tasks/C_debris.txt', '--out', out / 'cost'],
         'cost')

    if a.skip_train:
        steps['status'] = {
            'chain_ok': bool(steps['ok']),
            'physical_ok': all(s.get('returncode') == 0 for s in steps['stage']
                               if '物理' in s['name'] or '条件' in s['name']),
            'learning_verified': False,
            'learning_note': '未训练：只验证了条件→场景→物理校验链路',
        }
        (out / 'pipeline.json').write_text(json.dumps(steps, indent=2, ensure_ascii=False))
        return 0 if steps['ok'] else 1

    # 2. 训练（demo 用短预算，full 用冻结预算）
    if a.demo:
        plan = json.loads((ROOT / 'plans/pg_v2.json').read_text())
        plan['root'] = str(out / 'train')
        plan['tag'] = 'demo'
        plan['seeds'] = [0]   # demo 只跑一个种子，证明链路可运行
        for cfg in plan['configs']:
            src = ROOT / cfg['path']
            c = json.loads(src.read_text())
            c['total_control_steps'] = 6000
            c['eval_every_updates'] = 20
            c['eval_episode_seeds'] = [0]
            dst = out / f"config_{cfg['group']}.json"
            dst.write_text(json.dumps(c, indent=2))
            cfg['path'] = str(dst.relative_to(ROOT)) if str(dst).startswith(str(ROOT)) else str(dst)
        plan_path = out / 'plan_demo.json'
        plan_path.write_text(json.dumps(plan, indent=2))
    else:
        plan_path = ROOT / 'plans/pg_v2.json'
    step('训练', ['scripts/run_experiments.py', '--plan', plan_path], 'train')

    # 3. 共同清单评估
    plan = json.loads(pathlib.Path(plan_path).read_text())
    evals = []
    for cfg in plan['configs']:
        for seed in plan['seeds']:
            ck = pathlib.Path(plan['root']) / f"{cfg['group']}_s{seed}" / 'checkpoints/final.npz'
            if not ck.exists():
                evals.append({'id': f"{cfg['group']}_s{seed}", 'missing': str(ck),
                              'returncode': 1})
                steps['ok'] = False
                continue
            dst = out / 'eval' / f"{cfg['group']}_s{seed}"
            rc, sec = sh(['scripts/evaluate.py', '--checkpoint', ck,
                          '--manifest', 'scenes/test_common.json',
                          '--config', cfg['path'], '--out', dst,
                          '--label', f"{cfg['group']}_s{seed}"],
                         out / 'logs' / f"eval_{cfg['group']}_s{seed}.log")
            evals.append({'id': f"{cfg['group']}_s{seed}", 'returncode': rc,
                          'seconds': sec, 'dir': str(dst)})
            if rc != 0:
                steps['ok'] = False       # 评估失败必须让总体失败
    (out / 'evals.json').write_text(json.dumps(evals, indent=2, ensure_ascii=False))

    steps['stage'].append({'name': '共同清单评估', 'evals': evals})
    # 三种状态严格分开：链路跑通 / 物理合格 / 学习有效，不能互相顶替
    steps['status'] = {
        'chain_ok': bool(steps['ok']),
        'physical_ok': all(s.get('returncode') == 0 for s in steps['stage']
                           if '物理' in s['name'] or '条件' in s['name']),
        'learning_verified': False,
        'learning_note': ('短预算 demo 只验证链路可运行，学习收益未验证'
                          if a.demo else '学习收益需另看 docs 报告中的对照表'),
    }
    (out / 'pipeline.json').write_text(json.dumps(steps, indent=2, ensure_ascii=False))
    print(f"\n链路 ok={steps['status']['chain_ok']} 物理合格="
          f"{steps['status']['physical_ok']} 学习有效="
          f"{steps['status']['learning_verified']} -> {out/'pipeline.json'}", flush=True)
    return 0 if steps['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
