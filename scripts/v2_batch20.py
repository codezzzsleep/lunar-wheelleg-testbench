"""v2 20 状态八行主表批处理（沙箱内运行，可断点续跑）。

阶段：
  A 观测与既有几何资产：缺 obs 的石头跑 v7_rock_families --assets-only
  B 六候选生成：v2_gen_six（已有 6/6 的复用；记账在 runs/lux3d/ledger.jsonl）
  C Lux3D 融合/碰撞/预演 + 生成贡献消融：v2_multi --ablate --jobs 2
  D 非 Lux 六行（nominal）：v2_nonlux_rows
  E 聚合八行主表：v2_main_table

  python scripts/v2_batch20.py [--dry-run] [--only A,B,C,D,E]

所有子进程输出写到 v3batch/logs/<phase>_<state>.log。
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1'
GRID = RUN / 'grid'
EXTRA = RUN / 'v3extra'
GEN = RUN / 'v3gen'
BATCH = RUN / 'v3batch'
LOGS = BATCH / 'logs'
PY = sys.executable


def load_states():
    return json.loads((RUN / 'v2_main_states.json').read_text())['selected']


def split(state):
    rid, sid = state.split('|')
    return rid, sid


def obs_for(state):
    rid, sid = split(state)
    for p in (GRID / rid / rid / sid / 'obs', EXTRA / rid / sid / 'obs'):
        if (p / 'observation.json').is_file():
            return p
    return None


def assets_for(state):
    rid, sid = split(state)
    for p in (GRID / rid / rid / sid, EXTRA / rid / sid):
        if p.is_dir():
            return p
    return None


def cands_for(state):
    d = state.replace('|', '_')
    for p in (GEN / d, RUN / 'gen_v2' / d):
        tasks = p / 'tasks.json'
        raw = p / 'raw'
        if tasks.is_file() and raw.is_dir():
            return p
    return None


def gen_done(state):
    p = cands_for(state)
    if not p:
        return False
    try:
        j = json.loads((p / 'tasks.json').read_text())
        ts = j.get('tasks', [])
        if len(ts) < 6:
            return False
        # 已提交过（有 task_id）的失败是终态，不再重复付费；从未提交的并发失败要补
        return all(t.get('ok') or t.get('task_id') for t in ts)
    except Exception:
        return False


def multi_done(state):
    p = BATCH / state.replace('|', '_') / 'multi.json'
    if not p.is_file():
        return False
    try:
        j = json.loads(p.read_text())
        if list(j.get('planning_soils') or []) != ['p0', 'p1', 'p2', 'p3', 'p4']:
            return False
        rows = j.get('rows') or {}
        st = j.get('candidate_status') or {}
        ok = all((st.get(t) or {}).get('status') not in
                 ('align_failed', 'fusion_invalid', 'collision_invalid',
                  'align_failed_no_pose') for t in st)
        return ok and bool(rows.get('multi')) and (bool(rows.get('multi_ablation'))
                                                   or bool(rows.get('first_ablation')))
    except Exception:
        return False


def nonlux_done(state):
    p = BATCH / state.replace('|', '_') / 'nonlux.json'
    if not p.is_file():
        return False
    try:
        j = json.loads(p.read_text())
        rows = j.get('rows') or {}
        if list(j.get('planning_soils') or []) != ['p0', 'p1', 'p2', 'p3', 'p4']:
            return False
        return all((rows.get(k) or {}).get('status') == 'planned'
                   for k in ('B1_height', 'B2_F', 'B3_F', 'E25D_block',
                             'E25D_fill', 'U_truth'))
    except Exception:
        return False


def run_pool(jobs, max_workers, phase):
    """jobs: [(name, cmd)]；返回 {name: returncode}。"""
    LOGS.mkdir(parents=True, exist_ok=True)
    pending = list(jobs)
    running = []
    rc = {}
    while pending or running:
        while pending and len(running) < max_workers:
            name, cmd = pending.pop(0)
            log = open(LOGS / f'{phase}_{name}.log', 'w')
            p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log,
                                 stderr=subprocess.STDOUT)
            running.append((name, p, log))
            print(f'[{phase}] start {name}', flush=True)
        time.sleep(5)
        still = []
        for name, p, log in running:
            code = p.poll()
            if code is None:
                still.append((name, p, log))
                continue
            log.close()
            rc[name] = code
            print(f'[{phase}] done {name} rc={code}', flush=True)
        running = still
    return rc


def phase_a(states):
    need = {}
    for st in states:
        if obs_for(st) is None:
            rid, sid = split(st)
            need.setdefault(rid, []).append(sid)
    if not need:
        return {}
    jobs = []
    for rid, sids in need.items():
        jobs.append((rid, [PY, 'scripts/v7_rock_families.py', '--rocks', rid,
                           '--states', ','.join(sorted(sids)),
                           '--out', str(EXTRA.relative_to(ROOT)),
                           '--soils', 'nominal', '--assets-only']))
    return run_pool(jobs, min(4, len(jobs)), 'A')


def phase_b(states):
    jobs = []
    for st in states:
        if gen_done(st):
            continue
        rid, sid = split(st)
        obs = obs_for(st)
        if obs is None:
            print(f'[B] skip {st}: no obs', flush=True)
            continue
        d = GEN / st.replace('|', '_')
        jobs.append((st.replace('|', '_'),
                     [PY, 'scripts/v2_gen_six.py', '--obs', str(obs.relative_to(ROOT)),
                      '--rock', rid, '--state', sid,
                      '--out', str(d.relative_to(ROOT))]))
    return run_pool(jobs, min(3, len(jobs)) if jobs else 0, 'B')


def phase_c(states):
    jobs = []
    for st in states:
        if multi_done(st):
            continue
        obs, cands = obs_for(st), cands_for(st)
        if obs is None or cands is None:
            print(f'[C] skip {st}: obs={obs} cands={cands}', flush=True)
            continue
        rid, sid = split(st)
        d = BATCH / st.replace('|', '_')
        jobs.append((st.replace('|', '_'),
                     [PY, 'scripts/v2_multi.py', '--rock', rid, '--state', sid,
                      '--obs', str(obs.relative_to(ROOT)),
                      '--cands', str(cands.relative_to(ROOT)),
                      '--out', str(d.relative_to(ROOT)),
                      '--soils', 'points',
                      '--jobs', '2', '--ablate', '--ablate-first-only']))
    return run_pool(jobs, min(3, len(jobs)) if jobs else 0, 'C')


def phase_d(states):
    jobs = []
    for st in states:
        if nonlux_done(st):
            continue
        obs, assets = obs_for(st), assets_for(st)
        if obs is None or assets is None:
            print(f'[D] skip {st}: obs={obs} assets={assets}', flush=True)
            continue
        rid, sid = split(st)
        d = BATCH / st.replace('|', '_')
        jobs.append((st.replace('|', '_'),
                     [PY, 'scripts/v2_nonlux_rows.py', '--rock', rid,
                      '--state', sid, '--obs', str(obs.relative_to(ROOT)),
                      '--assets', str(assets.relative_to(ROOT)),
                      '--out', str(d.relative_to(ROOT)),
                      '--soils', 'p0,p1,p2,p3,p4']))
    return run_pool(jobs, min(2, len(jobs)) if jobs else 0, 'D')


def phase_e(states):
    cmd = [PY, 'scripts/v2_main_table.py',
           '--states', str((RUN / 'v2_main_states.json').relative_to(ROOT)),
           '--root', str(BATCH.relative_to(ROOT)),
           '--out', str((BATCH / 'table').relative_to(ROOT))]
    subprocess.run(cmd, cwd=str(ROOT), check=False)
    return {'table': 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only', default='A,B,C,D,E')
    a = ap.parse_args()
    states = load_states()
    phases = [p.strip() for p in a.only.split(',') if p.strip()]
    print(json.dumps({'states': states, 'phases': phases}, ensure_ascii=False))
    if a.dry_run:
        for st in states:
            print(json.dumps({'state': st, 'obs': str(obs_for(st)),
                              'assets': str(assets_for(st)),
                              'cands': str(cands_for(st)),
                              'multi_done': multi_done(st),
                              'nonlux_done': nonlux_done(st),
                              'gen_done': gen_done(st)}, ensure_ascii=False))
        return
    status = {}
    for ph in phases:
        fn = {'A': phase_a, 'B': phase_b, 'C': phase_c,
              'D': phase_d, 'E': phase_e}[ph]
        t0 = time.time()
        status[ph] = fn(states)
        print(f'phase {ph} done in {time.time()-t0:.0f}s', flush=True)
        (BATCH / 'batch_status.json').write_text(json.dumps(
            {'phases': list(phases), 'status': status, 'states': states},
            ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
