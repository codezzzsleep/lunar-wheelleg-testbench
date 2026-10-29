"""
V6 工作包 B：原始 H5 预测—真值误差表（复用 V5 记录，不重跑仿真）。

输入：
  H5_R01_face12k/rehearsal.jsonl  候选上的逐动作预测
  H5_R01_face12k/execution.jsonl  真值 L2/R1/A0
  six_R01_v5/records.jsonl        真值 S1（U_truth / 宽度规则）
输出：
  prediction_audit/prediction_audit.json
  prediction_audit/action_confusion.csv
  prediction_audit/summary.md

只做已存在记录的交叉表；缺真值的动作标 not_run，不补 0。
"""
import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
C_FAIL, C_ABORT = 60.0, 40.0


def _cost(r):
    if r.get('success'):
        return float(r.get('t_end') or 0.0)
    return float(C_ABORT if r.get('abort') else C_FAIL)


def _key(r):
    return (r.get('option'), r.get('seed'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', default='runs/unseen/delivery_v5/v5_20261029')
    ap.add_argument('--out', default='runs/unseen/delivery_v6/v6_20261029/prediction_audit')
    a = ap.parse_args()
    b = pathlib.Path(a.batch)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pred = [json.loads(l) for l in open(b / 'evaluation/H5_R01_face12k/rehearsal.jsonl')]
    truth = [json.loads(l) for l in open(b / 'evaluation/H5_R01_face12k/execution.jsonl')]
    six = [json.loads(l) for l in open(b / 'evaluation/six_R01_v5/records.jsonl')]
    # 真值 S1 来自同一真值、同一初态的 U_truth 执行
    truth_s1 = [r for r in six if r.get('phase') == 'execution'
                and r.get('method') == 'U_truth' and r.get('option') == 'S1']
    tmap = {_key(r): r for r in truth}
    for r in truth_s1:
        tmap.setdefault(_key(r), r)
    pmap = {_key(r): r for r in pred}
    rows = []
    actions = sorted({r.get('option') for r in pred} | {k[0] for k in tmap})
    for o in actions:
        for sd in (0, 1, 2):
            p = pmap.get((o, sd)); t = tmap.get((o, sd))
            if not p and not t:
                continue
            rows.append({
                'option': o, 'seed': sd,
                'predicted': None if not p else {
                    'success': p.get('success'), 'reason': p.get('reason'),
                    't_end': p.get('t_end'), 'cost': round(_cost(p), 3),
                    'contact': p.get('contact')},
                'truth': None if not t else {
                    'success': t.get('success'), 'reason': t.get('reason'),
                    't_end': t.get('t_end'), 'cost': round(_cost(t), 3),
                    'final_x': t.get('final_x'), 'contact': t.get('contact')},
                'false_safe': bool(p and t and p.get('success') and not t.get('success')),
                'false_unsafe': bool(p and t and (not p.get('success')) and t.get('success')),
                'time_residual_s': (round(float(t['t_end']) - float(p['t_end']), 3)
                                    if p and t and p.get('success') and t.get('success') else None),
            })
    # 动作级汇总
    by_action = {}
    for o in actions:
        rr = [r for r in rows if r['option'] == o]
        pp = [r for r in rr if r['predicted']]
        tt = [r for r in rr if r['truth']]
        by_action[o] = {
            'n_pred': len(pp), 'n_truth': len(tt),
            'pred_success': sum(1 for r in pp if r['predicted']['success']),
            'truth_success': sum(1 for r in tt if r['truth']['success']),
            'false_safe': sum(1 for r in rr if r['false_safe']),
            'false_unsafe': sum(1 for r in rr if r['false_unsafe']),
            'pred_mean_cost': round(sum(r['predicted']['cost'] for r in pp) / len(pp), 3) if pp else None,
            'truth_mean_cost': round(sum(r['truth']['cost'] for r in tt) / len(tt), 3) if tt else None,
            'truth_reasons': [r['truth']['reason'] for r in tt],
        }
    # 排序：只对同时有预测/真值的动作
    common = [o for o in actions if by_action[o]['n_pred'] == 3 and by_action[o]['n_truth'] == 3]
    pred_rank = sorted(common, key=lambda o: (by_action[o]['pred_mean_cost'], o))
    truth_rank = sorted(common, key=lambda o: (-by_action[o]['truth_success'],
                                               by_action[o]['truth_mean_cost'], o))
    summary = {
        'schema': 'prediction-audit/v6', 'case': 'R01', 'candidate': 'C_R01_face12k',
        'source': {'prediction': str(b / 'evaluation/H5_R01_face12k/rehearsal.jsonl'),
                   'truth_L2_R1_A0': str(b / 'evaluation/H5_R01_face12k/execution.jsonl'),
                   'truth_S1': str(b / 'evaluation/six_R01_v5/records.jsonl')},
        'truth_sha': 'ae1837cd3114b90e895c9f593704dbda05bf8f717c5179b9cc544ee42b24ebe2',
        'time_limit_s': 30.0,
        'by_action': by_action,
        'predicted_rank_by_mean_cost': pred_rank,
        'truth_rank_by_success_then_cost': truth_rank,
        'false_safe_total': sum(1 for r in rows if r['false_safe']),
        'false_unsafe_total': sum(1 for r in rows if r['false_unsafe']),
        'false_safe_rows': [r for r in rows if r['false_safe']],
        'selected_by_v5': 'L2',
        'selected_truth': {'L2': '2/3', 'S1': '3/3'},
        'findings': {
            'confirmed': [
                'L2 seed0 在候选上预测成功（6.1 s），真值 30.02 s 超时 -> 1 个 false safe。',
                'S1 在候选上预测成功 3/3（均值 6.407 s），真值 3/3（6.54/6.52/6.72 s）-> 方向一致，成功耗时预测偏低约 0.19 s。',
                'L2 预测均值 6.10 s 优于 S1 的 6.407 s（约 0.3 s），V5 因此选 L2；真值上 S1 更稳健。',
            ],
            'supported_by_records': [
                '预测—真值差异集中在 L2 的 seed0，而不是所有动作/所有初态。',
                '真值上 L2 失败是 time_limit（final_x=2.019），不是 tipped；与候选上“更快通过”的预测不一致。',
            ],
            'still_hypothesis': [
                'seed0 的 L2 超时是否由可见面、生成隐藏面、CoACD 新造面或控制启动造成，现有记录没有接触点，不能归因。',
                '不能因为 L2 失败就归因于隐藏背面；需要工作包 B3/E 的接触位置与碰撞保真证据。',
            ],
        },
        'audio_visual': 'prediction_audit/R01_L2_seed0 回放由连续轨迹阶段生成；本表只做数值',
    }
    (out / 'prediction_audit.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    with open(out / 'action_confusion.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['option', 'seed', 'pred_success', 'truth_success', 'false_safe',
                    'false_unsafe', 'pred_t_end', 'truth_t_end', 'truth_reason', 'time_residual_s'])
        for r in rows:
            w.writerow([r['option'], r['seed'],
                        '' if not r['predicted'] else r['predicted']['success'],
                        '' if not r['truth'] else r['truth']['success'],
                        r['false_safe'], r['false_unsafe'],
                        '' if not r['predicted'] else r['predicted']['t_end'],
                        '' if not r['truth'] else r['truth']['t_end'],
                        '' if not r['truth'] else r['truth']['reason'],
                        '' if r['time_residual_s'] is None else r['time_residual_s']])
    md = ['# R01 原始 H5 预测—真值误差（V6 工作包 B）', '',
          f"- candidate: C_R01_face12k; truth: {summary['truth_sha'][:16]}…",
          f"- 假安全 {summary['false_safe_total']} 行；假不安全 {summary['false_unsafe_total']} 行",
          f"- 预测排序: {pred_rank}", f"- 真值排序: {truth_rank}", '',
          '| action | pred success | truth success | false safe | pred mean cost | truth mean cost |',
          '| --- | --- | --- | --- | --- | --- |']
    for o in actions:
        x = by_action[o]
        md.append(f"| {o} | {x['pred_success']}/{x['n_pred']} | {x['truth_success']}/{x['n_truth']} | "
                  f"{x['false_safe']} | {x['pred_mean_cost']} | {x['truth_mean_cost']} |")
    md += ['', '## 已确认', *[f'- {x}' for x in summary['findings']['confirmed']],
           '', '## 仍有假设', *[f'- {x}' for x in summary['findings']['still_hypothesis']]]
    (out / 'summary.md').write_text('\n'.join(md) + '\n')
    print(json.dumps({'false_safe': summary['false_safe_total'],
                      'false_unsafe': summary['false_unsafe_total'],
                      'pred_rank': pred_rank, 'truth_rank': truth_rank,
                      'out': str(out)}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
