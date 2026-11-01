"""碰撞资产解析（唯一入口）。

两类资产布局不同，不能一律追加 `/collision`：

  普通融合资产   <root>/manifest.json          （parts/body.stl，网格表示）
                 <root>/collision/manifest.json（boxes，占据合并表示）← 规划用这个
  2.5D 高程资产  <root>/manifest.json          （boxes 直接写在根，无 collision 子目录）

解析顺序（对每个候选目录都做**可用性校验**，不只看文件是否存在）：
  1. <root>/collision ：manifest 含 boxes 或 parts 全部可解析 → 采用；
  2. <root>           ：同上 → 采用；
  3. 都不行 → 抛 CollisionAssetError，附带每个候选的失败原因。

调用方一律使用 `resolve(root)`，不允许自己拼 `collision` 路径。
"""
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = 'collision-asset/v1'


class CollisionAssetError(RuntimeError):
    """资产不可加载：必须作为 rehearsal_error 记录，不能当成物理失败。"""

    def __init__(self, root, attempts):
        self.root = str(root)
        self.attempts = attempts
        detail = '; '.join(f"{a['dir']}: {a['reason']}" for a in attempts)
        super().__init__(f'碰撞资产不可用 {root} -> {detail}')


def _sha(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _check_dir(d):
    """返回 (ok, kind, manifest, reason)。kind ∈ {'boxes','parts'}。"""
    d = pathlib.Path(d)
    mpath = d / 'manifest.json'
    if not mpath.is_file():
        return False, None, None, '缺 manifest.json'
    try:
        man = json.loads(mpath.read_text())
    except Exception as e:
        return False, None, None, f'manifest 解析失败：{e}'
    boxes = man.get('boxes')
    if boxes:
        if not isinstance(boxes, list) or not all(len(b) == 6 for b in boxes[:5]):
            return False, None, man, 'boxes 结构异常'
        return True, 'boxes', man, None
    parts = man.get('parts') or []
    if not parts:
        return False, None, man, '既无 boxes 也无 parts'
    missing = [p for p in parts if not (d / p).is_file()]
    if missing:
        return False, None, man, f'parts 缺 {len(missing)}/{len(parts)} 个（如 {missing[0]}）'
    return True, 'parts', man, None


def resolve(asset_root, require_boxes=False):
    """把资产根解析成**可直接交给环境**的碰撞目录。"""
    root = pathlib.Path(asset_root)
    if not root.is_absolute():
        root = ROOT / root
    attempts = []
    for cand in (root / 'collision', root):
        ok, kind, man, reason = _check_dir(cand)
        attempts.append({'dir': str(cand), 'ok': ok, 'kind': kind, 'reason': reason})
        if ok and (not require_boxes or kind == 'boxes'):
            rel = (str(cand.relative_to(ROOT)) if cand.is_relative_to(ROOT) else str(cand))
            return {'schema': SCHEMA, 'asset_root': str(asset_root),
                    'collision_dir': rel, 'kind': kind,
                    'n_boxes': len(man.get('boxes') or []),
                    'n_parts': len(man.get('parts') or []),
                    'pitch_m': man.get('pitch_m'),
                    'coordinate_frame': man.get('coordinate_frame'),
                    'world_sha': man.get('world_sha'),
                    'collision_sha': man.get('collision_sha'),
                    'manifest_sha': _sha(cand / 'manifest.json'),
                    'attempts': attempts}
    raise CollisionAssetError(asset_root, attempts)


def describe(asset_root):
    """只诊断不抛错：返回解析结果或失败说明，供报告与页面用。"""
    try:
        return resolve(asset_root)
    except CollisionAssetError as e:
        return {'schema': SCHEMA, 'asset_root': str(asset_root), 'ok': False,
                'error': str(e), 'attempts': e.attempts}
