"""
实验清单管理：按 jobs 清单逐条运行训练，记录退出码与产物。

  .venv/bin/python scripts/run_experiments.py --plan plans/pg_v2.json --out runs/pg_v2

设计（回应任务书第十节"不能用 nohup 没跑完解释缺失的比较"）：
  · 每条 job 有唯一 id、独立输出目录、日志文件；
  · 退出码、耗时、日志尾部写入 ledger.json，进程被杀也能看到已完成的 job；
  · 已存在且 summary 完整的 job 会被跳过（可安全重跑本脚本）；
  · 失败的 job 记录 returncode 与 stderr 尾部，不静默忽略；
  · 顺序执行 + 可选并发数；不依赖 shell 循环。
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_plan(path):
    plan = json.loads(pathlib.Path(path).read_text())
    jobs = []
    for cfg in plan['configs']:
        for seed in plan['seeds']:
            jobs.append({
                'id': f"{plan['tag']}_{cfg['group']}_s{seed}",
                'config': cfg['path'], 'group': cfg['group'], 'seed': seed,
                'out': str(pathlib.Path(plan['root']) / f"{cfg['group']}_s{seed}"),
            })
    return plan, jobs


def is_complete(job):
    s = pathlib.Path(job['out']) / 'train_summary.json'
    if not s.exists():
        return False
    try:
        d = json.loads(s.read_text())
        return d.get('updates', 0) > 0
    except Exception:
        return False


def run_job(job, log_dir, timeout=7200):
    out = pathlib.Path(job['out'])
    out.parent.mkdir(parents=True, exist_ok=True)
    log = pathlib.Path(log_dir) / f"{job['id']}.log"
    cmd = [sys.executable, str(ROOT / 'scripts/train.py'),
           '--config', str(ROOT / job['config']),
           '--seed', str(job['seed']), '--out', str(out)]
    t0 = time.time()
    with log.open('w') as fh:
        try:
            rc = subprocess.run(cmd, cwd=str(ROOT), stdout=fh,
                                stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            rc = -9
    tail = log.read_text()[-600:] if log.exists() else ''
    return {'id': job['id'], 'group': job['group'], 'seed': job['seed'],
            'config': job['config'], 'out': job['out'], 'returncode': rc,
            'seconds': round(time.time() - t0, 1), 'log': str(log),
            'log_tail': tail[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--only', default=None, help='只跑匹配该子串的 job id')
    a = ap.parse_args()

    plan, jobs = load_plan(a.plan)
    if a.only:
        jobs = [j for j in jobs if a.only in j['id']]
    root = pathlib.Path(plan['root'])
    log_dir = root / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = root / 'ledger.json'

    ledger = {'tag': plan['tag'], 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
              'jobs': []}
    if ledger_path.exists():
        old = json.loads(ledger_path.read_text())
        ledger['jobs'] = [j for j in old.get('jobs', [])
                          if j['id'] not in {x['id'] for x in jobs}]

    for i, job in enumerate(jobs, 1):
        if is_complete(job):
            print(f"[{i}/{len(jobs)}] SKIP (已完成) {job['id']}", flush=True)
            ledger['jobs'].append({**job, 'returncode': 0, 'skipped': True,
                                   'seconds': 0})
        else:
            print(f"[{i}/{len(jobs)}] RUN {job['id']}", flush=True)
            rec = run_job(job, log_dir)
            ledger['jobs'].append(rec)
            print(f"        rc={rec['returncode']} {rec['seconds']}s", flush=True)
        ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))

    bad = [j for j in ledger['jobs'] if j.get('returncode') != 0]
    ledger['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    ledger['n_jobs'] = len(ledger['jobs'])
    ledger['n_failed'] = len(bad)
    ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"\n完成 {len(ledger['jobs'])} 条，失败 {len(bad)} 条 -> {ledger_path}")
    for j in bad:
        print(f"  FAILED {j['id']} rc={j['returncode']} {j.get('log_tail','')[-200:]}")
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
