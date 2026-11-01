"""唯一正式资格门（本批第一件工件）。

所有生产入口（六方法比较、闭环、清单入口、网页、演示包）都必须调用这里的
`qualify_candidate`，不允许各自用 `planning_eligible=true` 或单独一个碰撞 PASS
就当作合格。

正式资格 = 五个条件的合取：

  1. files_complete       实际要加载的资产、占据、清单存在且可读
  2. source_identity_ok   测量的源实体就是实际将使用的实体（完整 SHA256 相等）
  3. observation_match_ok 测量针对本次案例、本次尺寸、本次观测
  4. visible_pass         冻结的 IoU / 可见点 P95 / 自由空间三项全过
  5. collision_pass       占据 IoU / 双向表面距离 / 有效测量全过

向外分别表达四个字段：measurement_valid、collision_pass、visible_pass、qualified。
`status` 取值为 measured/not_measured/measurement_error 与
qualified/disqualified 的组合语义，见 STATUS_*。

用法：
  python scripts/candidate_qualification.py --candidate V7_R01_s1 \
      --observation runs/.../scan_obs/R01_s1 --case cases/unseen_v1/R01.json --out q.json
"""
import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

QUALIFY_SCHEMA = 'candidate-qualification/v2'

# 阈值在重评之前固定；不按候选结果调整。继承的正式协议若有更严门槛，以更严者为准。
THRESHOLDS = {
    'visible_iou_min': 0.85,
    'vis_pt_p95_mm_base': 5.0,
    'vis_pt_p95_h_frac': 0.03,
    'freespace_max': 0.05,
    'collision_iou_min': 0.95,
    'surface_p95_mm_max': 5.0,
}

STATUS_QUALIFIED = 'qualified'
STATUS_DISQUALIFIED = 'disqualified'
STATUS_NOT_MEASURED = 'not_measured'
STATUS_MEASUREMENT_ERROR = 'measurement_error'


def sha256_file(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(p):
    """目录身份：稳定的相对路径排序 + 每个文件内容哈希。"""
    p = pathlib.Path(p)
    if not p.is_dir():
        return None
    h = hashlib.sha256()
    for f in sorted((x for x in p.rglob('*') if x.is_file()),
                    key=lambda x: str(x.relative_to(p)).replace('\\', '/')):
        h.update(str(f.relative_to(p)).replace('\\', '/').encode())
        h.update(b'\0')
        h.update((sha256_file(f) or '').encode())
        h.update(b'\n')
    return h.hexdigest()


def _rel(p):
    p = pathlib.Path(p)
    if str(p) in ('', '.'):
        return None
    try:
        return str(p.resolve().relative_to(ROOT))
    except Exception:
        return str(p)


def _norm(p):
    """把仓库内相对路径规范化成可比较的形式。"""
    if p is None:
        return None
    s = str(p).strip()
    if not s:
        return None
    q = pathlib.Path(s)
    if q.is_absolute():
        try:
            return str(q.resolve().relative_to(ROOT))
        except Exception:
            # 另一台机器上的绝对路径：取 runs/ 之后的仓库相对部分
            for marker in ('/runs/', '/cases/', '/demo/'):
                if marker in s:
                    tail = s.split(marker, 1)[1]
                    return (marker.strip('/') + '/' + tail) if marker != '/runs/' else 'runs/' + tail
            return str(q)
    return str(q)


def _num(d, *keys):
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def load_observation_set(observation_dir):
    """把一次观测目录解析成资格门需要的观察集合身份。"""
    d = pathlib.Path(observation_dir)
    obs_json = d / 'observation.json'
    rec = {
        'observation_dir': _norm(d),
        'observation_sha': sha256_file(obs_json),
        'views': [],
        'exists': obs_json.is_file(),
    }
    if obs_json.is_file():
        try:
            oj = json.loads(obs_json.read_text())
        except Exception:
            oj = {}
        rec['views'] = list(oj.get('views') or oj.get('view_ids') or [])
        rec['n_views'] = len(rec['views']) or int(oj.get('n_views') or 1)
        rec['visible'] = oj.get('visible') or {}
    return rec


def _find_metrics(collision_dir):
    """碰撞测量文件：优先取**有效测量**，其次按新旧顺序回退。

    同一目录可能同时存在旧格式（无 measurement_validity）与新测量；
    直接按文件名取第一个会把有效测量挡住，本批已实测到该缺陷。
    """
    d = pathlib.Path(collision_dir)
    names = ('metrics_full.json', 'metrics_occ.json', 'metrics_single.json',
             'metrics_v2.json', 'metrics.json')
    found = []
    for name in names:
        p = d / name
        if p.is_file():
            try:
                found.append((json.loads(p.read_text()), p))
            except Exception:
                found.append((None, p))
    for obj, p in found:
        if obj and (obj.get('measurement_validity') or {}).get('valid'):
            return obj, p
    return (found[0] if found else (None, None))


def qualify_candidate(candidate, observation_set, case=None, strict=True):
    """返回结构化资格结果。candidate 至少含 candidate_id / process / collision_dir。

    任何输入缺失都变成明确的 status，而不是静默通过或静默删除分母。
    """
    cid = (candidate or {}).get('candidate_id') or (candidate or {}).get('id') or 'unknown'
    reasons = []
    out = {
        'schema': QUALIFY_SCHEMA,
        'candidate_id': cid,
        'strict': bool(strict),
        'thresholds': dict(THRESHOLDS),
        'measurement_valid': False,
        'collision_pass': False,
        'visible_pass': False,
        'source_identity_ok': False,
        'observation_match_ok': False,
        'files_complete': False,
        'qualified': False,
        'status': STATUS_NOT_MEASURED,
        'reasons': reasons,
        'diag_mode': not strict,
    }

    process_path = pathlib.Path(candidate.get('process') or '')
    collision_dir = pathlib.Path(candidate.get('collision_dir') or '')
    mesh_path = pathlib.Path(candidate.get('mesh') or '')

    # ---- 1 files_complete -------------------------------------------------
    missing = []
    if not process_path.is_file():
        missing.append(f'process.json 缺: {_rel(process_path)}')
    if not collision_dir.is_dir():
        missing.append(f'碰撞目录缺: {_rel(collision_dir)}')
    if not mesh_path.is_file():
        missing.append(f'源网格缺: {_rel(mesh_path)}')
    metrics, metrics_path = _find_metrics(collision_dir) if collision_dir.is_dir() else (None, None)
    if metrics is None:
        missing.append(f'碰撞测量缺: {_rel(collision_dir)}/metrics_*.json')
    out['files_complete'] = not missing
    if missing:
        reasons.extend(missing)
        out['status'] = STATUS_NOT_MEASURED
        return out

    proc = json.loads(process_path.read_text())
    # 两种记录格式都必须支持：旧 process.json（fusion_metrics/observation/
    # fusion_world_sha）与本批 fuse_observed 的 manifest.json（metrics/
    # inputs.observation/world_sha）。归一化后走同一套判定。
    if 'fusion_metrics' not in proc and 'metrics' in proc:
        _in = proc.get('inputs') or {}
        proc = {
            'schema': proc.get('schema'),
            'candidate': proc.get('parent_id'),
            'observation': _in.get('observation'),
            'fusion_world_sha': proc.get('world_sha'),
            'fusion_metrics': proc.get('metrics') or {},
            'fusion_strict': proc.get('strict') or {},
            'case_id': proc.get('case_id'),
            '_source_format': 'fused-asset/v2',
        }
    else:
        proc.setdefault('_source_format', 'v7-candidate-process/v1')

    # ---- 2 source_identity_ok --------------------------------------------
    mesh_sha = sha256_file(mesh_path)
    cand_sha = metrics.get('source_sha')
    fusion_sha = proc.get('fusion_world_sha')
    identity_reasons = []
    if not mesh_sha:
        identity_reasons.append('源网格无法计算 SHA')
    if not cand_sha:
        identity_reasons.append('碰撞测量未记录 source_sha')
    elif len(str(cand_sha)) != 64:
        identity_reasons.append(f'碰撞测量 source_sha 不是完整 SHA256（{len(str(cand_sha))} 位）')
    if not fusion_sha:
        identity_reasons.append('process.json 未记录 fusion_world_sha')
    elif len(str(fusion_sha)) != 64:
        identity_reasons.append(f'fusion_world_sha 不是完整 SHA256（{len(str(fusion_sha))} 位）')
    if mesh_sha and cand_sha and str(cand_sha).lower() != mesh_sha.lower():
        identity_reasons.append('碰撞测量的源实体与实际加载网格 SHA 不符')
    if mesh_sha and fusion_sha and str(fusion_sha).lower() != mesh_sha.lower():
        identity_reasons.append('process 记录的融合实体与实际网格 SHA 不符')
    # 碰撞清单身份：metrics 记录的 manifest 内容 SHA 必须与当前清单一致
    man_path = collision_dir / 'manifest.json'
    man = json.loads(man_path.read_text()) if man_path.is_file() else {}
    man_content = (man.get('collision_sha') or man.get('content_sha')
                   or (man.get('identity') or {}).get('collision_sha'))
    rec_man = metrics.get('collision_sha_manifest')
    if man_content and rec_man and not str(man_content).startswith(str(rec_man)[:16]):
        identity_reasons.append('碰撞清单内容 SHA 与测量时记录的清单 SHA 不符')
    out['source_identity_ok'] = not identity_reasons
    out['identity'] = {
        'mesh_sha256': mesh_sha,
        'metrics_source_sha': cand_sha,
        'process_fusion_world_sha': fusion_sha,
        'collision_manifest_sha': man_content,
        'metrics_manifest_sha': rec_man,
    }
    reasons.extend(identity_reasons)

    # ---- 3 observation_match_ok ------------------------------------------
    proc_obs = _norm(proc.get('observation'))
    cur_obs = _norm(observation_set.get('observation_dir'))
    obs_reasons = []
    if not observation_set.get('exists', True):
        obs_reasons.append('本次观测目录或缺 observation.json')
    if not proc_obs:
        obs_reasons.append('process.json 未记录测量所用观测')
    elif cur_obs and proc_obs != cur_obs:
        obs_reasons.append(f'测量针对的观测是 {proc_obs}，本次案例观测是 {cur_obs}')
    # 案例/尺度绑定：若候选或调用方声明了案例，必须与本次一致
    want_case = (case or {}).get('case_id')
    proc_case = proc.get('case_id') or (proc.get('observation_set') or {}).get('case_id')
    if want_case and proc_case and proc_case != want_case:
        obs_reasons.append(f'候选测量来自案例 {proc_case}，本次是 {want_case}')
    out['observation_match_ok'] = not obs_reasons
    out['observation'] = {
        'process_observation': proc_obs,
        'current_observation': cur_obs,
        'current_observation_sha': observation_set.get('observation_sha'),
        'case_id': want_case,
        'process_case_id': proc_case,
    }
    reasons.extend(obs_reasons)

    # ---- 4 visible_pass ---------------------------------------------------
    fm = proc.get('fusion_metrics') or {}
    h_vis = _num(proc.get('fusion_strict') or {}, 'h_vis_m')
    if h_vis is None:
        h_vis = _num(observation_set.get('visible') or {}, 'H_vis')
    p95_limit = THRESHOLDS['vis_pt_p95_mm_base']
    if h_vis:
        p95_limit = max(p95_limit, THRESHOLDS['vis_pt_p95_h_frac'] * float(h_vis) * 1000.0)
    iou = _num(fm, 'mask_iou', 'iou')
    p95 = _num(fm, 'vis_pt_p95_mm', 'vis_pt_p95')
    free = _num(fm, 'freespace_violation', 'freespace')
    vis_reasons = []
    if iou is None:
        vis_reasons.append('缺可见 IoU')
    elif iou < THRESHOLDS['visible_iou_min']:
        vis_reasons.append(f'可见 IoU {iou:.4f} < {THRESHOLDS["visible_iou_min"]}')
    if p95 is None:
        vis_reasons.append('缺可见点 P95')
    elif p95 > p95_limit:
        vis_reasons.append(f'可见点 P95 {p95:.3f} mm > {p95_limit:.3f} mm')
    if free is None:
        vis_reasons.append('缺自由空间违规率')
    elif free > THRESHOLDS['freespace_max']:
        vis_reasons.append(f'自由空间违规 {free:.4f} > {THRESHOLDS["freespace_max"]}')
    out['visible_pass'] = not vis_reasons
    out['visible_metrics'] = {'mask_iou': iou, 'vis_pt_p95_mm': p95,
                              'freespace_violation': free,
                              'p95_limit_mm': round(p95_limit, 3),
                              'h_vis_m': h_vis}
    reasons.extend(vis_reasons)

    # ---- 5 collision_pass -------------------------------------------------
    validity = metrics.get('measurement_validity') or {}
    geo = metrics.get('geometry') or {}
    # 表面距离：现行测量把双向 P95 放在 geometry.*_mm.p95（嵌套），旧版放平铺字段
    surface = metrics.get('surface') or metrics.get('surface_mm') or {}
    s2c = _num(surface, 'source_to_collision_p95_mm', 's2c_p95_mm')
    c2s = _num(surface, 'collision_to_source_p95_mm', 'c2s_p95_mm')
    if s2c is None:
        s2c = _num(geo.get('source_to_collision_mm') or {}, 'p95')
    if c2s is None:
        c2s = _num(geo.get('collision_to_source_mm') or {}, 'p95')
    if s2c is None:
        s2c = _num(metrics.get('probe') or {}, 'source_to_collision_p95_mm')
    if c2s is None:
        c2s = _num(metrics.get('probe') or {}, 'collision_to_source_p95_mm')
    c_iou = _num(geo, 'occupancy_iou')
    col_reasons = []
    if not validity.get('valid'):
        col_reasons.append('碰撞测量无效（measurement_validity.valid 非真）')
    out['measurement_valid'] = bool(validity.get('valid'))
    if c_iou is None:
        col_reasons.append('缺占据 IoU')
    elif c_iou < THRESHOLDS['collision_iou_min']:
        col_reasons.append(f'占据 IoU {c_iou:.4f} < {THRESHOLDS["collision_iou_min"]}')
    if s2c is None or c2s is None:
        col_reasons.append('缺双向表面距离 P95')
    else:
        if s2c > THRESHOLDS['surface_p95_mm_max']:
            col_reasons.append(f'源→碰撞 P95 {s2c:.3f} mm > {THRESHOLDS["surface_p95_mm_max"]}')
        if c2s > THRESHOLDS['surface_p95_mm_max']:
            col_reasons.append(f'碰撞→源 P95 {c2s:.3f} mm > {THRESHOLDS["surface_p95_mm_max"]}')
    verdict = str(metrics.get('verdict') or '').upper()
    if verdict and verdict != 'PASS':
        col_reasons.append(f'碰撞判定为 {verdict}')
    out['collision_pass'] = not col_reasons
    out['collision_metrics'] = {'occupancy_iou': c_iou,
                                'source_to_collision_p95_mm': s2c,
                                'collision_to_source_p95_mm': c2s,
                                'verdict': verdict,
                                'measurement_valid': out['measurement_valid'],
                                'file': _rel(metrics_path)}
    reasons.extend(col_reasons)

    # ---- 合成 -------------------------------------------------------------
    out['qualified'] = bool(out['files_complete'] and out['source_identity_ok']
                            and out['observation_match_ok']
                            and out['visible_pass'] and out['collision_pass'])
    if out['qualified']:
        out['status'] = STATUS_QUALIFIED
    elif not out['measurement_valid']:
        out['status'] = STATUS_MEASUREMENT_ERROR
    else:
        out['status'] = STATUS_DISQUALIFIED
    out['collision_dir'] = _rel(collision_dir)
    out['mesh'] = _rel(mesh_path)
    out['claims'] = {'planning_eligible_in_manifest': bool(candidate.get('planning_eligible'))}
    if candidate.get('planning_eligible') and not out['qualified']:
        reasons.append('清单声称 planning_eligible=true，被资格门拒绝')
    return out



def record_from_two_view(asset_dir):
    """从两视角占据派生的资产生成资格门可读的记录。

    这类资产没有 process.json：可见指标记在 visible_two_view.json（逐视角），
    身份记在 two_view_report.json。这里只做**格式归一**，不新造任何数值。
    """
    d = pathlib.Path(asset_dir)
    rep = json.loads((d / 'two_view_report.json').read_text())
    vis = json.loads((d / 'visible_two_view.json').read_text())
    obs1 = vis.get('obs1') or {}
    views = [rep.get('obs1'), rep.get('obs2')]
    rec = {
        'schema': 'two-view-candidate-record/v1',
        'candidate': rep.get('parent_id'),
        'observation': rep.get('obs1'),
        'observation_views': views,
        'fusion_world_sha': sha256_file(d / 'body.stl'),
        'fusion_metrics': {'mask_iou': obs1.get('mask_iou'),
                           'vis_pt_p95_mm': obs1.get('vis_pt_p95_mm'),
                           'freespace_violation': obs1.get('freespace_violation')},
        'fusion_metrics_obs2': vis.get('obs2'),
        'fusion_strict': {'pass': bool(vis.get('both_views')),
                          'iou_min': THRESHOLDS['visible_iou_min'],
                          'freespace_max': THRESHOLDS['freespace_max']},
        'collision_metrics_file': 'collision/metrics_occ.json',
        '_derived_from': [str(d / 'two_view_report.json'), str(d / 'visible_two_view.json')],
        'note': ('两视角资产无 process.json；可见指标取 obs1（主视角），obs2 明细保留。'),
    }
    (d / 'candidate_record.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return d / 'candidate_record.json'


def gate(candidates, observation_set, case=None, strict=True, diag_ids=()):
    """对一个候选池做资格判定，返回 (qualified, diag, summary)。

    - qualified：正式可用候选（进正式表）
    - diag：显式诊断候选（标 DIAG，不进正式表）
    - summary：分母与状态统计，缺测/失败原因逐项列出
    """
    qualified, diag, rows = [], [], []
    for c in candidates or ():
        r = qualify_candidate(c, observation_set, case=case, strict=strict)
        rows.append(r)
        cid = r['candidate_id']
        if cid in diag_ids:
            r['diag_only'] = True
            diag.append({'candidate_id': cid, 'result': r})
        elif r['qualified']:
            qualified.append({'candidate_id': cid, 'result': r})
        else:
            diag.append({'candidate_id': cid, 'result': r})
    summary = {
        'n_input': len(rows),
        'n_qualified': len(qualified),
        'n_diag': len(diag),
        'status_counts': {},
        'no_qualified_candidate': not qualified,
        'rows': rows,
    }
    for r in rows:
        summary['status_counts'][r['status']] = summary['status_counts'].get(r['status'], 0) + 1
    return qualified, diag, summary


def _candidate_from_dir(cid, processed_root):
    """从 processed/<cid> 目录推断候选三件套路径。"""
    base = pathlib.Path(processed_root) / cid
    return {
        'candidate_id': cid,
        'process': str(base / 'process.json'),
        'collision_dir': str(base / 'collision'),
        'mesh': str(base / 'fusion' / 'body.stl'),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--processed-root',
                    default='runs/unseen/delivery_v7/v7_20261030/processed')
    ap.add_argument('--collision-dir', default=None)
    ap.add_argument('--mesh', default=None)
    ap.add_argument('--process', default=None)
    ap.add_argument('--observation', required=True)
    ap.add_argument('--case', default=None)
    ap.add_argument('--diag', action='store_true', help='显式诊断模式：不进入正式表')
    ap.add_argument('--two-view', default=None,
                    help='两视角资产目录：从报告归一生成记录再判定')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    if a.two_view:
        d = ROOT / a.two_view if not pathlib.Path(a.two_view).is_absolute() else pathlib.Path(a.two_view)
        proc = record_from_two_view(d)
        cand = {'candidate_id': json.loads(proc.read_text())['candidate'],
                'process': str(proc), 'collision_dir': str(d / 'collision'),
                'mesh': str(d / 'body.stl')}
    else:
        cand = _candidate_from_dir(a.candidate, ROOT / a.processed_root)
    if a.collision_dir:
        cand['collision_dir'] = str(ROOT / a.collision_dir) if not pathlib.Path(a.collision_dir).is_absolute() else a.collision_dir
    if a.mesh:
        cand['mesh'] = str(ROOT / a.mesh) if not pathlib.Path(a.mesh).is_absolute() else a.mesh
    if a.process:
        cand['process'] = str(ROOT / a.process) if not pathlib.Path(a.process).is_absolute() else a.process
    obs = load_observation_set(ROOT / a.observation if not pathlib.Path(a.observation).is_absolute() else a.observation)
    case = json.loads((ROOT / a.case).read_text()) if a.case else None
    res = qualify_candidate(cand, obs, case=case, strict=not a.diag)
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        p = ROOT / a.out
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    print(text)
    return 0 if res['qualified'] else 3


if __name__ == '__main__':
    sys.exit(main())
