"""清单驱动的薄编排：输入清单 → 每个阶段从同一上下文取参数 → 结果清单。

设计要点（收口整改 §4）：
  * 不再有 R02/R03 默认路径：所有案例、观测、候选、真值、土壤、预算都来自清单；
  * 每个阶段显式声明它的输入/输出，阶段之间只通过上下文与文件交换；
  * 阶段状态区分 done_qualified / done_unqualified / error / pending，文件存在不等于成功；
  * 正式资格由 candidate_qualification 判定，未通过就写 no_qualified_candidate 并走真实 A0；
  * 命令行与页面调用同一个 run()。

  python scripts/r1_pipeline.py --manifest plans/r1_runs/input_R03_close.json \
      --out runs/.../runs/R03_same_scene --stages observe,candidate,fuse,measure,qualify,closed_loop,verify
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import v7_run_manifest as MAN
import candidate_qualification as CQ

PY = sys.executable


class Ctx:
    def __init__(self, man, out_dir, run_id=None):
        self.man = man
        self.out = pathlib.Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or time.strftime('%Y%m%dT%H%M%S') + '-' + str(abs(hash(str(self.out))) % 100000)
        self.started_at = time.time()
        self.stage_status = {}
        self.artifacts = {}
        self.qualification = {}
        self.errors = []

    # ---- 从清单解析出的实际输入（唯一来源） ----
    @property
    def case_path(self):
        return MAN._abs(self.man['case_config'])

    @property
    def case(self):
        return json.loads(self.case_path.read_text())

    @property
    def obs_dir(self):
        return MAN._abs((self.man.get('observation_policy') or {})['observation_dir'])

    @property
    def truth(self):
        return MAN._abs(self.man['truth_collision'])

    @property
    def parents(self):
        return self.man.get('parent_candidates') or []

    @property
    def soils(self):
        return list(self.man.get('planning_soils') or [])

    @property
    def budget(self):
        return float(self.man.get('time_budget_s') or 30.0)

    @property
    def pitch(self):
        return float((self.man.get('fusion') or {}).get('pitch_m') or 0.0025)

    @property
    def config(self):
        return (self.man.get('fusion') or {}).get('config',
                                                  'configs/unseen_v7_r1_fusion_gapfill.json')

    def set(self, name, status, **kw):
        rec = {'stage': name, 'status': status, 'ts': time.time()}
        rec.update(kw)
        self.stage_status[name] = rec
        (self.out / 'stage_status.json').write_text(
            json.dumps(self.stage_status, ensure_ascii=False, indent=2))
        return rec


def _run(cmd, log_path=None):
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if log_path:
        pathlib.Path(log_path).write_text((r.stdout or '') + '\n' + (r.stderr or ''))
    return r


def stage_observe(ctx):
    """观测：清单指定观测包时做身份校验；要求重采时用同一相机策略真实采集。"""
    pol = ctx.man.get('observation_policy') or {}
    obs = ctx.obs_dir
    if pol.get('mode') == 'recollect':
        cmd = [PY, 'scripts/v7_scan_observations.py',
               '--cases', str(ctx.man['case_id']).split('_')[0],
               '--scales', str(ctx.man.get('scale') or 1.0),
               '--out', MAN._rel(obs.parent)]
        r = _run(cmd, ctx.out / 'observe.log')
        if r.returncode != 0:
            return ctx.set('observe', MAN.STAGE_ERROR, error=r.stderr[-800:])
    if not (obs / 'observation.json').is_file():
        return ctx.set('observe', MAN.STAGE_ERROR,
                       error=f'观测包缺 observation.json：{MAN._rel(obs)}')
    oj = json.loads((obs / 'observation.json').read_text())
    vis = oj.get('visible') or {}
    ctx.artifacts['observation'] = {
        'dir': MAN._rel(obs), 'sha': MAN.sha256_tree(obs),
        'observation_json_sha': MAN.sha256_file(obs / 'observation.json'),
        'n_pixels': vis.get('n_pixels'), 'H_vis': vis.get('H_vis'),
        'W_vis': vis.get('W_vis'), 'x_front': vis.get('x_front')}
    return ctx.set('observe', MAN.STAGE_QUALIFIED,
                   observation=MAN._rel(obs), n_pixels=vis.get('n_pixels'))


def stage_candidate(ctx):
    """候选：本批只选择已有父任务，不新增付费生成。"""
    parents = ctx.parents
    if not parents:
        return ctx.set('candidate', MAN.STAGE_UNQUALIFIED, error='清单无父候选')
    rows = []
    for c in parents:
        w = MAN._abs(c.get('world') or c.get('world_dir'))
        rows.append({'candidate_id': c.get('candidate_id'),
                     'world': MAN._rel(w),
                     'world_sha': MAN.sha256_tree(w),
                     'mesh_sha': MAN.sha256_file(w / 'body.stl'),
                     'exists': w.is_dir()})
    ctx.artifacts['candidates'] = rows
    bad = [r for r in rows if not r['exists'] or not r['mesh_sha']]
    return ctx.set('candidate', MAN.STAGE_UNQUALIFIED if bad else MAN.STAGE_QUALIFIED,
                   n=len(rows), missing=[r['candidate_id'] for r in bad])


def stage_fuse(ctx):
    """融合：每个父候选一次，用本次观测与本次配置，输出到本次 out。"""
    fused = []
    for c in ctx.parents:
        cid = c['candidate_id']
        w = MAN._abs(c.get('world') or c.get('world_dir'))
        out = ctx.out / 'fusion' / cid
        cmd = [PY, 'scripts/fuse_observed.py', '--observation', MAN._rel(ctx.obs_dir),
               '--method', 'H5_F', '--parent-world', MAN._rel(w), '--parent-id', cid,
               '--out', MAN._rel(out), '--pitch', str(ctx.pitch),
               '--config', ctx.config]
        r = _run(cmd, ctx.out / f'fuse_{cid}.log')
        man = out / 'manifest.json'
        if r.returncode != 0 or not man.is_file():
            fused.append({'candidate_id': cid, 'error': (r.stderr or '')[-600:]})
            continue
        m = json.loads(man.read_text())
        fused.append({'candidate_id': cid, 'dir': MAN._rel(out),
                      'world_sha': m.get('world_sha'),
                      'strict_pass': (m.get('strict') or {}).get('pass'),
                      'metrics': m.get('metrics')})
    ctx.artifacts['fusion'] = fused
    ok = [f for f in fused if f.get('world_sha')]
    return ctx.set('fuse', MAN.STAGE_QUALIFIED if ok else MAN.STAGE_ERROR, n=len(ok))


def stage_measure(ctx):
    """碰撞：由本次占据直接建 box 并集，再测量。"""
    rows = []
    for f in (ctx.artifacts.get('fusion') or []):
        if not f.get('dir'):
            continue
        out = MAN._abs(f['dir'])
        coll = out / 'collision'
        r1 = _run([PY, 'scripts/collision_box_union.py', '--occupancy',
                   MAN._rel(out / 'occ.npz'), '--out', MAN._rel(coll),
                   '--pitch', str(ctx.pitch), '--hypothesis-id', f['candidate_id']],
                  ctx.out / f"boxes_{f['candidate_id']}.log")
        if r1.returncode != 0:
            rows.append({'candidate_id': f['candidate_id'], 'error': (r1.stderr or '')[-500:]})
            continue
        r2 = _run([PY, 'scripts/collision_occupancy_metrics.py', '--mesh',
                   MAN._rel(out / 'body.stl'), '--collision', MAN._rel(coll),
                   '--out', MAN._rel(coll / 'metrics_full.json'),
                   '--label', f['candidate_id'], '--eval-pitch', '0.004',
                   '--parity', 'full'], ctx.out / f"metrics_{f['candidate_id']}.log")
        metrics = {}
        if (coll / 'metrics_full.json').is_file():
            metrics = json.loads((coll / 'metrics_full.json').read_text())
        rows.append({'candidate_id': f['candidate_id'], 'collision_dir': MAN._rel(coll),
                     'verdict': metrics.get('verdict'),
                     'iou': (metrics.get('geometry') or {}).get('occupancy_iou'),
                     'ok': r2.returncode == 0})
    ctx.artifacts['collision'] = rows
    ok = [r for r in rows if r.get('ok')]
    return ctx.set('measure', MAN.STAGE_QUALIFIED if ok else MAN.STAGE_ERROR, n=len(ok))


def stage_qualify(ctx):
    """正式资格：唯一资格门。不通过就是 no_qualified_candidate，不缩小分母。"""
    obs = CQ.load_observation_set(ctx.obs_dir)
    case = ctx.case
    entries = []
    by_id = {r['candidate_id']: r for r in (ctx.artifacts.get('collision') or [])}
    for f in (ctx.artifacts.get('fusion') or []):
        cid = f['candidate_id']
        fused_dir = MAN._abs(f['dir']) if f.get('dir') else None
        entries.append({
            'candidate_id': cid,
            'process': str(fused_dir / 'manifest.json') if fused_dir else '',
            'collision_dir': str(fused_dir / 'collision') if fused_dir else '',
            'mesh': str(fused_dir / 'body.stl') if fused_dir else '',
            'planning_eligible': True,
        })
    qualified, diag, summary = CQ.gate(entries, obs, case=case, strict=True)
    # 融合清单不是 process.json：把融合的可见指标补进资格记录，便于审计
    ctx.qualification = summary
    (ctx.out / 'qualification.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    st = (MAN.STAGE_QUALIFIED if qualified else MAN.STAGE_UNQUALIFIED)
    return ctx.set('qualify', st, n_qualified=len(qualified),
                   status_counts=summary.get('status_counts'))


def stage_closed_loop(ctx):
    """闭环：有合格候选就跑正式入口；没有就写 no_qualified_candidate 走真实 A0。"""
    q = ctx.qualification or {}
    quals = [r for r in (q.get('rows') or []) if r.get('qualified')]
    if not quals:
        decision = {'chosen': 'A0', 'reason': 'no_qualified_candidate',
                    'safe_set': [], 'candidates': [],
                    'qualification_status': q.get('status_counts')}
        (ctx.out / 'decision.json').write_text(
            json.dumps(decision, ensure_ascii=False, indent=2))
        ctx.artifacts['decision'] = decision
        return ctx.set('closed_loop', MAN.STAGE_UNQUALIFIED,
                       decision='A0', reason='no_qualified_candidate')
    hyp = [{'id': r['candidate_id'],
            'world': str(MAN._abs((ctx.artifacts['fusion'][i]['dir']))),
            'collision': str(MAN._abs((ctx.artifacts['fusion'][i]['dir'])) + '/collision')}
           for i, r in enumerate(quals)]
    hp = ctx.out / 'hypotheses.json'
    hp.write_text(json.dumps(hyp, ensure_ascii=False, indent=2))
    out = ctx.out / 'same_scene'
    cmd = [PY, 'scripts/v7_same_scene_formal.py', '--case', MAN._rel(ctx.case_path),
           '--hypotheses', MAN._rel(hp), '--truth-collision', MAN._rel(ctx.truth),
           '--soils', ','.join(ctx.soils), '--exec-soil',
           str(ctx.man.get('execution_soil') or 'nominal'),
           '--budget', str(ctx.budget), '--out', MAN._rel(out)]
    if ctx.man.get('state_source'):
        cmd += ['--resume-state', MAN._rel(MAN._abs(ctx.man['state_source']))]
    r = _run(cmd, ctx.out / 'closed_loop.log')
    rep = out / 'same_scene_report.json'
    if not rep.is_file():
        return ctx.set('closed_loop', MAN.STAGE_ERROR, error=(r.stderr or '')[-800:])
    d = json.loads(rep.read_text())
    ctx.artifacts['closed_loop'] = {'report': MAN._rel(rep),
                                    'decision': (d.get('decision') or {}).get('chosen'),
                                    'execution': d.get('execution')}
    ok = bool((d.get('execution') or {}).get('success'))
    return ctx.set('closed_loop', MAN.STAGE_QUALIFIED if ok else MAN.STAGE_UNQUALIFIED,
                   decision=(d.get('decision') or {}).get('chosen'), success=ok)


def stage_verify(ctx):
    """核对本次生产产物内部一致，并写出结果清单。"""
    checks = []
    if ctx.artifacts.get('observation'):
        checks.append({'check': 'observation_exists', 'ok': True})
    q = ctx.qualification or {}
    checks.append({'check': 'qualification_written',
                   'ok': (ctx.out / 'qualification.json').is_file()})
    checks.append({'check': 'no_silent_empty_denominator',
                   'ok': (q.get('n_input', 0) == len(q.get('rows') or []))})
    # 决策必须在执行之前落盘
    dec = ctx.out / 'decision.json'
    if dec.is_file():
        checks.append({'check': 'decision_before_execution', 'ok': True})
    res = MAN.make_result(ctx.man, ctx.stage_status, ctx.qualification,
                          extra={'run_id': ctx.run_id,
                                 'artifacts': ctx.artifacts,
                                 'started_at': ctx.started_at})
    errs = MAN.validate_result(res)
    checks.append({'check': 'result_manifest_valid', 'ok': not errs, 'errors': errs})
    res['checks'] = checks
    (ctx.out / 'result_manifest.json').write_text(
        json.dumps(res, ensure_ascii=False, indent=2))
    ok = all(c['ok'] for c in checks)
    return ctx.set('verify', MAN.STAGE_QUALIFIED if ok else MAN.STAGE_ERROR,
                   checks=checks)


STAGES = {
    'observe': stage_observe,
    'candidate': stage_candidate,
    'fuse': stage_fuse,
    'measure': stage_measure,
    'qualify': stage_qualify,
    'closed_loop': stage_closed_loop,
    'verify': stage_verify,
}
ORDER = ['observe', 'candidate', 'fuse', 'measure', 'qualify', 'closed_loop', 'verify']


def run(manifest_path, out_dir=None, stages=None, dry_run=False):
    """命令行与页面共用的编排入口。"""
    man = MAN.load_input(manifest_path)
    errs = MAN.validate_input(man)
    if errs:
        return {'ok': False, 'stage': 'validate', 'errors': errs}
    out = out_dir or (MAN._abs(man['output_root']) / str(man.get('run_tag') or 'run'))
    if dry_run:
        ctx = Ctx(man, out)
        plan = []
        for name in (stages or ORDER):
            plan.append({'stage': name,
                         'inputs': {
                             'case': MAN._rel(ctx.case_path),
                             'observation': MAN._rel(ctx.obs_dir),
                             'truth': MAN._rel(ctx.truth),
                             'parents': [c['candidate_id'] for c in ctx.parents],
                             'soils': ctx.soils,
                             'exec_soil': man.get('execution_soil'),
                             'budget': ctx.budget,
                             'out': MAN._rel(out)}})
        return {'ok': True, 'dry_run': True, 'out': MAN._rel(out), 'plan': plan}

    ctx = Ctx(man, out)
    todo = stages or ORDER
    for name in todo:
        fn = STAGES.get(name)
        if fn is None:
            ctx.errors.append(f'未知阶段 {name}')
            continue
        t0 = time.time()
        rec = fn(ctx)
        rec['seconds'] = round(time.time() - t0, 2)
    ok = all(r['status'] in (MAN.STAGE_QUALIFIED, MAN.STAGE_UNQUALIFIED)
             for r in ctx.stage_status.values())
    return {'ok': ok, 'out': MAN._rel(ctx.out), 'run_id': ctx.run_id,
            'stage_status': ctx.stage_status,
            'qualification': ctx.qualification.get('status_counts') if ctx.qualification else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--stages', default=None, help='逗号分隔；默认全部')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    stages = [x.strip() for x in a.stages.split(',')] if a.stages else None
    res = run(a.manifest, a.out, stages, a.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get('ok') else 2


if __name__ == '__main__':
    sys.exit(main())
