"""权威运行清单：定义 schema、校验实例、并解析相对仓库的路径。

清单字段（任务书 §四）：run / case / observation / state / hypothesis / physics /
decision / execution / limits。缺文件立即报错；"文件存在"不等于阶段成功。

  .venv/bin/python scripts/v7_run_manifest.py --manifest plans/r1_runs/R03_same_scene.json --check
"""
import argparse, hashlib, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent

REQUIRED = {
    'run': ['batch_id', 'run_id', 'code_commit', 'protocol_sha'],
    'case': ['object_id', 'case_config'],
    'observation': ['package', 'public_visibility'],
    'state': ['snapshot', 'controller_freeze'],
    'hypothesis': ['parent_id', 'parent_sha', 'fusion', 'collision'],
    'physics': ['truth_collision', 'exec_soil', 'rehearsal_soils'],
    'decision': ['decision_sha', 'matrix', 'events'],
    'execution': ['trajectory', 'result'],
    'limits': ['missing', 'disqualified'],
}


def sha(p):
    p = pathlib.Path(p)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()[:16]


def resolve(v):
    if v is None or isinstance(v, (int, float, bool, list, dict)):
        return v
    p = pathlib.Path(v)
    return p if p.is_absolute() else ROOT / p


def check(man):
    errs, info = [], {}
    for sec, keys in REQUIRED.items():
        block = man.get(sec)
        if not isinstance(block, dict):
            errs.append(f'缺区块 {sec}')
            continue
        for k in keys:
            if k not in block:
                errs.append(f'{sec}.{k} 缺失')
    for sec in ('case', 'observation', 'state', 'hypothesis', 'physics', 'decision', 'execution'):
        for k, v in (man.get(sec) or {}).items():
            if isinstance(v, str) and ('/' in v or v.endswith('.json') or v.endswith('.jsonl')):
                p = resolve(v)
                if not p.exists():
                    errs.append(f'{sec}.{k} 指向的文件不存在：{v}')
                else:
                    info[f'{sec}.{k}'] = {'path': str(p.relative_to(ROOT))
                                          if p.is_relative_to(ROOT) else str(p),
                                          'sha': sha(p) if p.is_file() else None}
    return errs, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    man = json.loads((ROOT / a.manifest).read_text())
    errs, info = check(man)
    rep = {'manifest': a.manifest, 'ok': not errs, 'errors': errs, 'resolved': info}
    print(json.dumps(rep, ensure_ascii=False, indent=2)[:2000])
    return 0 if not errs else 1


if __name__ == '__main__':
    sys.exit(main())
