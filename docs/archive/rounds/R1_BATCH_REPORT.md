# 《看不见的那一面》R1 收口整改 · 当前报告

基线 `fdd1d447` · 本批在 `main` 上分阶段提交 · 报告只描述**已实跑并留证**的内容。

状态分列：

```json
{"execution_status": "PARTIAL",
 "evidence_status": "PARTIAL",
 "capability_status": "PARTIAL",
 "benefit_status": "NOT_ESTABLISHED"}
```

`execution_status` 部分完成：九条完成标准中，资格门、清单入口、正式矩阵、第二观察、页面、
演示包、生产反例与报告均已实做；`evidence_status` 部分完成：核心结论都有原始产物与哈希，
但 216 键矩阵中的安全放弃分支多于通行分支、且 R01/R02 无合格候选是**经过验证的边界**；
`capability_status` 部分完成：R03 有可通行闭环，R01/R02/R04 在当前严格门下无正式候选；
`benefit_status` 未建立：唯一有合格候选的配置无区分度，候选与规则基线同分。

---

## 1. 用户现在可以怎么用

```bash
# 1) 清单驱动（先校验，缺文件即拒绝；--out 为本批新增接口）
.venv/bin/python scripts/v7_run_manifest.py --manifest plans/r1_runs/input_R03_close.json --check
.venv/bin/python scripts/r1_pipeline.py --manifest plans/r1_runs/input_R03_close.json --dry-run
.venv/bin/python scripts/r1_pipeline.py --manifest plans/r1_runs/input_R03_close.json --out <目录>

# 2) 唯一资格门（单候选）
.venv/bin/python scripts/candidate_qualification.py --candidate V7_R03_s1 \
  --two-view runs/.../fusion_diagnostics/tvocc_R03_s1_v3 \
  --observation runs/unseen/recovery_r3/obs_R03 --case cases/unseen_v1/R03.json

# 3) S0–S4 已知答案自检
.venv/bin/python scripts/v7_stage_fixture.py --observation <obs> --entity <该配置真值网格> --out <目录>

# 4) 共同状态采集 → 正式矩阵
.venv/bin/python scripts/v7_acquire_states.py --plan plans/r1_states_plan.json --out <目录>
.venv/bin/python scripts/v7_common_matrix.py --plan plans/r1_states_plan.json \
  --states <状态目录> --out <矩阵目录> --config R03_s1

# 5) 页面（正式闭环 / 候选预演分开）与演示包
.venv/bin/python scripts/v7_server.py --port 8809
bash demo/r1_r03_two_view/run_demo.sh /tmp/demo_new
```

---

## 2. 资格表（唯一正式门，多格式统一判定）

| 候选 | 可见 IoU | 可见 P95 | 自由空间 | 碰撞 IoU | 观测匹配 | 正式资格 |
| --- | --- | --- | --- | --- | --- | --- |
| V7_R01_s1（重配准） | 0.8856 | 1.002 mm | **0.0647** ✗ | 0.9365 ✗ | ✅ | disqualified |
| V7_R02_s1（重配准，0.9） | 0.9788 | 1.376 mm | **0.0649** ✗ | 0.9922 ✅ | ✅ | disqualified |
| **V7_R03_s1（两视角）** | **0.9781** | **1.550 mm** | **0.0380** ✅ | **0.9833** ✅ | ✅ | **qualified** |
| V7_R04_s1 | — | — | — | — | — | not_measured（无融合记录） |
| B2_F（R03 盒+观测约束） | 0.9737 | 9.736 mm ✗ | 0.0637 ✗ | — | ✅ | disqualified |
| B3_F（R03 镜像+观测约束） | 0.9650 | 13.655 mm ✗ | 0.0538 ✗ | — | ✅ | disqualified |
| 真值 fixture（正对照） | 0.9873 | 0.995 mm | 0.0295 ✅ | 0.9844 ✅ | ✅ | **qualified** |

**要点**：正对照证明资格门能通过，不是一律拒绝；四对象中只有 R03 具备正式资格。

---

## 3. S0–S4 表示链自检（R01，2.5 mm）

| 层 | 可见 IoU | 可见 P95 | 自由空间 | 通过 |
| --- | --- | --- | --- | --- |
| S0 原实体 | 1.0000 | 0.000 | 0.000 | ✅ |
| S1 导出加载 | 1.0000 | 0.000 | 0.000 | ✅ |
| S2 占据+表面 | 0.9838 | 0.806 | 0.0376 | ✅ |
| S3 自由空间约束 | 0.9873 | 0.995 | 0.0295 | ✅ |
| S4 完整融合（修正壳层后） | 0.9873 | 0.995 | 0.0295 | ✅ |

自检发现并修复了一个**链级缺陷**：原壳层无条件加厚，导致真值自身 S4 自由空间 0.0642 不过；
改为"壳层只补父先验缺口"后通过。该修复进入配置身份（`shell_gap_fill`）。

---

## 4. 正式矩阵：216 键（4 配置 × 3 土壤 × 3 新验证 seed × 6 方法）

| 配置 | B0 盲走 | B1 高度 | B2_F | B3_F | H5_F | U_truth | 固定 R2 | 宽度规则 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R01@1.0 | 0/9 | 9 A0 | 9 A0 | 9 A0 | 9 A0 | 0/9 | 0/9 | 0/9 |
| R02@0.9 | **9/9** | 9 A0 | 9 A0 | 9 A0 | 9 A0 | 1/9 | 1/9 | **9/9** |
| R03@1.0 | 9/9 | 9/9 | 9 A0 | 9 A0 | **9/9** | 9/9 | 9/9 | 9/9 |
| R04@1.0 | 0/9 | 9 A0 | 9 A0 | 9 A0 | 9 A0 | 0/9 | 0/9 | 6/9 |

合计：**46 通行 / 126 安全放弃 / 44 失败**，216 键无一删除；诊断基线另计 72 行。

**判读**：

- R03 六方法全部通行 → 该配置**无区分度**，不能用于论证方法优劣；
- R02 盲走与宽度规则 9/9，而真值参考仅 1/9、候选方法无候选 → 简单规则在该配置已足够；
- R01、R04 连真值参考都不通行 → 是**动作库/状态的边界**，不是方法差异；
- 候选方法（B2_F/B3_F/H5_F）在 4 个配置里只有 R03 有正式候选，其余按真实 A0 分支执行。

---

## 5. 第二观察消融（同状态、同预算、同土壤）

| 臂 | 决策 | 结果 | 位移 | 观察成本 |
| --- | --- | --- | --- | --- |
| A 单视角（不用第二图） | R1 | ✅ | 3.299 | 已含 |
| B 两视角（用第二图） | R1 | ✅ | 3.299 | 已含 |
| C 从 S0 直接行动 | R1 | ✅ | **3.611** | 0 |

信息价值：**0**（决策与结果都不变）；操作净价值：**不为正**（移动观察少走约 0.31 m）。
两臂均使用采集记录中的验收，未使用 `--skip-acceptance` 覆盖。

---

## 6. 页面与演示包

页面七项浏览器实操（真 DOM 点击）全部通过：已有回放播放/暂停/拖动、选案例发起正式闭环、
打开新 run 回放、UI 与记录一致、安全放弃可见、物理失败（tipped）可见、候选预演标签独立。

演示包在新目录完整运行（退出码 0）：14 项输入身份校验 → 从占据重建 → 碰撞复测
（0.9833/0.504/0.739）→ 新预演 → 决策 R1 → 独立真值执行 → 291 帧轨迹 → 连续回放。
任一步缺失即非零退出。

---

## 7. 修复与撤回（不得只追加新状态）

| 对象 | 处置 | 依据 |
| --- | --- | --- |
| 上一批"四对象候选合格" | **撤回** | 只核对了碰撞；R01/R02 可见自由空间 0.1122/0.1490，R03 旧记录无测量有效性，R04 无可见记录 |
| R01 H5 3/3 正例 | **降级 SUPERSEDED** | 依赖未过资格门的资产 |
| R02 H5 A0 归因"决策器保守" | **撤回** | 实际是无合格候选，A0 是正确回退 |
| 三土壤分别运行 = 跨土壤稳健 | **撤回** | 已改为 planning_soils 全集枚举 + 最坏情形聚合 |
| 第二观察"改变决策"旧结论 | **降级** | 旧结论用 skip-acceptance 强制 usable；新结论为信息价值 0 |
| 壳层公式 | **修正并记入配置身份** | 真值自身 S4 曾不过自由空间 |
| 工程运行能力（闭环、扫描、页面、演示包） | **保留** | 均有本轮实跑证据 |

降级清单见 `verify/superseded.json`（13 项，含文件哈希）。

---

## 8. 仍然缺什么

1. R01/R02 在严格门下**没有正式候选**：重配准后自由空间 0.0647/0.0649；1.25 mm 更细表示
   对照使 R02 候选退化（可见 P95 129 mm、深度中位 285 mm），更细网格救不了它；
2. R03 是唯一合格配置，但六方法同分，**收益不可测**；
3. 第二观察只做了一个状态的三臂对照，不能外推到全部配置；
4. 页面尚未做"多候选 vs 单候选"的可视对照。

以上均为**已验证的边界**，不是未实现的功能。

---

## 9. 资源与账本

| 项 | 值 |
| --- | --- |
| 本批新增付费 create | **0** |
| 历史 500 积分授权 | 不变 |
| 实际扣费 | **unknown**（外部对账项，不阻塞工程收口） |
| 计算分工 | 本机（验证/报告）+ 远程沙箱（融合/测量/矩阵） |

---

## 10. 审查索引

| 结论 | 原始记录 |
| --- | --- |
| 资格门判定 | `runs/unseen/delivery_v7/v7_20261030_r1/verify/gate_*.json`、`gate_evidence.json` |
| 表示链自检 | `fixture_R01_gapfill/fixture_report.json` |
| 共同状态 | `common_states/<config>/<soil>/seed<N>/acquisition.json` |
| 正式矩阵 | `matrix_all/matrix.jsonl`、`matrix_all/summary.json` |
| 第二观察消融 | `evaluation/ablation_second_view_v2/ablation.json` |
| 页面验收 | `verify/page_acceptance_v2.json` |
| 生产反例 | `verify/negatives_close.json`、`negatives_qualification.json` |
| 演示包 | `demo/r1_r03_two_view/verification/full_run/` |
| 降级清单 | `verify/superseded.json` |
| 报告事实快照 | `verify/report_facts.json` |
