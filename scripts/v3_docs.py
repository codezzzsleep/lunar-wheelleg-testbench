"""从唯一结果表生成三份文档（同一 report JSON / SHA / 生成时点）。

  python scripts/v3_docs.py --report runs/v3/report/v3_results.json

生成：
  docs/CURRENT_STATUS.md     唯一当前状态（入口）
  docs/V3_FINAL_REPORT.md    单篇最终报告
  docs/V3_RESULTS_TABLE.md   结果表
三份都写同一个 report_sha256 与 generated_at，分母一致；旧版本保留在 git 历史里，
不覆写成“从未出错”。
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def jl(p, d=None):
    p = pathlib.Path(p)
    return json.loads(p.read_text()) if p.is_file() else d


def fmt(x, nd=3):
    if x is None:
        return '—'
    if isinstance(x, float):
        return f'{x:.{nd}f}'
    return str(x)


def stamp(res):
    return (f"> 唯一源表：`runs/v3/report/v3_results.json`　"
            f"SHA256 `{res.get('report_sha256', '—')}`　生成时点 `{res.get('generated_at')}`\n"
            f"> 三份文档（CURRENT_STATUS / V3_FINAL_REPORT / V3_RESULTS_TABLE）都由该表生成；"
            f"数字口径见表中 `definitions`。\n")


def funnel_tbl(res):
    f = res['funnel']
    L = ['| 项 | 值 |', '| --- | --- |']
    L.append(f"| 状态目录 | {f['n_state_dirs']} |")
    L.append(f"| 已筛选 | {f['n_screened']} |")
    L.append(f"| 完整真值可通行 | {f['n_complete_feasible']} |")
    L.append(f"| 隐藏敏感 | {f['n_hidden_sensitive']} |")
    L.append(f"| 入选（计划分母） | {f['n_selected']} |")
    L.append(f"| 分层 | {json.dumps(f['layers'], ensure_ascii=False)} |")
    return '\n'.join(L)


def class_tbl(res):
    c = res['classification']
    L = ['| 计划状态分类 | 数量 |', '| --- | --- |']
    for k in ('executed_pair', 'one_arm_only', 'not_run', 'pipeline_failure',
              'invalid_identity'):
        L.append(f'| {k} | {c.get(k, 0)} |')
    return '\n'.join(L)


def method_tbl(res):
    pm = res['per_method']
    keys = [('pass', 'pass'), ('safe_stop', 'safe_stop'),
            ('physical_failure', 'physical_failure'),
            ('risk_underestimate', '风险低估'), ('over_conservative', '过度保守'),
            ('reference_unassessed', '参考未评估'), ('n_valid_runs', '有效执行')]
    L = ['| 指标 | FULL | OBS_ONLY |', '| --- | --- | --- |']
    for k, name in keys:
        L.append(f"| {name} | {pm['FULL'].get(k, 0)} | {pm['OBS_ONLY'].get(k, 0)} |")
    return '\n'.join(L)


def compare_tbl(res):
    mc = res['method_compare']
    b = mc['better']
    L = [f"- 有效配对：**{mc['n_pairs']}** 个（定义：{res['definitions']['executed_pair']}）。",
         f"- 结局更好：FULL {b['FULL']} / OBS_ONLY {b['OBS_ONLY']} / 相同 {b['same']}。",
         "- 这只陈述**当前已测配对计数**，不能据此推出“总体没有变差”或“方法有效”。"]
    if mc['rows']:
        L.append('')
        L.append('| 状态 | FULL | OBS_ONLY | 更好 | FULL 动作 | OBS 动作 |')
        L.append('| --- | --- | --- | --- | --- | --- |')
        for r in mc['rows']:
            L.append(f"| {r['state_id']} | {r['FULL']} | {r['OBS_ONLY']} | {r['better']} "
                     f"| {r['FULL_action']} | {r['OBS_action']} |")
    return '\n'.join(L)


def hidden_tbl(res):
    h = res['hidden_error']
    L = [f"- 覆盖：**{h['n_states']} 个状态 / {h['n_candidate_rows']} 个候选-状态行**；"
         f"{h['coverage_note']}。"]
    for key, name in (('A_iou', '隐藏占据 IoU'), ('A_missing', '漏填率'),
                      ('A_overfill', '过填率'), ('B_mae', '沿路径顶面 MAE (mm)'),
                      ('B_p95', '沿路径顶面 P95 (mm)'),
                      ('C_rear_abs', '后缘位置误差绝对值 (mm)'),
                      ('C_drop_abs', '后坡落差误差绝对值 (mm)')):
        s = h.get(key)
        if s:
            L.append(f"- {name}：n={s['n']}，均值 {fmt(s['mean'])}，中位 {fmt(s['median'])}，"
                     f"范围 [{fmt(s['min'])}, {fmt(s['max'])}]")
        else:
            L.append(f"- {name}：未度量")
    return '\n'.join(L)


def ka_tbl(res):
    ka = res['known_answer']
    L = [f"- 有实测记录的状态：**{ka['n_measured']}**；无记录状态："
         f"**{ka['n_states_without_record']}**（无记录 ≠ 已运行通过）。"]
    for r in ka['rows'][:8]:
        L.append(f"- {r['state_id']}: 尺度误差 {fmt(r.get('scale_error_pct'))}%、"
                 f"旋转 {fmt(r.get('rotation_error_deg'))}°、表面 P95 "
                 f"{fmt(r.get('surface_p95_mm'))} mm、pass={r.get('pass')}")
    return '\n'.join(L)


def state_tbl(res):
    L = ['| 状态 | H(m) | 配对状态 | FULL 动作/结局 | OBS 动作/结局 |',
         '| --- | --- | --- | --- | --- |']
    for s in res['states']:
        if s['pair_status'] == 'not_run':
            continue
        L.append(f"| {s['state_id']} | {fmt(s['H'])} | {s['pair_status']} | "
                 f"{s['FULL'].get('action') or '—'}/{s['FULL'].get('outcome') or '—'} | "
                 f"{s['OBS_ONLY'].get('action') or '—'}/{s['OBS_ONLY'].get('outcome') or '—'} |")
    return '\n'.join(L)


def build_status(res):
    L = ['# 当前状态（唯一入口）\n', stamp(res), '## 一、当前结论（口径见源表）\n',
         funnel_tbl(res), '', class_tbl(res), '', '### 逐方法结局与误判\n',
         method_tbl(res), '', compare_tbl(res), '', '### 隐藏区误差覆盖\n', hidden_tbl(res),
         '', '### 已知答案\n', ka_tbl(res), '',
         '## 二、本批已落实的合同\n',
         '1. 共同观测 V：栅格只由公共观测决定，V 一次落盘并哈希绑定；'
         '`FULL = V ∪ (P∩U)`、`OBS_ONLY = V`（同一数组）；消融后不做清理/补洞；'
         '自由区不被占据。',
         '2. 配准：24 朝向粗搜索 + 投影式多尺度鲁棒 ICP + 局部坐标下降；'
         '已知答案两个形状通过（见上）。',
         '3. 决策：候选级矩阵 → 多数票（≥⌊n/2⌋+1）→ 预登记代价最低；'
         '相同几何只算一票、任务分母保留。',
         '4. 执行：两臂各自 `restore_state(S0, mode=same_scene)` 后独立执行；'
         '未完成不缩分母，分类见上表。',
         '',
         '## 三、未完成与下一步\n',
         '- 有效配对只覆盖部分计划状态；其余按 one_arm_only/not_run/pipeline_failure/'
         'invalid_identity 分类保留在分母里。',
         '- 隐藏误差只覆盖有 metrics 的状态与候选，不外推。',
         '- 下一步（按 SPEC 优先级）：P0-A 数据发布（凭据受限，先备包）→ §5 全轨迹记录 → '
         'V0 逐层追踪与缓存修复 → V1 逐腿三关节控制与 CLIMB/第二技能/软土脱困 → '
         'V2 三项成本 → V3 背面敏感 → V4 六候选三支 → V5 20m 连续路线 → A–G/H 生产。',
         '',
         '## 四、产物位置\n',
         '| 产物 | 路径 |', '| --- | --- |',
         '| 结果源表 | `runs/v3/report/v3_results.json` |',
         '| 结果 CSV | `runs/v3/report/v3_table.csv` |',
         '| 协议 | `plans/v3_protocol.json` |',
         '| 入口 | `scripts/run_v3.py` |',
         '| 素材包 | `dist/v3_bundle/`（仅旧批次，待按新口径重建） |',
         '',
         '# 归档：v2 及更早',
         'v2 的主表与“修复前 H5_F 不检验本方法”的定级保留在 `docs/V2_*.md` 与 '
         '`runs/unseen/...`，不参与 v3 分母；其工程结论（融合入口缺陷、组件清理会删壳层、'
         'freespace 超限来自体素化）已并入 v3 实现合同。']
    return '\n'.join(L) + '\n'


def build_report(res):
    L = ['# 《看不见的那一面》v3 结果报告（由唯一源表生成）\n', stamp(res),
         '## 0 回答\n',
         f"- 有效配对 **{res['method_compare']['n_pairs']}** 个；"
         f"FULL 更好 {res['method_compare']['better']['FULL']}、"
         f"OBS_ONLY 更好 {res['method_compare']['better']['OBS_ONLY']}、"
         f"相同 {res['method_compare']['better']['same']}。",
         f"- 风险低估：FULL {res['per_method']['FULL']['risk_underestimate']}、"
         f"OBS_ONLY {res['per_method']['OBS_ONLY']['risk_underestimate']}；"
         f"过度保守：FULL {res['per_method']['FULL']['over_conservative']}、"
         f"OBS_ONLY {res['per_method']['OBS_ONLY']['over_conservative']}。",
         f"- 隐藏误差覆盖 {res['hidden_error']['n_states']} 状态 / "
         f"{res['hidden_error']['n_candidate_rows']} 候选行；"
         "生成先验的隐藏区是否可用，以该分布为准，不以单次成功推断。",
         '',
         '## 1 筛选漏斗\n', funnel_tbl(res), '',
         '## 2 计划状态分类\n', class_tbl(res), '',
         '## 3 逐方法结局与误判\n', method_tbl(res), '',
         '## 4 配对比较\n', compare_tbl(res), '',
         '## 5 隐藏区误差\n', hidden_tbl(res), '',
         '## 6 已知答案\n', ka_tbl(res), '',
         '## 7 逐状态表\n', state_tbl(res), '',
         '## 8 错误分层与限制\n',
         '- pipeline_failure / provider_unavailable / not_run / invalid_identity 独立标记，'
         '不并入物理结局。',
         '- 未完成不缩分母；本报告不把“合同断言通过”当作“隐藏几何被理解对了”。',
         '- 单视角 + 光滑正面存在配准滑动歧义；Lux3D 隐藏面是先验不是测量；'
         '月壤是半经验受限模型，不是真实月壤。',
         '',
         '## 9 可复现\n',
         '源表由 `scripts/v3_report.py` 从逐状态原始记录重算；'
         '文档由 `scripts/v3_docs.py` 生成；两者都写 report SHA。']
    return '\n'.join(L) + '\n'


def build_table(res):
    L = ['# v3 结果表（由唯一源表生成）\n', stamp(res), '## 漏斗\n', funnel_tbl(res), '',
         '## 分类\n', class_tbl(res), '', '## 逐方法\n', method_tbl(res), '',
         '## 配对\n', compare_tbl(res), '', '## 隐藏误差\n', hidden_tbl(res), '',
         '## 逐状态\n', state_tbl(res)]
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', default='runs/v3/report/v3_results.json')
    a = ap.parse_args()
    res = jl(ROOT / a.report)
    if not res:
        raise SystemExit(f'找不到结果表 {a.report}')
    side = ROOT / (a.report + '.sha256')
    if side.is_file():
        res['report_sha256'] = side.read_text().strip()
    docs = ROOT / 'docs'
    docs.mkdir(parents=True, exist_ok=True)
    (docs / 'CURRENT_STATUS.md').write_text(build_status(res))
    (docs / 'V3_FINAL_REPORT.md').write_text(build_report(res))
    (docs / 'V3_RESULTS_TABLE.md').write_text(build_table(res))
    print(json.dumps({'report_sha256': res.get('report_sha256'),
                      'generated_at': res.get('generated_at'),
                      'docs': ['docs/CURRENT_STATUS.md', 'docs/V3_FINAL_REPORT.md',
                               'docs/V3_RESULTS_TABLE.md']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
