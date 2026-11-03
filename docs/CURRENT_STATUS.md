# 当前状态（唯一入口）

> 唯一源表：`runs/v3/report/v3_results.json`　SHA256 `091b4104216279974b424d2ec81270817048bc6e4db4fdcdcd4f6d3f93fe3130`　生成时点 `2026-11-03T15:19:20+0800`
> 三份文档（CURRENT_STATUS / V3_FINAL_REPORT / V3_RESULTS_TABLE）都由该表生成；数字口径见表中 `definitions`。

## 一、当前结论（口径见源表）

| 项 | 值 |
| --- | --- |
| 状态目录 | 48 |
| 已筛选 | 48 |
| 完整真值可通行 | 44 |
| 隐藏敏感 | 23 |
| 入选（计划分母） | 22 |
| 分层 | {"action_only": 18, "none": 25, "action_and_outcome": 5} |

| 计划状态分类 | 数量 |
| --- | --- |
| executed_pair | 14 |
| one_arm_only | 0 |
| not_run | 8 |
| pipeline_failure | 0 |
| invalid_identity | 0 |

### 逐方法结局与误判

| 指标 | FULL | OBS_ONLY |
| --- | --- | --- |
| pass | 12 | 12 |
| safe_stop | 1 | 1 |
| physical_failure | 1 | 1 |
| 风险低估 | 1 | 1 |
| 过度保守 | 1 | 1 |
| 参考未评估 | 0 | 0 |
| 有效执行 | 14 | 14 |

- 有效配对：**14** 个（定义：两臂 decision+execution 齐全、action 与 decision 一致、state_mode=same_scene、同一 state_hash、轨迹可读且首尾时间可核）。
- 结局更好：FULL 0 / OBS_ONLY 0 / 相同 14。
- 这只陈述**当前已测配对计数**，不能据此推出“总体没有变差”或“方法有效”。

| 状态 | FULL | OBS_ONLY | 更好 | FULL 动作 | OBS 动作 |
| --- | --- | --- | --- | --- | --- |
| moon_rock_01_h0v0 | pass | pass | same | R1 | R1 |
| moon_rock_01_h0v1 | pass | pass | same | D1 | D1 |
| moon_rock_01_h2v0 | safe_stop | safe_stop | same | A0 | A0 |
| moon_rock_02_h0v1 | pass | pass | same | R1 | R1 |
| moon_rock_02_h2v0 | pass | pass | same | L2 | R1 |
| moon_rock_02_h2v1 | pass | pass | same | L2 | L2 |
| moon_rock_03_h1v0 | pass | pass | same | R1 | R1 |
| moon_rock_03_h2v1 | pass | pass | same | R1 | R1 |
| moon_rock_04_h0v1 | pass | pass | same | L2 | L2 |
| moon_rock_04_h1v0 | pass | pass | same | R2 | R2 |
| moon_rock_05_h1v0 | pass | pass | same | D1 | D1 |
| moon_rock_05_h1v1 | physical_failure | physical_failure | same | S1 | S1 |
| moon_rock_05_h2v0 | pass | pass | same | R1 | R1 |
| moon_rock_05_h2v1 | pass | pass | same | R2 | R2 |

### 隐藏区误差覆盖

- 覆盖：**1 个状态 / 6 个候选-状态行**；只覆盖有 metrics/summary.json 的状态与候选；未度量状态不在分母里，也不外推。
- 隐藏占据 IoU：n=6，均值 0.011，中位 0.011，范围 [0.009, 0.013]
- 漏填率：n=6，均值 0.989，中位 0.989，范围 [0.987, 0.991]
- 过填率：n=6，均值 0.552，中位 0.562，范围 [0.436, 0.617]
- 沿路径顶面 MAE (mm)：n=6，均值 36.301，中位 35.732，范围 [33.044, 40.073]
- 沿路径顶面 P95 (mm)：n=6，均值 217.000，中位 215.800，范围 [198.600, 236.600]
- 后缘位置误差绝对值 (mm)：n=6，均值 48.000，中位 46.000，范围 [46.000, 56.000]
- 后坡落差误差绝对值 (mm)：n=6，均值 3.333，中位 4.000，范围 [2.000, 4.000]

### 已知答案

- 有实测记录的状态：**2**；无记录状态：**46**（无记录 ≠ 已运行通过）。
- moon_rock_01_h0v0: 尺度误差 0.308%、旋转 2.107°、表面 P95 6.270 mm、pass=True
- moon_rock_02_h0v1: 尺度误差 0.865%、旋转 0.865°、表面 P95 4.508 mm、pass=True

## 二、本批已落实的合同

1. 共同观测 V：栅格只由公共观测决定，V 一次落盘并哈希绑定；`FULL = V ∪ (P∩U)`、`OBS_ONLY = V`（同一数组）；消融后不做清理/补洞；自由区不被占据。
2. 配准：24 朝向粗搜索 + 投影式多尺度鲁棒 ICP + 局部坐标下降；已知答案两个形状通过（见上）。
3. 决策：候选级矩阵 → 多数票（≥⌊n/2⌋+1）→ 预登记代价最低；相同几何只算一票、任务分母保留。
4. 执行：两臂各自 `restore_state(S0, mode=same_scene)` 后独立执行；未完成不缩分母，分类见上表。

## 三、未完成与下一步

- 有效配对只覆盖部分计划状态；其余按 one_arm_only/not_run/pipeline_failure/invalid_identity 分类保留在分母里。
- 隐藏误差只覆盖有 metrics 的状态与候选，不外推。
- 下一步（按 SPEC 优先级）：P0-A 数据发布（凭据受限，先备包）→ §5 全轨迹记录 → V0 逐层追踪与缓存修复 → V1 逐腿三关节控制与 CLIMB/第二技能/软土脱困 → V2 三项成本 → V3 背面敏感 → V4 六候选三支 → V5 20m 连续路线 → A–G/H 生产。

## 四、产物位置

| 产物 | 路径 |
| --- | --- |
| 结果源表 | `runs/v3/report/v3_results.json` |
| 结果 CSV | `runs/v3/report/v3_table.csv` |
| 协议 | `plans/v3_protocol.json` |
| 入口 | `scripts/run_v3.py` |
| 素材包 | `dist/v3_bundle/`（仅旧批次，待按新口径重建） |

# 归档：v2 及更早
v2 的主表与“修复前 H5_F 不检验本方法”的定级保留在 `docs/V2_*.md` 与 `runs/unseen/...`，不参与 v3 分母；其工程结论（融合入口缺陷、组件清理会删壳层、freespace 超限来自体素化）已并入 v3 实现合同。
