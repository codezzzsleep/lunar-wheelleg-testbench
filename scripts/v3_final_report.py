"""生成单篇最终报告（docs/V3_FINAL_REPORT.md），数字全部来自实际产物。

  python scripts/v3_final_report.py --protocol plans/v3_protocol.json
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def jl(p, d=None):
    p = pathlib.Path(p)
    return json.loads(p.read_text()) if p.is_file() else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', default='plans/v3_protocol.json')
    a = ap.parse_args()
    proto = jl(ROOT / a.protocol, {})
    res = jl(ROOT / 'runs/v3/report/v3_results.json', {})
    sel = jl(ROOT / 'runs/v3/selected.json', {})
    la = jl(ROOT / 'runs/v3/look_again/index.json', {})
    media = jl(ROOT / 'media/v3/manifest.json', {})
    summ = res.get('summary', {})
    herr = res.get('hidden_error', {})
    funnel = sel.get('funnel', {})
    oc = summ.get('outcomes', {})
    pairs = summ.get('pairs', [])
    L = []
    L.append('# v3 最终报告：真实扫描岩石上，Lux3D 隐藏几何是否改善隐藏区理解与行动\n')
    L.append('> 单篇报告。当前状态只看 `docs/CURRENT_STATUS.md`；本文件是结果与解释，不是状态文档。\n')
    L.append('## 0 主问题的回答\n')
    L.append(f"- 完成双枪执行的状态：**{summ.get('n_executed_states', 0)}** 个"
             f"（FULL 与 OBS_ONLY 从同一个 S0 各执行一次）。")
    L.append(f"- 三结局：FULL {oc.get('FULL', {})}；OBS_ONLY {oc.get('OBS_ONLY', {})}。")
    L.append(f"- FULL 更好 {summ.get('FULL_better_than_OBS', 0)} 个；"
             f"OBS_ONLY 更好 {summ.get('OBS_better_than_FULL', 0)} 个；"
             f"结局相同 {summ.get('same_outcome', 0)} 个。")
    L.append(f"- 风险低估（FULL 预演安全、真值失败）{summ.get('risk_underestimate', 0)}；"
             f"过度保守（FULL 安全停下、OBS 能通行）{summ.get('over_conservative', 0)}。\n")
    L.append('## 1 口径（先冻结，再看结果）\n')
    L.append('- 主比较：同一状态、同一公共观测几何、同一栅格与配置，'
             'FULL = V ∪ (生成父候选 ∩ 未知区)，OBS_ONLY = V（逐体素同一个数组）。')
    L.append('- 取消旧形状关：IoU≥0.85 / P95≤8% / 融合 strict 不再是准入条件；'
             '只检查数据有效、放置正确、观测不被覆盖、自由区不被占据、消融只删未知区。')
    L.append('- 隐藏敏感筛选只用完整真值：真值规划与观测规划动作不同，或两者在真值上的三结局不同；'
             '且完整真值至少有一条实测通行动作。')
    L.append('- 决策：候选级预演矩阵 → 多数票（≥⌊n/2⌋+1）→ 预登记代价最低；'
             '附加最坏规则（n/n）与固定首候选 A1。')
    L.append('- 执行：FULL/OBS_ONLY 各自从同一个 S0 恢复到同一真值场景、独立执行，不 reset、不多给时间。\n')
    L.append('## 2 数据与方法\n')
    L.append(f"- 来源池：Poly Haven CC0 真实摄影测量扫描件，池上限 "
             f"{proto.get('grid', {}).get('max_screen_states', 48)} 状态网格，"
             f"主网格 {len(proto.get('grid', {}).get('rocks', []))} 块石头 × "
             f"{len(proto.get('grid', {}).get('levels', []))} 个 H/r 档 × "
             f"{len(proto.get('grid', {}).get('views', []))} 个首视角。")
    L.append(f"- 高度档 H/r = {proto.get('assets', {}).get('levels_hr')}（轮半径 "
             f"{proto.get('assets', {}).get('wheel_radius_m')} m）。"
             f"初始 0.6/1.0/1.4 档实测对现有轮式平台不产生接触，"
             f"按 §4.4 的能力标定改档，改动发生在任何生成之前。")
    L.append(f"- 配准：24 朝向粗搜索 + 投影式多尺度鲁棒 ICP + 局部坐标下降；"
             f"输出唯一矩阵，评估/导出/融合/碰撞共用。已知答案："
             + _ka_text() + '。')
    L.append(f"- 融合：栅格只由公共观测决定（pitch {proto.get('visibility', {}).get('pitch_m')} m），"
             'V 与候选无关、一次落盘并哈希绑定；消融只删 U∩P，之后不做任何清理/补洞。')
    L.append(f"- 碰撞：占据按 {proto.get('collision', {}).get('box_downsample')}× 降采样到 "
             f"{proto.get('collision', {}).get('box_pitch_m')} m 后做 box union；"
             '不以 IoU 0.95 作准入。\n')
    L.append('## 3 筛选漏斗（真实规模）\n')
    L.append('| 项 | 值 |')
    L.append('| --- | --- |')
    for k in ('n_pool_rocks', 'n_states_planned', 'n_states_captured', 'n_complete_feasible',
              'n_hidden_sensitive', 'n_selected'):
        if k in funnel:
            L.append(f'| {k} | {funnel[k]} |')
    L.append(f"| 选中岩石 | {', '.join(funnel.get('rocks_in_selection', []))} |")
    L.append(f"| 分层 | {funnel.get('layers', {})} |")
    L.append(f"| 排除原因 | {funnel.get('exclusions', {})} |\n")
    L.append('## 4 主结果：FULL vs OBS_ONLY\n')
    L.append('| 状态 | H(m) | 真值选择 | 观测选择 | FULL 动作 | FULL 结局 | OBS 动作 | OBS 结局 |')
    L.append('| --- | --- | --- | --- | --- | --- | --- | --- |')
    for s in res.get('states', []):
        if not s.get('arms'):
            continue
        sc = s.get('screen') or {}
        ar = s['arms']
        L.append(f"| {s['state_id']} | {s['H']:.3f} | "
                 f"{(sc.get('truth_plan') or {}).get('chosen')} | "
                 f"{(sc.get('obs_plan') or {}).get('chosen')} | "
                 f"{ar['FULL'].get('chosen')} | "
                 f"{(ar['FULL'].get('execution') or {}).get('outcome')} | "
                 f"{ar['OBS_ONLY'].get('chosen')} | "
                 f"{(ar['OBS_ONLY'].get('execution') or {}).get('outcome')} |")
    L.append('')
    L.append('### 4.1 多数 / 最坏 / 首候选\n')
    L.append('- 多数：上表 FULL/OBS_ONLY 列即多数规则（阈值 ⌊n/2⌋+1）。')
    L.append('- 最坏与首候选复用同一候选级矩阵；对应汇总在 '
             '`runs/v3/report/v3_results.json` 的每状态 `arms` 与 `decision/matrix_*.jsonl`。')
    L.append('- n_tasks / n_unique_geometries 逐状态记录在决策记录里；'
             '相同几何只算一票，任务分母保留。\n')
    L.append('## 5 隐藏区误差（候选分布）\n')
    for k, v in herr.items():
        if k == 'n_rows':
            L.append(f'- 候选-状态行数：{v}')
        elif v:
            L.append(f'- {k}: {v}')
    L.append('\nOBS_ONLY 没有物体的格在物理规划中等同可通行地面；顶面计分按公共地面高处理，'
             '并另报"无隐藏表面"比例。空预测仍承担遗漏误差。\n')
    L.append('## 6 再看一眼（诊断子集）\n')
    if la.get('rows'):
        for r in la['rows']:
            if 'error' in r:
                L.append(f"- {r['state_id']}: observation_failure（{r['error']}）")
            else:
                L.append(f"- {r['state_id']}: A({r['A']['chosen']}→{r['A']['outcome']}) "
                         f"B({r['B']['chosen']}→{r['B']['outcome']}) "
                         f"C({r['C']['chosen']}→{r['C']['outcome']})；"
                         f"信息增量 {r['info_gain_A_to_B']}；净价值 {r['net_value_B_vs_C']}")
    else:
        L.append('- 本批未执行（记录为 observation_failure 或未运行，不伪造信息收益）。')
    L.append('')
    L.append('## 7 作品与复现\n')
    L.append(f"- 五画面页面：`media/v3/page/index.html`；素材 {len(media.get('files', []))} 个 mp4，"
             f"{media.get('resolution')}@{media.get('fps')} fps。")
    L.append('- 轻量包：`dist/v3_bundle/`（≤300 MiB，含离线演示与缓存重仿真入口；默认不联网）。')
    L.append('- 复现步骤见 `dist/v3_bundle/README.md` 与根目录 `README.md` 的 v3 一节。\n')
    L.append('## 8 错误分层与局限\n')
    L.append('- 管线错误（加载/渲染/度量）与机器人物理失败分开记；未完成不缩分母。')
    L.append('- 已知局限：单视角 + 光滑正面的配准存在沿面滑动歧义（见已知答案记录）；'
             'Lux3D 图像到 3D 的隐藏面是先验而非测量；月壤是半经验/受限模型，不是真实月壤。')
    L.append('- 生成过程没有界面录屏（无头 API）：以真实 task_id/时间线/上传图与返回资产为证，'
             '不伪造实时录屏。\n')
    L.append('## 9 结论\n')
    L.append(_conclusion(summ))
    out = ROOT / 'docs/V3_FINAL_REPORT.md'
    out.write_text('\n'.join(L) + '\n')
    print(json.dumps({'out': str(out), 'n_states': summ.get('n_executed_states')},
                     ensure_ascii=False))


def _ka_text():
    ka = None
    for p in (ROOT / 'runs/v3/states').glob('*/registration/known_answer/known_answer.json'):
        ka = json.loads(p.read_text())
        break
    if not ka:
        return '未运行'
    se = ka.get('surface_error_mm', {})
    return (f"尺度误差 {ka.get('scale_error_pct')}%、旋转误差 {ka.get('rotation_error_deg')}°、"
            f"表面 p95 {se.get('p95')} mm（pass={ka.get('pass')}；单视角光滑正面存在滑动歧义）")


def _conclusion(summ):
    f = summ.get('FULL_better_than_OBS', 0)
    o = summ.get('OBS_better_than_FULL', 0)
    n = summ.get('n_executed_states', 0)
    if n == 0:
        return ('本批没有完成双枪执行，结论为 inconclusive_pipeline；'
                '工程部分（共同观测、匹配消融、配准、碰撞、执行链）已可运行并被逐项检查。')
    if f > o:
        return (f'在已完成的 {n} 个隐藏敏感状态上，加入生成隐藏几何的 FULL 臂结局更好 '
                f'{f} 次、更差 {o} 次。方向上支持"补上隐藏几何有助于行动选择"，'
                '但样本规模不足以声称统计显著，且必须与逐候选的隐藏误差分布一起读。')
    if o > f:
        return (f'在已完成的 {n} 个隐藏敏感状态上，OBS_ONLY 结局更好 {o} 次、FULL 更好 {f} 次。'
                '本批数据不支持"加入生成隐藏几何改善行动结局"：多数情况下，'
                'Lux3D 补出的背面让候选显得比真值更难过，策略因此过度保守。'
                '这与上一轮"候选过于悲观"的观察一致，但这是本批真实扫描资产上的独立证据。')
    return (f'在已完成的 {n} 个隐藏敏感状态上，两臂结局无差异（FULL 更好 {f}、OBS 更好 {o}）。'
            '隐藏几何带来的信息没有转化为行动收益；需要在更难的隐藏敏感状态上重复。')


if __name__ == '__main__':
    main()
