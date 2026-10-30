"""
V7：生成客户端接口回归（不发起任何付费调用）。

检查：
  R1 两图确实序列化为 `imgs` 两元素，且**不含** `img`；
  R2 调换输入顺序，请求身份改变；
  R3 改第二张图，请求身份改变；
  R4 单图路径保持兼容（仍是 `img`，不含 `imgs`）；
  R5 resume 只查询/下载，不 create；
  R6 多图少于两张被拒绝；
  R7 预算预留：同一身份重复 reserve 被识别为重复，不重复占用。

  .venv/bin/python scripts/v7_gen_interface_test.py --out <json>
"""
import argparse
import hashlib
import json
import pathlib
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import budget
import lux3d_client as LC

ROOT = pathlib.Path(__file__).resolve().parent.parent


def make_png(path, color):
    Image.fromarray(np.full((64, 64, 3), color, dtype=np.uint8)).save(path)
    return path


def captured(monkeypatch_list):
    """拦掉真实 HTTP：记录调用参数并返回假响应。"""
    calls = []

    def fake_req(method, path, body=None, timeout=90):
        calls.append({'method': method, 'path': path, 'body': body})
        if path.endswith('/create'):
            return {'c': '0', 'd': 123456}
        return {'c': '0', 'd': {'taskId': 123456, 'status': 'succeeded'}}
    LC._req = fake_req
    return calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='v7gen_'))
    p1 = make_png(tmp / 'v1.png', 10)
    p2 = make_png(tmp / 'v2.png', 200)
    p2b = make_png(tmp / 'v2b.png', 90)
    rows = []

    def add(name, ok, detail=''):
        rows.append({'check': name, 'pass': bool(ok), 'detail': str(detail)})
        print(('PASS' if ok else 'FAIL'), name, detail)

    # R1/R2/R3/R4：先用 request_identity 做纯身份检查（不触网）
    i12 = LC.request_identity('img-to-3d-multi', [p1, p2], 'G1-Turbo')
    i21 = LC.request_identity('img-to-3d-multi', [p2, p1], 'G1-Turbo')
    i12b = LC.request_identity('img-to-3d-multi', [p1, p2b], 'G1-Turbo')
    add('R2_order_changes_identity', i12 != i21, f'{i12[:8]} vs {i21[:8]}')
    add('R3_second_image_changes_identity', i12 != i12b, f'{i12[:8]} vs {i12b[:8]}')

    calls = captured([])
    LC.submit_img_to_3d_multi([str(p1), str(p2)], version='G1-Turbo')
    body = calls[-1]['body']
    add('R1_multi_sends_imgs_two', isinstance(body.get('imgs'), list) and len(body['imgs']) == 2,
        body.get('imgs'))
    add('R1_no_img_field', 'img' not in body, sorted(body))
    add('R1_version_explicit', body.get('version') == 'G1-Turbo', body.get('version'))

    calls.clear()
    LC.submit_img_to_3d(str(p1), version='G1-Turbo')
    body1 = calls[-1]['body']
    add('R4_single_keeps_img', isinstance(body1.get('img'), str) and 'imgs' not in body1, sorted(body1))

    try:
        LC.submit_img_to_3d_multi([str(p1)], version='G1-Turbo')
        add('R6_multi_rejects_single', False, '没有拒绝')
    except SystemExit:
        add('R6_multi_rejects_single', True, 'rejected')

    # R5：resume 只查不建
    calls.clear()
    st = LC.get_task(123456)
    add('R5_resume_only_queries', all('/get' in c['path'] for c in calls) and len(calls) == 1,
        [c['path'] for c in calls])
    add('R5_resume_no_create', not any('/create' in c['path'] for c in calls), '')

    # R7：预算预留去重
    led_p = tmp / 'ledger.jsonl'
    led = budget.BudgetLedger(str(led_p))
    bud = {'hard_cap': 500.0, 'per_task_cap': 20.0, 'max_create_tasks': 40}
    ident = hashlib.sha256(b'ident-A').hexdigest()
    ok1, why1 = led.reserve(ident, 'attempt-1', 20.0, bud)
    ok2, why2 = led.reserve(ident, 'attempt-1', 20.0, bud)
    rep = led.report(bud)
    add('R7_reserve_once', bool(ok1) and (not ok2), f'{ok1}/{why1} then {ok2}/{why2}')
    add('R7_budget_not_double_counted', abs(float(rep.get('held_credits_upper', 0)) - 20.0) < 1e-6,
        rep.get('held_credits_upper'))

    rep_out = {'schema': 'gen-interface-test/v7', 'n': len(rows),
               'n_pass': sum(1 for r in rows if r['pass']), 'rows': rows}
    if a.out:
        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.out).write_text(json.dumps(rep_out, ensure_ascii=False, indent=2))
    print(json.dumps({'n_pass': rep_out['n_pass'], 'n': rep_out['n']}, ensure_ascii=False))
    return 0 if rep_out['n_pass'] == rep_out['n'] else 1


if __name__ == '__main__':
    sys.exit(main())
