"""
一键运行入口：生成 trial 清单、并行执行、写运行目录、校验完整性。

  .venv/bin/python scripts/demo.py --suite smoke     --out runs/smoke_x
  .venv/bin/python scripts/demo.py --suite canonical --out runs/canonical_x
  .venv/bin/python scripts/demo.py --suite canonical --out runs/canonical_x --resume

批次隔离（第二轮任务 1）：
  · 新运行只接受不存在或为空的目录；否则在写入任何文件前拒绝
  · 续跑必须显式 --resume，并校验 suite / 完整任务集合 / 运行身份
  · 同一目录只允许一个写入进程（.run.lock）
清单（任务 1B）：
  · 保存**全部** trial 配置与 id，不截断、无省略号
  · 区分 available_asset_count / selected_asset_count / planned_trials
异常（任务 2）：
  · 单 trial 抛异常 → 记为 ERROR 记录，其余继续
  · MuJoCo 加载/仿真异常在 exam 内已转成 ERROR，不冒充物理结果
"""
import argparse
import json
import pathlib
import sys
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import exam
import runio

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROCESSED = ROOT / 'assets/processed'
OFFSETS_12 = [round(i * 0.04, 2) for i in range(12)]
CONTROLLERS = ['hold', 'step', 'adapt']
STANCES = ['low', 'high']
SMOKE_ASSETS = ['cargo_crate_w300', 'proc_box_h130', 'lander_leg_w300']


# ------------------------------------------------------------------ 清单

def available_assets():
    return [d.name for d in sorted(PROCESSED.iterdir())
            if (d / 'manifest.json').exists()]


def select_assets(suite):
    """返回 (selected_names, meta)。canonical 只在与生成资产同高度时纳入圆柱/斜坡。"""
    all_assets = available_assets()
    if suite == 'smoke':
        missing = [n for n in SMOKE_ASSETS if n not in all_assets]
        if missing:
            raise SystemExit(f'smoke 需要的资产不存在：{missing}')
        return list(SMOKE_ASSETS), {'available_asset_count': len(all_assets)}

    if suite != 'canonical':
        raise SystemExit(f'未知 suite: {suite}')

    lux_h, meta = [], {}
    for n in all_assets:
        man = json.loads((PROCESSED / n / 'manifest.json').read_text())
        meta[n] = {'source_kind': man.get('source_kind'), 'shape': man.get('shape', 'box'),
                   'rel_height': round(float(man.get('rel_height') or 0), 2)}
    for n, m in meta.items():
        if m['source_kind'] == 'lux3d':
            lux_h.append(m['rel_height'])

    selected = []
    for n in all_assets:
        m = meta[n]
        if m['source_kind'] == 'lux3d' or m['shape'] == 'box':
            selected.append(n)
        elif m['shape'] in ('cylinder', 'ramp'):
            if any(abs(m['rel_height'] - h) < 0.02 for h in lux_h):
                selected.append(n)
    return selected, {'available_asset_count': len(all_assets)}


def build_trials(suite):
    selected, meta = select_assets(suite)
    trials = []
    if suite == 'smoke':
        for stance in STANCES:
            trials.append(dict(asset=None, controller='hold', stance=stance, y_offset=0.0))
        for name in selected:
            for stance in STANCES:
                for ctrl in CONTROLLERS:
                    trials.append(dict(asset=name, controller=ctrl, stance=stance,
                                       y_offset=0.0))
    else:
        for name in selected:
            for stance in STANCES:
                for ctrl in CONTROLLERS:
                    for y in OFFSETS_12:
                        trials.append(dict(asset=name, controller=ctrl,
                                           stance=stance, y_offset=y))
    return trials, selected, meta


def prepare(trials):
    """补全 asset_dir / collision_sha / trial_id。资产解析每个资产只做一次。"""
    ctx = runio.make_context(exam.control_fingerprint(),
                             exam.scene_fingerprint())
    fps = {}
    for t in trials:
        name = t['asset']
        key = name or 'flat'
        if key not in fps:
            fps[key] = ({'collision_sha': None, 'ok': True, 'reason': 'flat'}
                        if name is None else runio.asset_fingerprint(str(PROCESSED / name)))
        fp = fps[key]
        t['asset_dir'] = None if name is None else str(PROCESSED / name)
        t['collision_sha'] = fp['collision_sha']
        t['obstacle_x'] = 2.0
        t['seconds'] = 18.0
        t['trial_id'] = runio.trial_identity(t, ctx)
    return ctx, fps


# ------------------------------------------------------------------ 执行

def _one(task):
    try:
        return exam.run(task['asset_dir'], stance=task['stance'],
                        controller=task['controller'], y_offset=task['y_offset'],
                        obstacle_x=task['obstacle_x'], seconds=task['seconds'])
    except Exception:
        return {
            'status': 'ERROR', 'outcome': 'ERROR', 'reason': 'worker_exception',
            'asset_id': task.get('asset') or 'flat',
            'asset_dir_name': task.get('asset') or 'flat',
            'controller': task['controller'], 'stance': task['stance'],
            'y_offset': task['y_offset'], 'collision_sha': task.get('collision_sha'),
            'detail': {'traceback': traceback.format_exc()[-1200:]},
        }


def summarize(rows):
    """按 (shape, source_kind, controller, stance, 高度层) 分组。"""
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
        st = r.get('status', 'ok')
        if st == 'precheck_failed':
            a['precheck_failed'] += 1
            a['outcomes']['precheck_failed'] += 1
            continue
        if st == 'ERROR':
            a['error'] += 1
            a['outcomes']['ERROR'] += 1
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
            'precheck_failed': a['precheck_failed'], 'error': a['error'],
            'contact_any': a['contact_any'], 'contact_wheel': a['contact_wheel'],
            'completed': completed,
            'completed_rate_all_executed': round(completed / a['executed'], 3) if a['executed'] else None,
            'outcomes': dict(a['outcomes']),
        })
    return out


# ------------------------------------------------------------------ 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--suite', required=True, choices=['smoke', 'canonical'])
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 个（调试用，会标记为不完整）')
    a = ap.parse_args()

    trials, selected, meta = build_trials(a.suite)
    if a.limit:
        trials = trials[:a.limit]
    ctx, fps = prepare(trials)

    ids = [t['trial_id'] for t in trials]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup:
        raise SystemExit(f'trial_id 重复：{dup[:5]}')

    config = {
        'suite': a.suite,
        'available_asset_count': meta['available_asset_count'],
        'selected_asset_count': len(selected),
        'selected_assets': selected,
        'asset_fingerprints': fps,
        'planned_trials': len(trials),
        'offsets': OFFSETS_12, 'controllers': CONTROLLERS, 'stances': STANCES,
        'obstacle_x': 2.0, 'seconds': 18.0,
        'control': exam.control_fingerprint(),
        'scene': exam.scene_fingerprint(),
        'context': ctx,          # model_sha / source_sha，供重演与续跑校验
        'identity': runio.run_identity(trials, ctx, a.suite),
        'trials': trials,                       # 完整清单，无省略号
        'trial_ids': ids,
    }

    run_dir, manifest = runio.new_run(a.out, a.suite, config, resume=a.resume)
    print(f'run: {run_dir}  suite={a.suite}  planned={len(trials)}  '
          f'assets={len(selected)}/{meta["available_asset_count"]}  '
          f'{"RESUME" if a.resume else "NEW"}', flush=True)

    with runio.RunLock(run_dir):
        rows, bad = runio.load_results(run_dir / 'results.jsonl')
        if bad and not a.resume:
            raise SystemExit(f'拒绝：结果文件有 {len(bad)} 行无法解析')
        got_ids = [r.get('trial_id') for r in rows]
        unexpected = set(got_ids) - set(ids)
        dup_existing = [k for k, v in Counter(got_ids).items() if v > 1]
        if unexpected or dup_existing:
            raise SystemExit(f'拒绝：已有记录含计划外 ID {len(unexpected)} 个、'
                             f'重复 ID {len(dup_existing)} 个')

        todo = [t for t in trials if t['trial_id'] not in set(got_ids)]
        if a.resume:
            print(f'续跑：已完成 {len(rows)}，待跑 {len(todo)}', flush=True)

        t0 = time.time()
        with ProcessPoolExecutor(max_workers=a.workers,
                                 mp_context=mp.get_context('fork')) as ex:
            for i, rec in enumerate(ex.map(_one, todo), 1):
                rec['trial_id'] = todo[i - 1]['trial_id']
                rec['planned'] = {k: todo[i - 1][k] for k in
                                  ('asset', 'controller', 'stance', 'y_offset',
                                   'obstacle_x', 'seconds')}
                runio.append_result(run_dir, rec)
                if i % 50 == 0:
                    print(f'  {i}/{len(todo)}  {time.time()-t0:.0f}s', flush=True)

        rows, bad = runio.load_results(run_dir / 'results.jsonl')
        summary = summarize(rows)
        ids_now = {r.get('trial_id') for r in rows}
        missing = set(ids) - ids_now
        extra = ids_now - set(ids)
        counts = Counter(r.get('status', 'ok') for r in rows)
        complete = (not missing) and (not extra) and (not bad) and \
                   counts.get('ERROR', 0) == 0 and len(rows) == len(ids)

        status = 'complete' if complete else 'incomplete'
        (run_dir / 'summary.json').write_text(json.dumps({
            'run_id': run_dir.name, 'suite': a.suite, 'status': status,
            'planned': len(ids), 'received': len(rows),
            'ok': counts.get('ok', 0),
            'precheck_failed': counts.get('precheck_failed', 0),
            'ERROR': counts.get('ERROR', 0),
            'missing': len(missing), 'unexpected': len(extra),
            'bad_lines': len(bad),
            'wall_seconds': round(time.time() - t0, 1),
            'groups': summary,
        }, indent=2, ensure_ascii=False))

    print(f'\n状态 {status}：计划 {len(ids)} / 收到 {len(rows)} / ok {counts.get("ok",0)} '
          f'/ 预检失败 {counts.get("precheck_failed",0)} / ERROR {counts.get("ERROR",0)} '
          f'/ 缺失 {len(missing)} / 非法行 {len(bad)}')
    print(f'{"shape":10s} {"src":11s} {"ctrl":6s} {"stance":7s} {"layer":11s} '
          f'{"exec":>5s} {"pre":>4s} {"err":>4s} {"any":>4s} {"wheel":>6s} {"done":>5s}')
    for g in summary:
        print(f'{str(g["shape"]):10s} {str(g["source_kind"]):11s} {g["controller"]:6s} '
              f'{g["stance"]:7s} {g["layer"]:11s} {g["executed"]:5d} '
              f'{g["precheck_failed"]:4d} {g["error"]:4d} {g["contact_any"]:4d} '
              f'{g["contact_wheel"]:6d} {g["completed"]:5d}')
    return 0 if complete else 1


if __name__ == '__main__':
    sys.exit(main())
