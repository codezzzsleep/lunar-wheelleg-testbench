"""
V7-R1 §3.1：预算口径更正（不重写历史账本）。

历史账本里 10 个 V7 任务按 estimate_upper=20 预留（合计 200）。用户提供的价目截图显示
Lux3D「图生网格极速版」优惠 1 积分/次。该价格**尚未与 API 回传的实际扣费核对**，
因此：price_expected 写 1.0、price_verified=false、actual_charge=unknown，
同时把前后差额作为**更正事件**释放，而不是改写旧记录。

  .venv/bin/python scripts/v7_budget_r1.py --out configs/unseen_v7_r1_budget.json
"""
import argparse, json, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parent.parent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', default='runs/unseen/delivery_v7/v7_20261030')
    ap.add_argument('--out', default='configs/unseen_v7_r1_budget.json')
    a = ap.parse_args()
    B = ROOT / a.batch
    rows = [json.loads(l) for l in (B / 'generation/ledger.jsonl').read_text().splitlines() if l.strip()]
    legacy = sum(float(r.get('estimate_upper') or 0) for r in rows)
    n = len(rows)
    price_expected = 1.0
    reserved_current = round(n * price_expected, 3)
    cfg = {
        'schema': 'batch-budget/v7-r1',
        'batch_id': 'v7_20261030_r1',
        'created': '2026-10-30',
        'authorization': {'new_total_credits': 500.0,
                          'note': '沿用 V7 新增授权 500，不是再获得 500；账户余额 1042 是另一件事，分列。'},
        'account': {'balance_reported_by_user': 1042, 'unit': 'credits',
                    'note': '账户余额与本批授权余量分列，不混算。'},
        'price': {
            'product': 'Lux3D 图生网格（极速版 / G1-Turbo）',
            'price_expected': price_expected,
            'price_basis': ('用户提供的价目截图：Lux3D 图生网格极速版优惠 1 积分/次；'
                            '仅该产品行，未证明所有版本与两图任务同价'),
            'price_verified': False,
            'actual_charge': 'unknown',
            'note': 'API 不返回实际扣费；不得把 price_expected 写成已核验支出。'},
        'ledger': {
            'path': f'{a.batch}/generation/ledger.jsonl',
            'n_tasks': n,
            'legacy_estimate_upper_sum': legacy,
            'reserved_current': reserved_current,
            'correction': {'from': legacy, 'to': reserved_current,
                           'released': round(legacy - reserved_current, 3),
                           'reason': '旧预留沿用历史 20 积分/任务口径，按当前价目与产品行更正；'
                                     '历史记录保留，不改写为已核验支出'},
            'actual_charge_verified_total': None},
        'remaining': {
            'authorized_minus_current_reserved': round(500.0 - reserved_current, 3),
            'authorized_minus_legacy_upper': round(500.0 - legacy, 3),
            'note': '两个口径都列出；实际扣费未知时不得声称精确剩余。'},
        'constraints': {
            'max_create_tasks_note': '删除 budget_total // 20 这种由旧估价推导的硬任务数限制；'
                                     '保留计划级防无限重复（同 identity 不重复创建）。',
            'resume_never_creates': True,
            'timeout_first_query': True,
            'repeated_sampling_needs_new_sample_id': True},
        'created_at': time.time(),
    }
    p = ROOT / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    print(json.dumps({'n_tasks': n, 'legacy_upper': legacy,
                      'reserved_current': reserved_current,
                      'released': round(legacy - reserved_current, 3)}, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
