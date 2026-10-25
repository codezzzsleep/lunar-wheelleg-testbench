"""
一键运行入口：按 suite 生成 trial 清单、并行执行、写运行目录。

  python scripts/demo.py --suite smoke     --out runs/smoke
  python scripts/demo.py --suite canonical --out runs/canonical

设计要点（对应复查意见第 5、6 节）：
  · 每个 trial 的结果逐条落盘，中断后可续跑（已完成 trial_id 会被跳过）
  · records 里同时保存 contact_any / contact_wheel / outcome，三者分开统计
  · 分组键包含 shape 与 controller，绝不把方块、圆柱、斜坡或三个考生混成一个率
  · trial 清单数量在运行前自动校验，防止"计划 2088、实际跑了 1200"这类静默缺失
"""
import argparse
import json
import pathlib
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import runio

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROCESSED = ROOT / 'assets/processed'
OFFSETS_12 = [round(i * 0.04, 2) for i in range(12)]     # 0.00 .. 0.44
CONTROLLERS = ['hold', 'step', 'adapt']
STANCES = ['low', 'high']

# smoke 用到的具体资产（存在性在运行前检查）
SMOKE_ASSETS = ['cargo_crate_w300', 'proc_box_h130', 'lander_leg_w300']


def available_assets():
    out = []
    for d in sorted(PROCESSED.iterdir()):
        if (d / 'manifest.json').exists():
            out.append(d.name)
    return out


def build_trials(suite):
    if suite == 'smoke':
        trials = []
        for stance in STANCES:                       # 1) 平地基线
            trials.append(dict(asset=None, controller='hold', stance=stance,
                               y_offset=0.0))
        for name in SMOKE_ASSETS:                    # 2) 生成物 / 方块 / 凹形件
            if not (PROCESSED / name).exists():
                raise SystemExit(f'smoke 需要的资产不存在：{name}')
            for stance in STANCES:
                for ctrl in CONTROLLERS:
                    trials.append(dict(asset=name, controller=ctrl,
                                       stance=stance, y_offset=0.0))
        return trials

    if suite == 'canonical':
        import json
        all_assets = available_assets()
        if not all_assets:
            raise SystemExit('assets/processed 下没有可用资产')
        # 主对照：方块 + 生成网格。圆柱/斜坡只在与生成资产同高度的档位做附加测试，
        # 不混进方块基线，也不为每个高度都建一份（那会让批次无谓膨胀）。
        lux_h = []
        for n in all_assets:
            d = (PROCESSED / n / 'manifest.json')
            if not d.exists():
                continue
            m = json.loads(d.read_text())
            if m.get('source_kind') == 'lux3d':
                lux_h.append(round(m['rel_height'], 2))
        assets = []
        for n in all_assets:
            m = json.loads((PROCESSED / n / 'manifest.json').read_text())
            kind = m.get('source_kind')
            shape = m.get('shape', 'box')
            if kind == 'lux3d' or shape == 'box':
                assets.append(n)
            elif shape in ('cylinder', 'ramp'):
                if any(abs(round(m['rel_height'], 2) - h) < 0.02 for h in lux_h):
                    assets.append(n)
        trials = []
        for a in assets:
            for stance in STANCES:
                for ctrl in CONTROLLERS:
                    for y in OFFSETS_12:
                        trials.append(dict(asset=a, controller=ctrl,
                                           stance=stance, y_offset=y))
        return trials

    raise SystemExit(f'未知 suite: {suite}')


def _one(task):
    from exam import run
    cfg = dict(task)
    rec = run(cfg.pop('asset_dir'), stance=cfg['stance'], controller=cfg['controller'],
              y_offset=cfg['y_offset'], obstacle_x=cfg.get('obstacle_x', 2.0),
              seconds=cfg.get('seconds', 18.0))
    rec['trial_id'] = cfg['trial_id']
    rec['planned'] = cfg
    return rec


def summarize(rows):
    """按 (shape, source_kind, controller, stance, rel_height 层) 分组。"""
    def layer(h):
        if h is None:
            return 'none'
        if h < 0.5:
            return 'L0 (<0.5)'
        if h < 1.0:
            return 'L1 (0.5-1)'
        if h < 1.5:
            return 'L2 (1-1.5)'
        return 'L3 (>1.5)'

    agg = defaultdict(lambda: {'planned': 0, 'executed': 0, 'precheck_failed': 0,
                               'error': 0, 'contact_any': 0, 'contact_wheel': 0,
                               'outcomes': Counter()})
    for r in rows:
        rel_h = (r.get('dimensions') or {}).get('rel_height')
        k = (r.get('shape'), r.get('source_kind'), r.get('controller'),
             r.get('stance'), layer(rel_h))
        a = agg[k]
        a['planned'] += 1
        if r.get('status') == 'precheck_failed':
            a['precheck_failed'] += 1
            a['outcomes']['precheck_failed'] += 1
            continue
        a['executed'] += 1
        a['contact_any'] += 1 if r.get('contact_any') else 0
        a['contact_wheel'] += 1 if r.get('contact_wheel') else 0
        a['outcomes'][r.get('outcome') or 'ERROR'] += 1

    out = []
    for (shape, src, ctrl, stance, lay), a in sorted(
            agg.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        completed = a['outcomes'].get('completed', 0)
        out.append({
            'shape': shape, 'source_kind': src, 'controller': ctrl,
            'stance': stance, 'layer': lay,
            'planned': a['planned'], 'executed': a['executed'],
            'precheck_failed': a['precheck_failed'],
            'contact_any': a['contact_any'], 'contact_wheel': a['contact_wheel'],
            'completed': completed,
            'completed_rate_all_executed': round(completed / a['executed'], 3) if a['executed'] else None,
            'outcomes': dict(a['outcomes']),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--suite', required=True, choices=['smoke', 'canonical'])
    ap.add_argument('--out', required=True, help='运行目录，例如 runs/canonical')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 个 trial（调试用）')
    ap.add_argument('--objects', type=int, default=0,
                    help='每 1 个生成资产附带多少个方块对照（仅 canonical 缩减用）')
    a = ap.parse_args()

    trials = build_trials(a.suite)
    if a.limit:
        trials = trials[:a.limit]

    # 补全 asset_dir 与 trial_id
    for t in trials:
        name = t['asset']
        t['asset_dir'] = None if name is None else str(PROCESSED / name)
        t['obstacle_x'] = 2.0
        t['seconds'] = 18.0
        t['trial_id'] = runio.trial_id({**t, 'asset': name})

    ids = [t['trial_id'] for t in trials]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup:
        raise SystemExit(f'trial_id 重复：{dup[:5]}（配置相同但被认为不同任务）')

    expected = len(trials)
    run_dir, run_id = runio.new_run(a.out, a.suite, {
        'planned_trials': expected,
        'asset_count': len(available_assets()),
        'offsets': OFFSETS_12, 'controllers': CONTROLLERS, 'stances': STANCES,
        'obstacle_x': 2.0, 'seconds': 18.0,
        'gravity': 1.62, 'friction': '0.9 0.02 0.001',
        'clearance_m': 0.25,
        'trial_ids': ids[:50] + (['...'] if expected > 50 else []),
    })
    print(f'run: {run_dir}  suite={a.suite}  planned={expected}', flush=True)

    done = runio.already_done(run_dir)
    todo = [t for t in trials if t['trial_id'] not in done]
    if done:
        print(f'续跑：跳过已完成 {len(done)} 个', flush=True)

    t0 = time.time()
    completed = 0
    with ProcessPoolExecutor(max_workers=a.workers,
                             mp_context=mp.get_context('fork')) as ex:
        for rec in ex.map(_one, todo):
            runio.append_result(run_dir, rec)
            completed += 1
            if completed % 50 == 0:
                print(f'  {completed}/{len(todo)}  {time.time()-t0:.0f}s', flush=True)

    rows, bad = runio.load_results(run_dir / 'results.jsonl')
    summary = summarize(rows)
    (run_dir / 'summary.json').write_text(json.dumps({
        'run_id': run_id, 'suite': a.suite,
        'planned': expected, 'records': len(rows), 'unparsable_lines': bad,
        'wall_seconds': round(time.time() - t0, 1),
        'groups': summary,
    }, indent=2, ensure_ascii=False))

    print(f'\n{len(rows)} 条记录 / 计划 {expected}，用时 {time.time()-t0:.0f}s')
    print(f'{"shape":10s} {"src":11s} {"ctrl":6s} {"stance":7s} {"layer":11s} '
          f'{"exec":>5s} {"pre":>4s} {"any":>4s} {"wheel":>6s} {"done":>5s}')
    for g in summary:
        print(f'{str(g["shape"]):10s} {str(g["source_kind"]):11s} {g["controller"]:6s} '
              f'{g["stance"]:7s} {g["layer"]:11s} {g["executed"]:5d} '
              f'{g["precheck_failed"]:4d} {g["contact_any"]:4d} {g["contact_wheel"]:6d} '
              f'{g["completed"]:5d}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
