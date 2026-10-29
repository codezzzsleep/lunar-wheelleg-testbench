"""
V5 批次干跑/预检：不联网、不上传、不 create。

  .venv/bin/python scripts/preflight_delivery_v5.py \
      --plan plans/unseen_delivery_v5.json \
      --budget configs/unseen_v5_budget.json \
      --ledger runs/unseen/generation/ledger.jsonl \
      --cache runs/unseen/generation/cache \
      --out runs/unseen/delivery_v5/v5_20261029/verify/preflight.json

检查：文件/哈希、模型参数、请求身份唯一、输入/观测/真值配套、账本授权上界、
缓存与已有任务、resume 不 create、重复计划/缺图/超时路径的测试引用。
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import budget as B
import imagine

ROOT = pathlib.Path(__file__).resolve().parent.parent
FACE_MIN, FACE_MAX = 10000, 300000
VERSIONS = {'G1', 'G1-Turbo'}


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--budget', required=True)
    ap.add_argument('--ledger', required=True)
    ap.add_argument('--cache', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    plan = json.loads(pathlib.Path(a.plan).read_text())
    budget = json.loads(pathlib.Path(a.budget).read_text())
    led = B.BudgetLedger(a.ledger)
    checks = []

    def check(name, ok, detail=''):
        checks.append({'check': name, 'pass': bool(ok), 'detail': detail})
        return bool(ok)

    inputs = plan.get('inputs', [])
    check('plan 最多 3 项', len(inputs) <= 3, len(inputs))
    check('plan 授权上界 <=60',
          sum(float(i.get('credits_upper', 0)) for i in inputs) <= 60,
          sum(float(i.get('credits_upper', 0)) for i in inputs))
    check('plan 单项上界 <=20', all(float(i.get('credits_upper', 0)) <= 20
                                   for i in inputs),
          [i.get('credits_upper') for i in inputs])
    check('plan status 为 PREPARED/READY',
          plan.get('status') in ('PREPARED', 'READY'), plan.get('status'))
    check('plan 历史与预算一致',
          plan.get('history', {}).get('tasks_used') == budget.get('inherited_usage', {}).get('tasks')
          and plan.get('history', {}).get('credits_upper') == budget.get('inherited_usage', {}).get('credits_upper'),
          {'plan': plan.get('history'), 'budget': budget.get('inherited_usage')})
    check('plan 累计数与预算一致',
          plan.get('would_be_cumulative', {}).get('tasks') == budget.get('max_create_tasks')
          and plan.get('would_be_cumulative', {}).get('credits_upper') == budget.get('hard_cap'),
          {'plan': plan.get('would_be_cumulative'),
           'budget': {'tasks': budget.get('max_create_tasks'),
                      'credits_upper': budget.get('hard_cap')}})

    rep = led.report(budget)
    check('账本历史 24 任务/480 上界',
          rep['created_tasks'] == 24 and abs(rep['held_credits_upper'] - 480.0) < 1e-6,
          rep)
    check('剩余额度容纳本批 3/60',
          rep['remaining_tasks'] >= len(inputs)
          and rep['remaining_credits'] >= sum(float(i.get('credits_upper', 0)) for i in inputs),
          {'remaining_tasks': rep['remaining_tasks'],
           'remaining_credits': rep['remaining_credits']})
    check('核验扣费仍为 unknown（不写已核验）',
          rep.get('verified_charge') == 0 and rep.get('charge_unknown', 0) >= 24,
          rep)
    check('AHOLO_API_KEY 存在（付费路径）', bool(os.environ.get('AHOLO_API_KEY')),
          '只记录存在性，不记录值')
    check('resume 只处理 has_task、不会 create',
          'resume' in pathlib.Path(ROOT / 'scripts/imagine.py').read_text()
          and "endswith('has_task')" in pathlib.Path(ROOT / 'scripts/imagine.py').read_text(),
          'tests/test_budget.py::test_7_resume_never_creates')
    check('重复计划/首次超时/缺图测试存在',
          all(x in pathlib.Path(ROOT / 'tests/test_budget.py').read_text()
              for x in ('test_duplicate_identity_in_plan_rejected',
                        'test_first_create_timeout_does_not_create_again',
                        'test_12_submit_timeout_marks_uncertain_and_keeps_budget')),
          'tests/test_budget.py')

    seen = {}
    entries = []
    for item in inputs:
        iid = item['id']
        img = ROOT / item['image']
        ok_img = img.exists() and sha(img) == item.get('image_sha256')
        check(f'{iid}: 输入图存在且 SHA 一致', ok_img,
              {'path': item['image'], 'sha': item.get('image_sha256')})
        model = item.get('model') or {}
        ok_model = (model.get('version') in VERSIONS
                    and isinstance(model.get('face_count'), int)
                    and FACE_MIN <= model['face_count'] <= FACE_MAX)
        check(f'{iid}: 模型参数合法（官方 faceCount 10000–300000）', ok_model,
              {'model': model,
               'source': 'https://labs.aholo3d.cn/api-docs/openapi.json'})
        try:
            ident = imagine.request_identity(img.read_bytes(), item.get('variant', 'orig'),
                                             model, item.get('repeat_idx', 0))
            ok_id = len(ident) == 64 and all(c in '0123456789abcdef' for c in ident)
        except Exception as e:
            ident, ok_id = None, False
        check(f'{iid}: 请求身份 64 位十六进制', ok_id, ident)
        if ident:
            check(f'{iid}: 计划内身份唯一', ident not in seen,
                  {'identity': ident, 'also': seen.get(ident)})
            seen[ident] = iid
            recs = [r for r in led.rows() if r.get('identity') == ident and led.is_held(r)]
            hit = imagine.cache_valid(a.cache, ident)
            state = ('cached' if hit else
                     (f"{recs[-1]['status']}_has_task" if recs and recs[-1].get('task_id')
                      else ('has_ledger_no_task' if recs else 'need_create')))
            check(f'{iid}: 无已占用同身份任务且未缓存（本批要求新 create）',
                  state == 'need_create',
                  {'state': state, 'task_id': (recs[-1] if recs else {}).get('task_id')})
        else:
            state = 'identity_error'
        # observation / truth 配套
        obs_man = item.get('observation_manifest_dir')
        ok_obs = False
        detail_obs = {}
        if obs_man:
            mp = ROOT / obs_man / 'observation_manifest.json'
            if mp.exists():
                m = json.loads(mp.read_text())
                ok_obs = (m.get('observation_id') == item.get('observation_id')
                          and m.get('observation_sha') == item.get('observation_sha'))
                detail_obs = {'manifest': str(mp), 'observation_id': m.get('observation_id'),
                              'observation_sha': m.get('observation_sha')}
        check(f'{iid}: 观测 manifest 与 observation_sha 对应', ok_obs, detail_obs)
        tc = item.get('truth_case')
        ok_truth = bool(tc) and (ROOT / tc).exists()
        check(f'{iid}: 真值 case 存在', ok_truth, tc)
        if ok_truth:
            t = json.loads((ROOT / tc).read_text())
            check(f'{iid}: 真值 world SHA 记录一致',
                  (not item.get('truth_world_sha')) or (t.get('truth_world_sha') == item.get('truth_world_sha')),
                  {'case_sha': t.get('truth_world_sha'), 'plan_sha': item.get('truth_world_sha')})
        entries.append({'id': iid, 'identity': ident, 'state': state,
                        'model': model, 'observation_sha': item.get('observation_sha'),
                        'truth_case': tc})

    need = [e for e in entries if e['state'] == 'need_create']
    check('need_create 数 <= 3 且总上界 <=60',
          len(need) <= 3 and len(need) * 20 <= 60, len(need))
    out = {'schema': 'delivery-preflight/v1', 'plan': a.plan,
           'plan_sha256': sha(ROOT / a.plan), 'budget': a.budget,
           'budget_sha256': sha(ROOT / a.budget), 'ledger': a.ledger,
           'budget_report': rep, 'entries': entries, 'checks': checks,
           'n_checks': len(checks),
           'n_pass': sum(1 for c in checks if c['pass']),
           'ok': all(c['pass'] for c in checks),
           'mode': 'dry_run_only_no_network'}
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'ok': out['ok'], 'n_pass': out['n_pass'],
                      'n_checks': out['n_checks'],
                      'need_create': [e['id'] for e in need],
                      'budget': rep}, ensure_ascii=False))
    for c in checks:
        if not c['pass']:
            print('FAIL', c['check'], '|', c['detail'])
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
