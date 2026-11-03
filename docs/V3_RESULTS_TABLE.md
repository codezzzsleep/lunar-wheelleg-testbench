# v3 结果表（由唯一源表生成）

> 唯一源表：`runs/v3/report/v3_results.json`　SHA256 `f884bb48a68d1e42b35bb7ca2de15f17069375dc6e5dbba84a51b435a742c9b6`　生成时点 `2026-11-03T13:29:39+0800`
> 三份文档（CURRENT_STATUS / V3_FINAL_REPORT / V3_RESULTS_TABLE）都由该表生成；数字口径见表中 `definitions`。

## 漏斗

| 项 | 值 |
| --- | --- |
| 状态目录 | 48 |
| 已筛选 | 48 |
| 完整真值可通行 | 44 |
| 隐藏敏感 | 23 |
| 入选（计划分母） | 22 |
| 分层 | {"action_only": 18, "none": 25, "action_and_outcome": 5} |

## 分类

| 计划状态分类 | 数量 |
| --- | --- |
| executed_pair | 14 |
| one_arm_only | 0 |
| not_run | 8 |
| pipeline_failure | 0 |
| invalid_identity | 0 |

## 逐方法

| 指标 | FULL | OBS_ONLY |
| --- | --- | --- |
| pass | 12 | 11 |
| safe_stop | 1 | 1 |
| physical_failure | 1 | 2 |
| 风险低估 | 1 | 2 |
| 过度保守 | 1 | 1 |
| 参考未评估 | 0 | 0 |
| 有效执行 | 14 | 14 |

## 配对

- 有效配对：**14** 个（定义：两臂 decision+execution 齐全、action 与 decision 一致、state_mode=same_scene、同一 state_hash、轨迹可读且首尾时间可核）。
- 结局更好：FULL 1 / OBS_ONLY 0 / 相同 13。
- 这只陈述**当前已测配对计数**，不能据此推出“总体没有变差”或“方法有效”。

| 状态 | FULL | OBS_ONLY | 更好 | FULL 动作 | OBS 动作 |
| --- | --- | --- | --- | --- | --- |
| moon_rock_01_h0v0 | pass | pass | same | D1 | D1 |
| moon_rock_01_h0v1 | pass | pass | same | D1 | D1 |
| moon_rock_01_h2v0 | safe_stop | safe_stop | same | A0 | A0 |
| moon_rock_02_h0v1 | pass | pass | same | D1 | D1 |
| moon_rock_02_h2v0 | pass | pass | same | L2 | L2 |
| moon_rock_02_h2v1 | pass | pass | same | D1 | D1 |
| moon_rock_03_h1v0 | pass | pass | same | L2 | L2 |
| moon_rock_03_h2v1 | pass | pass | same | R1 | R1 |
| moon_rock_04_h0v1 | pass | pass | same | L2 | L2 |
| moon_rock_04_h1v0 | pass | physical_failure | FULL | R2 | L2 |
| moon_rock_05_h1v0 | pass | pass | same | D1 | D1 |
| moon_rock_05_h1v1 | physical_failure | physical_failure | same | L2 | L2 |
| moon_rock_05_h2v0 | pass | pass | same | R1 | R1 |
| moon_rock_05_h2v1 | pass | pass | same | R2 | R2 |

## 隐藏误差

- 覆盖：**1 个状态 / 6 个候选-状态行**；只覆盖有 metrics/summary.json 的状态与候选；未度量状态不在分母里，也不外推。
- 隐藏占据 IoU：n=6，均值 0.011，中位 0.011，范围 [0.009, 0.013]
- 漏填率：n=6，均值 0.989，中位 0.989，范围 [0.987, 0.991]
- 过填率：n=6，均值 0.552，中位 0.562，范围 [0.436, 0.617]
- 沿路径顶面 MAE (mm)：n=6，均值 36.301，中位 35.732，范围 [33.044, 40.073]
- 沿路径顶面 P95 (mm)：n=6，均值 217.000，中位 215.800，范围 [198.600, 236.600]
- 后缘位置误差绝对值 (mm)：n=6，均值 48.000，中位 46.000，范围 [46.000, 56.000]
- 后坡落差误差绝对值 (mm)：n=6，均值 3.333，中位 4.000，范围 [2.000, 4.000]

## 逐状态

| 状态 | H(m) | 配对状态 | FULL 动作/结局 | OBS 动作/结局 |
| --- | --- | --- | --- | --- |
| moon_rock_01_h0v0 | 0.120 | executed_pair | D1/pass | D1/pass |
| moon_rock_01_h0v1 | 0.120 | executed_pair | D1/pass | D1/pass |
| moon_rock_01_h2v0 | 0.224 | executed_pair | A0/safe_stop | A0/safe_stop |
| moon_rock_02_h0v1 | 0.120 | executed_pair | D1/pass | D1/pass |
| moon_rock_02_h2v0 | 0.224 | executed_pair | L2/pass | L2/pass |
| moon_rock_02_h2v1 | 0.224 | executed_pair | D1/pass | D1/pass |
| moon_rock_03_h1v0 | 0.172 | executed_pair | L2/pass | L2/pass |
| moon_rock_03_h2v1 | 0.224 | executed_pair | R1/pass | R1/pass |
| moon_rock_04_h0v1 | 0.120 | executed_pair | L2/pass | L2/pass |
| moon_rock_04_h1v0 | 0.172 | executed_pair | R2/pass | L2/physical_failure |
| moon_rock_05_h1v0 | 0.172 | executed_pair | D1/pass | D1/pass |
| moon_rock_05_h1v1 | 0.172 | executed_pair | L2/physical_failure | L2/physical_failure |
| moon_rock_05_h2v0 | 0.224 | executed_pair | R1/pass | R1/pass |
| moon_rock_05_h2v1 | 0.224 | executed_pair | R2/pass | R2/pass |
