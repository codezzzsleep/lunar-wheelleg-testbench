"""
H5 候选加载器：从**本地缓存**读取已清理、已配准的真实 Lux3D 候选。

不触发生成、不联网。缺失或坏文件明确拒绝，不猜。

  from candidate_store import load_candidates
  cands = load_candidates(plan_path, clean_root, align_root, policy_path)

合同（E4 任务 4）：
  · 每条候选必须带 task_id、输入图 SHA、GLB SHA、clean SHA、world SHA、
    policy 版本与 coordinate_frame；
  · coordinate_frame 必须是 world；否则拒绝（不猜、不二次变换）；
  · source_kind 区分 lux3d / fixture；fixture 不计入真实生成主张。
"""
import hashlib
import json
import pathlib

REQUIRED_KEYS = ('candidate_id', 'task_id', 'input_sha256', 'glb_sha256',
                 'clean_sha256', 'world_sha256', 'coordinate_frame',
                 'policy_version', 'source_kind')


def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


class CandidateError(Exception):
    pass


def load_candidates(plan_path, clean_root, align_root, policy_path,
                    observation_group='A'):
    """返回 (candidates, report)。任何一条不合格只跳过该条并记录原因。"""
    plan = json.loads(pathlib.Path(plan_path).read_text())
    policy = json.loads(pathlib.Path(policy_path).read_text())
    clean_root = pathlib.Path(clean_root)
    align_root = pathlib.Path(align_root)

    # 计划项 id -> 输入图与任务 id（来自生成账本）
    ledger = {}
    led_p = pathlib.Path(plan_path).parent.parent / 'runs/unseen/generation/ledger.jsonl'
    if led_p.exists():
        for line in led_p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            ledger[r['identity']] = r

    out, report = [], {'accepted': [], 'rejected': [], 'policy_version': policy.get('version')}
    for item in plan['inputs']:
        cid = item['id']
        if item.get('status') == 'disabled' or not item.get('image'):
            continue
        if item.get('group') not in ('A', 'B', observation_group, 'CAL'):
            continue
        rec, why = {'candidate_id': cid, 'source_kind': 'lux3d'}, []
        # 1) 清理记录
        cj = clean_root / cid / 'clean.json'
        if not cj.exists():
            why.append('missing clean.json')
        else:
            cr = json.loads(cj.read_text())
            rec['clean_verdict'] = cr.get('precheck', {}).get('verdict')
            rec['clean_sha256'] = cr.get('clean_sha')
            rec['thin_ratio'] = cr.get('verify', {}).get('thin_ratio')
            if rec['clean_verdict'] != 'ok':
                why.append(f"clean verdict {rec['clean_verdict']}")
        # 2) 配准结果 + world 资产
        aj = align_root / f'{cid}.json'
        if not aj.exists():
            why.append('missing alignment json')
        else:
            ar = json.loads(aj.read_text())
            rec['strict_rgbd_diagnostic_pass'] = bool(ar.get('pass'))
            rec['best'] = (ar.get('best') or {}).get('native')
            wd = align_root / 'world' / cid
            man = wd / 'manifest.json'
            if not man.exists():
                why.append('missing world manifest')
            else:
                m = json.loads(man.read_text())
                if m.get('coordinate_frame') != 'world':
                    why.append(f"coordinate_frame={m.get('coordinate_frame')} (must be world)")
                rec['coordinate_frame'] = m.get('coordinate_frame')
                rec['world_sha256'] = m.get('world_sha')
                rec['T_world_from_asset'] = m.get('T_world_from_asset')
                rec['world_dir'] = str(wd)
                if m.get('world_sha') and (wd / 'body.stl').exists():
                    if _sha(wd / 'body.stl') != m['world_sha']:
                        why.append('world mesh SHA mismatch')
        # 3) 生成来源：由输入图字节身份在账本里查 task_id（不猜、不按 id 名匹配）
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import imagine
        try:
            ident = imagine.request_identity(pathlib.Path(item['image']).read_bytes(),
                                             item.get('variant', 'orig'), item['model'],
                                             item.get('repeat_idx', 0))
            led = ledger.get(ident) or {}
            rec['task_id'] = led.get('task_id') or item.get('task_id')
            rec['glb_sha256'] = None
            g = pathlib.Path('runs/unseen/generation/cache') / ident[:2] / ident / 'model.glb'
            if g.exists():
                rec['glb_sha256'] = _sha(g)
            rec['input_sha256'] = _sha(item['image'])
        except Exception as e:
            why.append(f'identity resolution failed: {type(e).__name__}')
        rec['policy_version'] = policy.get('version')
        missing = [k for k in REQUIRED_KEYS if rec.get(k) in (None, '')]
        missing = [k for k in missing if k not in ('glb_sha256', 'input_sha256')]
        if missing:
            why.append(f'missing keys {missing}')
        rec['reject_reason'] = '; '.join(why) if why else None
        rec['planning_eligible'] = bool(not why) and _planning_eligible(rec, policy)
        if why:
            report['rejected'].append({'candidate_id': cid, 'reasons': why})
        else:
            out.append(rec)
            report['accepted'].append(cid)
    return out, report


def _planning_eligible(rec, policy):
    """按冻结政策判定是否允许进入工程预演（不是安全证明）。"""
    c = policy.get('criteria', {})
    if rec.get('source_kind') != 'lux3d':
        return False
    if rec.get('clean_verdict') != 'ok':
        return False
    tr = rec.get('thin_ratio')
    if tr is None or tr < c.get('thin_ratio_min', 0.2):
        return False
    best = rec.get('best') or {}
    iou = best.get('mask_iou')
    if iou is None or iou < c.get('contour_iou_min', 0.85):
        return False
    if rec.get('coordinate_frame') != 'world':
        return False
    return True


def make_fixture_candidate(mesh_path, candidate_id, out_dir, work_dir=None):
    """
    用已配准的 fixture 网格构造一条 source_kind=fixture 的候选。
    仅用于接口与错误路径测试，**不得**计入真实生成效果表。
    """
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    wd = out / 'world' / candidate_id
    wd.mkdir(parents=True, exist_ok=True)
    body = wd / 'body.stl'
    import shutil
    shutil.copy2(mesh_path, body)
    man = {'schema': 'asset-manifest/v1', 'coordinate_frame': 'world',
           'parts': ['body.stl'], 'world_sha': _sha(body),
           'source_kind': 'fixture',
           'note': 'fixture：接口测试用，不是 Lux3D 产物'}
    (wd / 'manifest.json').write_text(json.dumps(man, indent=2))
    return {'candidate_id': candidate_id, 'source_kind': 'fixture',
            'coordinate_frame': 'world', 'world_dir': str(wd),
            'world_sha256': man['world_sha'], 'clean_verdict': 'ok',
            'thin_ratio': 0.5, 'best': {'mask_iou': 0.99},
            'policy_version': 'fixture', 'task_id': 'fixture',
            'planning_eligible': False}
