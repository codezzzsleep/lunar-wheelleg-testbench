"""
第 2 关：无人值守跑完一批场景，自动出报告。

每个（资产 × 考生）是一次独立仿真；4 核并行。
结果一行一个 JSON，方便后面按分组统计。

用法：
  python scripts/batch.py --stances low high --out runs/batch.jsonl
"""
import json, pathlib, sys, time, argparse, os
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

sys.path.insert(0, str(pathlib.Path(__file__).parent))
RESULTS = pathlib.Path('runs')


def one(task):
    asset_dir, stance, y_off = task
    try:
        from exam import run
        r = run(asset_dir, stance=stance, target_x=2.0, seconds=18.0, y_offset=y_off)
        man = json.loads((pathlib.Path(asset_dir) / 'manifest.json').read_text())
        r['source_kind'] = man.get('source_kind', 'lux3d')
        r['asset_id'] = man.get('asset_id', pathlib.Path(asset_dir).name)
        r['family'] = man.get('family', pathlib.Path(asset_dir).name)
        r['rel_height'] = man['rel_height']
        r['rel_width'] = man['rel_width']
        r['concavity'] = man['concavity']
        r['coacd_parts'] = man['coacd_parts']
        return r
    except Exception as e:
        return {'asset': str(asset_dir), 'stance': stance, 'y_offset': y_off,
                'outcome': 'ERROR', 'error': repr(e)[:200]}


def layer_of(rel_h):
    if rel_h < 0.5:
        return 'L0 (<0.5)'
    if rel_h < 1.0:
        return 'L1 (0.5-1)'
    if rel_h < 1.5:
        return 'L2 (1-1.5)'
    return 'L3 (>1.5)'


def summarize(rows):
    """按 (来源, 分层, 考生) 聚合完成率。"""
    from collections import defaultdict
    agg = defaultdict(lambda: {'n': 0, 'completed': 0, 'outcomes': defaultdict(int),
                               'attempts': 0, 'engaged': 0})
    for r in rows:
        if r.get('outcome') == 'ERROR':
            continue
        k = (r['source_kind'], layer_of(r['rel_height']), r['stance'])
        a = agg[k]
        a['attempts'] += 1
        # 没接触到障碍物的仿真不算成绩：机器人只是从旁边开过去了。
        # 把它计成 completed 会把通过率抬到假高——第一版就踩了这个坑。
        if not r.get('engaged', r.get('first_contact_s') is not None):
            continue
        a['engaged'] += 1
        a['n'] += 1
        a['completed'] += 1 if r['outcome'] == 'completed' else 0
        a['outcomes'][r['outcome']] += 1
    out = []
    for (src, layer, stance), a in sorted(agg.items()):
        out.append({
            'source': src, 'layer': layer, 'stance': stance,
            'attempts': a['attempts'], 'engaged': a['engaged'],
            'n': a['n'], 'completed': a['completed'],
            'pass_rate': round(a['completed'] / a['n'], 3) if a['n'] else None,
            'outcomes': dict(a['outcomes']),
        })
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--stances', nargs='+', default=['low', 'high'])
    ap.add_argument('--out', default='runs/batch.jsonl')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--filter', default=None, help='只跑名字含该子串的资产')
    ap.add_argument('--offsets', default='0,0.04,0.08,0.12,0.16,0.20,0.24,0.28,0.32,0.36,0.40,0.44',
                    help='障碍物横向偏移（采样"轮子会不会碰上"这条边界）')
    a = ap.parse_args()

    dirs = sorted(p for p in pathlib.Path('assets/processed').iterdir()
                  if (p / 'manifest.json').exists())
    if a.filter:
        dirs = [d for d in dirs if a.filter in d.name]
    offsets = [float(x) for x in a.offsets.split(',')]
    tasks = [(str(d), s, y) for d in dirs for s in a.stances for y in offsets]
    print(f'{len(dirs)} assets x {len(a.stances)} stances x {len(offsets)} offsets = {len(tasks)} sims', flush=True)

    t0 = time.time()
    rows = []
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=a.workers, mp_context=mp.get_context('fork')) as ex, \
            out.open('w') as fh:
        for i, r in enumerate(ex.map(one, tasks), 1):
            rows.append(r)
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
            if i % 20 == 0:
                print(f'  {i}/{len(tasks)}  {time.time()-t0:.0f}s', flush=True)

    summary = summarize(rows)
    (RESULTS / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    (RESULTS / 'batch_meta.json').write_text(json.dumps(
        {'runs': len(rows), 'seconds': round(time.time() - t0, 1),
         'assets': len(dirs)}, indent=2))

    print(f'\n{len(rows)} sims in {time.time()-t0:.0f}s\n')
    print(f'{"source":11s} {"layer":12s} {"stance":7s} {"n":>3s} {"pass":>5s}  outcomes')
    for s in summary:
        print(f"{s['source']:11s} {s['layer']:12s} {s['stance']:7s} {s['n']:3d} "
              f"{(s['pass_rate'] or 0):5.2f}  {s['outcomes']}")
