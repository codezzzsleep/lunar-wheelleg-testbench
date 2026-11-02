"""Nominal-soil main table, reusing the already-fused 5-point assets.

The 5-point worst-case screen collapses the formal planner to A0 on most states
(including the truth reference), so the main comparison is run on the current
(nominal) soil, with the 5-point results kept as a sensitivity annex.

This does NOT re-fuse: it symlinks v3batch/<state>/<tag>/{fused,coll,parent}
into v3batch_nominal/<state>/<tag> and runs only the planner.

  python scripts/v2_nominal_table.py [--only multi,nonlux,table] [--workers 3]
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1'
SRC = RUN / 'v3batch'
DST = RUN / 'v3batch_nominal'
LOGS = DST / 'logs'
PY = sys.executable


def states():
    out = json.loads((RUN / 'v2_main_states.json').read_text())['selected']
    if 'P58|S2' not in out:
        out.append('P58|S2')
    return out


def key(s):
    return s.replace('|', '_')


def obs_for(s):
    rid, sid = s.split('|')
    for p in (RUN / 'grid' / rid / rid / sid / 'obs', RUN / 'v3extra' / rid / sid / 'obs'):
        if (p / 'observation.json').is_file():
            return p
    return None


def assets_for(s):
    rid, sid = s.split('|')
    for p in (RUN / 'grid' / rid / rid / sid, RUN / 'v3extra' / rid / sid):
        if p.is_dir():
            return p
    return None


def cands_for(s):
    k = key(s)
    for p in (RUN / 'v3gen' / k, RUN / 'gen_v2' / k):
        if (p / 'tasks.json').is_file():
            return p
    return None


def valid_tags(s):
    d = SRC / key(s)
    out = []
    for tag_dir in sorted(p for p in d.glob('*') if p.is_dir() and not p.name.endswith('_abl')):
        if (tag_dir / 'fused/manifest.json').is_file() \
                and (tag_dir / 'coll/manifest.json').is_file() \
                and (tag_dir / 'parent/body.stl').is_file():
            out.append(tag_dir.name)
    return out


def link_state(s):
    tags = valid_tags(s)
    dst = DST / key(s)
    for tag in tags:
        src = SRC / key(s) / tag
        d = dst / tag
        d.mkdir(parents=True, exist_ok=True)
        for name in ('fused', 'coll', 'parent', 'align_used.json'):
            target = src / name
            link = d / name
            if target.exists() and not link.exists():
                os.symlink(str(target), str(link))
    return tags


def run_pool(jobs, workers, phase):
    LOGS.mkdir(parents=True, exist_ok=True)
    pending = list(jobs)
    running = []
    rc = {}
    while pending or running:
        while pending and len(running) < workers:
            name, cmd = pending.pop(0)
            log = open(LOGS / f'{phase}_{name}.log', 'w')
            p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            running.append((name, p, log))
            print(f'[{phase}] start {name}', flush=True)
        time.sleep(5)
        still = []
        for name, p, log in running:
            code = p.poll()
            if code is None:
                still.append((name, p, log)); continue
            log.close(); rc[name] = code
            print(f'[{phase}] done {name} rc={code}', flush=True)
        running = still
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='multi,nonlux,table')
    ap.add_argument('--workers', type=int, default=3)
    a = ap.parse_args()
    phases = [x.strip() for x in a.only.split(',') if x.strip()]
    all_states = states()
    if 'multi' in phases:
        jobs = []
        for s in all_states:
            tags = link_state(s)
            if not tags:
                print(f'[multi] skip {s}: no valid fused assets', flush=True)
                continue
            if (DST / key(s) / 'multi.json').is_file():
                print(f'[multi] skip {s}: done', flush=True)
                continue
            obs, cands = obs_for(s), cands_for(s)
            if obs is None or cands is None:
                print(f'[multi] skip {s}: obs/cands missing', flush=True)
                continue
            rid, sid = s.split('|')
            jobs.append((key(s), [PY, 'scripts/v2_multi.py', '--rock', rid,
                                  '--state', sid,
                                  '--obs', str(obs.relative_to(ROOT)),
                                  '--cands', str(cands.relative_to(ROOT)),
                                  '--out', str((DST / key(s)).relative_to(ROOT)),
                                  '--soils', 'current', '--jobs', '1']))
        run_pool(jobs, a.workers, 'M')
    if 'nonlux' in phases:
        jobs = []
        for s in all_states:
            nd = DST / key(s) / 'nonlux.json'
            if nd.is_file():
                try:
                    if list(json.loads(nd.read_text()).get('planning_soils') or []) == ['nominal']:
                        continue
                except Exception:
                    pass
            obs, assets = obs_for(s), assets_for(s)
            if obs is None or assets is None:
                print(f'[nonlux] skip {s}: obs/assets missing', flush=True)
                continue
            rid, sid = s.split('|')
            jobs.append((key(s), [PY, 'scripts/v2_nonlux_rows.py', '--rock', rid,
                                  '--state', sid,
                                  '--obs', str(obs.relative_to(ROOT)),
                                  '--assets', str(assets.relative_to(ROOT)),
                                  '--out', str((DST / key(s)).relative_to(ROOT)),
                                  '--soils', 'nominal']))
        run_pool(jobs, a.workers, 'N')
    if 'table' in phases:
        subprocess.run([PY, 'scripts/v2_main_table.py',
                        '--states', str((RUN / 'v2_main_states.json').relative_to(ROOT)),
                        '--root', str(DST.relative_to(ROOT)),
                        '--out', str((RUN / 'v3table_nominal').relative_to(ROOT))],
                       cwd=str(ROOT), check=False)


if __name__ == '__main__':
    main()
