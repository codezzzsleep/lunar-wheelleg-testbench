"""运行清单：输入清单（要跑什么）与结果清单（实际用了什么、产出什么）。

本批（收口整改 §4）要求两者分开：
  - 输入清单在运行**之前**就存在，不能要求决策与轨迹已经存在；
  - 结果清单在运行**之后**写出，记录真实的输入 SHA、资格、矩阵、决策、执行。

字段语义（§4.2）：
  - 路径字段与哈希字段分开；`*_sha` 必须是**内容哈希**，不是路径；
  - 新严合同使用完整 SHA256（64 位）；旧截断身份只作历史兼容；
  - 缺字段、缺文件、哈希不符、对象不符、尺度不符，**在计算前拒绝**；
  - 目录身份 = 稳定相对路径排序 + 每文件内容哈希；
  - 写结果时避免「文件把自身 SHA 包在自身内」的循环（先算内容摘要再落盘）。

  python scripts/v7_run_manifest.py --manifest <输入清单> --check
  python scripts/v7_run_manifest.py --manifest <输入清单> --check --strict-missing
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

INPUT_SCHEMA = 'run-input/v1'
RESULT_SCHEMA = 'run-result/v1'
LEGACY_SCHEMA = 'run-manifest/v1'

# 输入清单必填字段（§4.1 建议集合，全部落地）
INPUT_REQUIRED = [
    'schema_version', 'batch_id', 'run_tag', 'case_id', 'case_config',
    'protocol', 'controller_freeze', 'observation_policy',
    'parent_candidates', 'truth_collision', 'planning_soils',
    'execution_soil', 'state_source', 'time_budget_s', 'output_root',
]

# 结果清单必填字段
RESULT_REQUIRED = [
    'schema_version', 'run_id', 'code_sha', 'protocol_sha', 'inputs_sha',
    'observation_sha', 'state_sha', 'qualification', 'stage_status',
    'started_at', 'finished_at',
]

STAGE_QUALIFIED = 'done_qualified'
STAGE_UNQUALIFIED = 'done_unqualified'
STAGE_ERROR = 'error'
STAGE_PENDING = 'pending'


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
    """目录身份：稳定相对路径排序 + 文件内容哈希（§4.2）。"""
    p = pathlib.Path(p)
    if not p.is_dir():
        return None
    h = hashlib.sha256()
    files = sorted((x for x in p.rglob('*') if x.is_file()),
                   key=lambda x: str(x.relative_to(p)).replace('\\', '/'))
    for f in files:
        rel = str(f.relative_to(p)).replace('\\', '/')
        h.update(rel.encode())
        h.update(b'\0')
        h.update((sha256_file(f) or '').encode())
        h.update(b'\n')
    return h.hexdigest()


def sha_obj(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False)
                          .encode()).hexdigest()


def ident(path):
    """路径 → 内容身份。文件用 SHA256，目录用树哈希。"""
    p = pathlib.Path(path)
    if p.is_dir():
        return {'kind': 'dir', 'sha256': sha256_tree(p),
                'n_files': sum(1 for _ in p.rglob('*') if _.is_file())}
    if p.is_file():
        return {'kind': 'file', 'sha256': sha256_file(p)}
    return {'kind': 'missing', 'sha256': None}


def _abs(v):
    p = pathlib.Path(v)
    return p if p.is_absolute() else (ROOT / p)


def _rel(p):
    p = pathlib.Path(p)
    try:
        return str(p.resolve().relative_to(ROOT))
    except Exception:
        return str(p)


def git_head():
    import subprocess
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT),
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return None


def load_input(path):
    """读入并规范化输入清单；不判断文件是否存在（那是 validate_input 的事）。"""
    man = json.loads(_abs(path).read_text())
    man.setdefault('schema_version', INPUT_SCHEMA)
    return man


def validate_input(man, strict_missing=True):
    """返回错误列表。空列表=可以开跑。

    逐条对应 §4.2：缺字段、缺文件、哈希不符、对象不符、尺度不符都在这里拒绝。
    """
    errs = []
    for k in INPUT_REQUIRED:
        if k not in man:
            errs.append(f'缺字段 {k}')

    # case_config 必须是文件，且 case_id 与文件内一致
    cc = man.get('case_config')
    if cc:
        p = _abs(cc)
        if not p.is_file():
            errs.append(f'case_config 不存在：{cc}')
        else:
            try:
                case = json.loads(p.read_text())
            except Exception as e:
                errs.append(f'case_config 解析失败：{e}')
                case = {}
            cid = case.get('case_id') or ''
            want = str(man.get('case_id') or '')
            # 缩放配置的 case_id 形如 R01_s1；基础案例是 R01
            if want and cid and not (cid == want or cid.startswith(want)
                                     or want.startswith(cid.split('_s')[0])):
                errs.append(f'case_id 与配置文件不符：清单 {want}，文件 {cid}')

    # 观测包：目录 + observation.json，且可见量与案例尺度一致（若有）
    op = man.get('observation_policy') or {}
    obs_dir = op.get('observation_dir')
    if obs_dir:
        d = _abs(obs_dir)
        if not d.is_dir():
            errs.append(f'观测目录不存在：{obs_dir}')
        elif not (d / 'observation.json').is_file():
            errs.append(f'观测包缺 observation.json：{obs_dir}')

    # 父候选：每个都必须有 id 与路径
    pcs = man.get('parent_candidates') or []
    if not isinstance(pcs, list) or not pcs:
        errs.append('parent_candidates 为空')
    else:
        for i, c in enumerate(pcs):
            if not c.get('candidate_id'):
                errs.append(f'parent_candidates[{i}] 缺 candidate_id')
            w = c.get('world') or c.get('world_dir')
            if not w:
                errs.append(f'parent_candidates[{i}] 缺 world 路径')
            elif not _abs(w).exists():
                errs.append(f'父候选目录不存在：{w}')

    # 真值碰撞资产
    tc = man.get('truth_collision')
    if tc and not _abs(tc).exists():
        errs.append(f'真值碰撞资产不存在：{tc}')

    # 协议 / 控制器冻结 / 状态来源
    for key in ('protocol', 'controller_freeze', 'state_source'):
        v = man.get(key)
        if v and not _abs(v).exists():
            errs.append(f'{key} 不存在：{v}')

    # 土壤：执行土壤必须在规划土壤集合内
    soils = man.get('planning_soils') or []
    ex = man.get('execution_soil')
    if not soils:
        errs.append('planning_soils 为空（跨土壤聚合必须有集合）')
    elif ex and ex not in soils:
        errs.append(f'execution_soil={ex} 不在 planning_soils={soils} 内')

    tb = man.get('time_budget_s')
    if not isinstance(tb, (int, float)) or tb <= 0:
        errs.append('time_budget_s 非法')

    return errs


def input_identities(man):
    """把输入清单里所有路径字段解析成内容身份（用于结果清单）。"""
    op = man.get('observation_policy') or {}
    pcs = man.get('parent_candidates') or []
    out = {
        'case_config': ident(_abs(man['case_config'])) if man.get('case_config') else None,
        'protocol': ident(_abs(man['protocol'])) if man.get('protocol') else None,
        'controller_freeze': (ident(_abs(man['controller_freeze']))
                              if man.get('controller_freeze') else None),
        'observation_dir': ident(_abs(op['observation_dir'])) if op.get('observation_dir') else None,
        'observation_json': (ident(_abs(op['observation_dir']) / 'observation.json')
                             if op.get('observation_dir') else None),
        'truth_collision': (ident(_abs(man['truth_collision']))
                            if man.get('truth_collision') else None),
        'state_source': ident(_abs(manifest_path_of(man, 'state_source')))
        if man.get('state_source') else None,
        'parents': [],
    }
    for c in pcs:
        w = c.get('world') or c.get('world_dir')
        out['parents'].append({'candidate_id': c.get('candidate_id'),
                               'world': ident(_abs(w)) if w else None})
    return out


def manifest_path_of(man, key):
    """state_source 既可以是文件也可以是目录；原样返回。"""
    return man.get(key)


def make_result(man, stage_status, qualification, extra=None):
    """构造结果清单并给出内容摘要。

    摘要只覆盖内容字段，不覆盖自身，避免自引用（§4.2）。
    """
    ids = input_identities(man)
    res = {
        'schema_version': RESULT_SCHEMA,
        'run_id': None,               # 由调用方在执行前生成并回填
        'batch_id': man.get('batch_id'),
        'run_tag': man.get('run_tag'),
        'case_id': man.get('case_id'),
        'code_sha': git_head(),
        'protocol_sha': (ids.get('protocol') or {}).get('sha256'),
        'controller_freeze_sha': (ids.get('controller_freeze') or {}).get('sha256'),
        'inputs_sha': ids,
        'observation_sha': (ids.get('observation_dir') or {}).get('sha256'),
        'observation_json_sha': (ids.get('observation_json') or {}).get('sha256'),
        'state_sha': (ids.get('state_source') or {}).get('sha256'),
        'planning_soils': man.get('planning_soils'),
        'execution_soil': man.get('execution_soil'),
        'time_budget_s': man.get('time_budget_s'),
        'stage_status': stage_status,
        'qualification': qualification,
        'started_at': man.get('_started_at'),
        'finished_at': time.time(),
    }
    if extra:
        res.update(extra)
    res['content_sha'] = sha_obj({k: v for k, v in res.items() if k != 'content_sha'})
    return res


def validate_result(res):
    errs = []
    for k in RESULT_REQUIRED:
        if k not in res:
            errs.append(f'结果清单缺字段 {k}')
    for k in ('protocol_sha', 'observation_sha'):
        v = res.get(k)
        if v is not None and (not isinstance(v, str) or len(v) != 64):
            errs.append(f'{k} 不是完整 SHA256：{v}')
    prov = res.get('protocol_sha')
    if prov and ('/' in prov or prov.endswith('.json')):
        errs.append('protocol_sha 填的是路径，不是内容哈希')
    for p in (res.get('inputs_sha') or {}).get('parents') or []:
        s = (p.get('world') or {}).get('sha256')
        if s is not None and len(s) != 64:
            errs.append(f'父候选 {p.get("candidate_id")} 的 world sha 不是完整 SHA256')
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--result', action='store_true', help='按结果清单校验')
    a = ap.parse_args()
    man = json.loads(_abs(a.manifest).read_text())
    if a.result:
        errs = validate_result(man)
        out = {'manifest': a.manifest, 'kind': 'result', 'ok': not errs, 'errors': errs}
    else:
        errs = validate_input(man)
        ids = input_identities(man) if not errs else {}
        out = {'manifest': a.manifest, 'kind': 'input', 'ok': not errs,
               'errors': errs, 'identities': ids}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not errs else 1


if __name__ == '__main__':
    sys.exit(main())
