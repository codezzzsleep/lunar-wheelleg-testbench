"""V8 与 Lux3D 的交接：请求文件、结果文件、复用检查（格式沿用 V7）。

路线脚本在沙箱上运行，Lux3D 只在用户本机调用。路线每走到需要想象的一眼：
  - 每块目标石头写一份 lux_request.json（与 V7 相同的字段）；结果还没有 -> 退出码 10，等本机把结果拉回来；
  - 再次运行时，路线从头确定性地重放到这一眼，重新拍到的输入图必须与请求时逐字节相同（sha256），
    相同才使用已有结果；不同就退出码 11 停下（说明重放不一致，不能拿旧结果冒充）。
第一眼：单图，A1 A2 B1 B2 C1 C2 六份（A=紧裁剪，B=只留石头亮处，C=带上下文；各两份独立样本）。
第二眼：两图，同一块石头第一眼与第二眼的 A1，按顺序放进请求体字段 imgs（不得拼成一张图），三份独立样本 M1–M3。
"""
import hashlib
import json
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def rel(p):
    return str(pathlib.Path(p).resolve().relative_to(ROOT))


def items_first(tstate):
    return [{'id': k, 'path': v['path'], 'sha256': v['sha256']} for k, v in sorted(tstate['crops'].items())]


def items_second(t1state, t2state):
    p1, p2 = t1state['crops']['A1'], t2state['crops']['A1']
    return [{'id': f'M{i}', 'paths': [p1['path'], p2['path']], 'sha256': [p1['sha256'], p2['sha256']]} for i in (1, 2, 3)]


def write_request(tdir, mode, items):
    req = {'schema': 'v8-lux-request/v1', 'mode': mode, 'version': 'G1-Turbo', 'faceCount': 30000, 'items': items,
           'result_file': rel(pathlib.Path(tdir) / 'lux_result.json'),
           'result_schema': {'tasks': [{'id': 'A1', 'task_id': '...', 'status': 'ok|failed', 'submitted_at': '...', 'finished_at': '...',
                                        'fetched_at': '...', 'glb': 'repo-relative path of tex_mesh.glb', 'glb_sha256': '...',
                                        'inputs': ['repo-relative input image paths'],
                                        **({'api_field': 'imgs', 'n_images': 2} if mode == 'imgs' else {})}]}}
    if mode == 'imgs':
        req['imgs_rule'] = ('Each item is ONE Lux3D task whose request body carries the field imgs = [url of paths[0], url of paths[1]] '
                            'in this order (scripts/lux3d_client.submit_img_to_3d_multi). Never stitch the two images into one picture. '
                            'Items with identical paths are independent samples: give each its own sample id so they are not cache hits.')
    (pathlib.Path(tdir) / 'lux_request.json').write_text(json.dumps(req, indent=2, ensure_ascii=False))
    return req


def read_result(tdir):
    """返回 [{'id', 'glb'}]；结果不存在返回 None；不合规（两图不是真两图、输入图对不上、GLB 校验不过）抛错。"""
    tdir = pathlib.Path(tdir)
    p = tdir / 'lux_result.json'
    if not p.exists():
        return None
    res = json.loads(p.read_text()); req = json.loads((tdir / 'lux_request.json').read_text())
    want = {it['id']: it for it in req['items']}
    out = []
    for t in res['tasks']:
        it = want.get(t['id'])
        if it is None:
            raise RuntimeError(f'{p}: task {t["id"]} is not in the request')
        if req['mode'] == 'imgs' and t.get('status') == 'ok' and not (t.get('api_field') == 'imgs' and t.get('n_images') == 2):
            raise RuntimeError(f'{p}: task {t["id"]} is not a real two-image call (need api_field=imgs, n_images=2)')
        paths = it['paths'] if req['mode'] == 'imgs' else [it['path']]
        if [str(x) for x in (t.get('inputs') or [])] != paths:
            raise RuntimeError(f'{p}: task {t["id"]} inputs {t.get("inputs")} != request {paths}')
        if t.get('status') == 'ok' and t.get('glb'):
            g = ROOT / t['glb']
            if not g.exists() or sha(g) != t.get('glb_sha256'):
                raise RuntimeError(f'{p}: task {t["id"]} glb missing or sha256 mismatch')
            out.append({'id': t['id'], 'glb': str(g)})
    return out


def same_inputs(old_state, new_state):
    """重放检查：两次拍到的观测与 Lux3D 输入图逐字节相同。"""
    a, b = old_state.get('observation_sha256', {}), new_state.get('observation_sha256', {})
    if a != b:
        return False
    return {k: v['sha256'] for k, v in old_state['crops'].items()} == {k: v['sha256'] for k, v in new_state['crops'].items()}


def match_target(cells, prev_targets):
    """第二眼的目标对应到第一眼的哪一块：地图格子重叠最多的那块。"""
    best, score = None, 0
    for t in prev_targets:
        s = int((np.asarray(t['cells']) & cells).sum())
        if s > score:
            best, score = t, s
    return best
