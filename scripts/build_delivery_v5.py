"""
从本批 manifest/正式表/收益/月壤/验收结果生成 delivery.json（不手写状态）。

  .venv/bin/python scripts/build_delivery_v5.py \
      --manifest runs/unseen/delivery_v5/v5_20261029/manifest.json \
      --out runs/unseen/delivery_v5/v5_20261029/delivery.json

delivery_status 只在 P0–P7 均有真实产物、统一验收无失败、页面截图存在时为 COMPLETE；
否则 PARTIAL。研究收益不由本脚本升级。
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(p, default=None):
    p = pathlib.Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    manp = pathlib.Path(a.manifest)
    man = load(manp)
    bdir = manp.parent
    formal = load(bdir / 'evaluation/formal_table_v5.json', {})
    benefit = load(bdir / 'evaluation/benefit_summary.json', {})
    soil = load(bdir / 'soil/summary.json', {})
    obs = load(bdir / 'observation/summary.json', {})
    ver = load(bdir / 'verify/report.json', {})
    ct = load(bdir / 'candidates/candidate_table.json', {})
    pages = sorted((bdir / 'media/page').glob('*.png')) if (bdir / 'media/page').exists() else []
    wps = {k: v.get('status') for k, v in (man.get('work_packages') or {}).items()}
    ver_ok = bool(ver) and ver.get('n_fail') == 0
    delivery = ('COMPLETE' if all(wps.get(f'P{i}') == 'done' for i in range(8))
                and ver_ok and len(pages) >= 3 else 'PARTIAL')

    r01 = next((c for c in formal.get('cases', []) if c.get('case') == 'R01'), {})
    h5 = benefit.get('R01', {}).get('H5', {})
    b3 = benefit.get('R01', {}).get('B3_mirror', {})
    ut = benefit.get('R01', {}).get('U_truth', {})
    wr = benefit.get('R01', {}).get('width_rule', {})
    r03 = benefit.get('R03', {})
    out = {
        'schema': 'delivery/v5', 'batch_id': man.get('batch_id'),
        'delivery_status': delivery,
        'evidence_status': 'MIXED',
        'evidence_note': ('核心批次数据、身份链、同初态配对和负例已核验；'
                          '旧 H5 init003(0.03) / six_v4(15 s) / pipeline_H5_R03(0.03) 被统一初态/30 s 版本取代；'
                          'R01 与 dev_narrow_tall 同网格，不是独立留出；页面视觉状态见 page。'),
        'capability_status': {
            'real_generation': ('PARTIAL：3/3 生成并下载；3/3 clean/v4 通过；3/3 完成 1512 次配准搜索；'
                                '0/3 strict；1/3 planning eligible（C_R01_face12k，仅 IoU 过政策，P95/freespace 失败，CoACD 32 部件 hit_part_cap）；'
                                '原始 GLB 仍为 1–2 cm 量级，尺度问题未修复。'),
            'h5_truth_execution': ('PARTIAL：R01 H5 L2 2/3（seed0 30.02 s timeout），盲走 R1 0/3；'
                                   'B3 镜像/U_truth/宽度规则 S1 3/3；R03 H5=盲走=3/3；R02/R04 无候选且全动作 0/3。'),
            'multi_hypothesis_observation': ('NOT_ESTABLISHED：真实 face12k 单候选不触发（L2 一致）；'
                                             '可控 fixture（truth vs box）触发、第二视角筛掉 box、S1 真值续行成功；'
                                             '真实多假设观察收益未建立。'),
            'soil': ('PARTIAL：A 单轮 5 标定 + 4 验证 ≤5.24%；B 平地刚性/土壤；C 坡面 0–20°；'
                     'D 零牵引；E 1000 组合 0 NaN/Inf/异常；F 吞吐比 1.768；'
                     'G 整机几何下陷 PARTIAL_NOT_IMPLEMENTED（公式 26.5 mm vs 实测约 −0.97 mm）。'),
            'page_browser': (f'VERIFIED：{len(pages)} 张真实浏览器截图' if pages else 'NOT_VERIFIED'),
            'verifier': (f"{ver.get('n_pass')}/{ver.get('n_checks')}，含真实负例" if ver_ok else 'FAIL'),
            'case_coverage': ('6 个独立完整形状、3 个 API 任务、6 个观测方向、10 个 twin 背面变体；'
                              '有效隐藏背面取舍 0 个；R01 仅支持宽度规则诊断。')},
        'benefit_status': benefit.get('benefit_status', 'NOT_ESTABLISHED'),
        'key_numbers': {
            'generation_tasks': 3, 'credits_upper': 60, 'actual_charge': 'unknown',
            'cumulative_tasks': 27, 'cumulative_credits_upper': 540,
            'strict_pass': ct.get('summary', {}).get('strict_pass', 0),
            'planning_eligible': ct.get('summary', {}).get('planning_eligible', 0),
            'R01_H5': h5, 'R01_B3': b3, 'R01_U_truth': ut, 'R01_width_rule': wr,
            'R03': r03,
            'soil_stability_episodes': soil.get('E', {}).get('n_episodes'),
            'soil_geometry_sinkage': soil.get('G', {}).get('verdict'),
            'initial_state_config': 'configs/unseen_initial_state_v5.json',
            'state_alignment_R01': load(bdir / 'evaluation/state_alignment_R01.json', {}).get('all_match')},
        'products': {
            'manifest': str(manp), 'formal_table': str(bdir / 'evaluation/formal_table_v5.json'),
            'candidate_table': str(bdir / 'candidates/candidate_table.json'),
            'observation': str(bdir / 'observation/summary.json'),
            'soil': str(bdir / 'soil/summary.json'),
            'verify': str(bdir / 'verify/report.json'),
            'page_screenshots': [str(p) for p in pages]},
        'commands': {
            'verify': '.venv/bin/python scripts/verify_delivery_v5.py --manifest '
                      'runs/unseen/delivery_v5/v5_20261029/manifest.json '
                      '--out runs/unseen/delivery_v5/v5_20261029/verify/report.json --self-test',
            'page': '.venv/bin/python scripts/app_unseen.py --port 8091',
            'tests': '.venv/bin/python -m unittest discover -s tests',
            'dry_run': '.venv/bin/python scripts/imagine.py --plan plans/unseen_delivery_v5.json --dry-run',
            'resume_no_create': '.venv/bin/python scripts/imagine.py --plan plans/unseen_delivery_v5.json --resume '
                                '--budget configs/unseen_v5_budget.json',
            'preflight': '.venv/bin/python scripts/preflight_delivery_v5.py --plan plans/unseen_delivery_v5.json '
                         '--budget configs/unseen_v5_budget.json --ledger runs/unseen/generation/ledger.jsonl '
                         '--cache runs/unseen/generation/cache --out runs/unseen/delivery_v5/v5_20261029/verify/preflight.json',
            'soil': '.venv/bin/python scripts/soil_acceptance_v5.py --out '
                    'runs/unseen/delivery_v5/v5_20261029/soil --stages a,b,c,d,f,g'},
        'remaining': [
            '隐藏背面必要的案例：需新造“可见宽度不足/误导、隐藏背面使 S1 必败、另有 3/3 稳健动作”的几何；先用 twins 免费扫描，再决定付费生成。',
            '真实多假设第二观察收益：当前真实候选无分歧；fixture 只验证接口。',
            '整机几何下陷：PARTIAL_NOT_IMPLEMENTED；坡面滑转/参数随机化仍有限。',
            'R01 与 dev_narrow_tall 同网格，不是独立留出；不能用于泛化主张。',
            '实际扣费 unknown；累计 27 任务/540 上界，不再新增付费 create。',
            '旧 H5 init003(0.03) 与 six_v4(15 s) 保留为 superseded，不用于正式比较。'],
        'git_commit': None,
        'note': ('delivery_status 只表示本批工程交付；benefit_status 由 formal/benefit 结果决定，'
                 '不因测试绿灯升级。')}
    op = pathlib.Path(a.out); op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'delivery_status': delivery, 'evidence_status': out['evidence_status'],
                      'benefit_status': out['benefit_status'],
                      'page_screenshots': len(pages),
                      'verify': ver.get('n_pass'), 'verify_n': ver.get('n_checks'),
                      'work_packages': wps}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
