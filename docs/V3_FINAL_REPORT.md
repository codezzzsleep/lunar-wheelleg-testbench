# 《看不见的那一面》v3 结果报告（由唯一源表生成）

> 唯一源表：`runs/v3/report/v3_results.json`　SHA256 `091b4104216279974b424d2ec81270817048bc6e4db4fdcdcd4f6d3f93fe3130`　生成时点 `2026-11-03T15:19:20+0800`
> 三份文档（CURRENT_STATUS / V3_FINAL_REPORT / V3_RESULTS_TABLE）都由该表生成；数字口径见表中 `definitions`。

## 0 回答

- 有效配对 **14** 个；FULL 更好 0、OBS_ONLY 更好 0、相同 14。
- 风险低估：FULL 1、OBS_ONLY 1；过度保守：FULL 1、OBS_ONLY 1。
- 隐藏误差覆盖 1 状态 / 6 候选行；生成先验的隐藏区是否可用，以该分布为准，不以单次成功推断。

## 1 筛选漏斗

| 项 | 值 |
| --- | --- |
| 状态目录 | 48 |
| 已筛选 | 48 |
| 完整真值可通行 | 44 |
| 隐藏敏感 | 23 |
| 入选（计划分母） | 22 |
| 分层 | {"action_only": 18, "none": 25, "action_and_outcome": 5} |

## 2 计划状态分类

| 计划状态分类 | 数量 |
| --- | --- |
| executed_pair | 14 |
| one_arm_only | 0 |
| not_run | 8 |
| pipeline_failure | 0 |
| invalid_identity | 0 |

## 3 逐方法结局与误判

| 指标 | FULL | OBS_ONLY |
| --- | --- | --- |
| pass | 12 | 12 |
| safe_stop | 1 | 1 |
| physical_failure | 1 | 1 |
| 风险低估 | 1 | 1 |
| 过度保守 | 1 | 1 |
| 参考未评估 | 0 | 0 |
| 有效执行 | 14 | 14 |

## 4 配对比较

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

## 5 隐藏区误差

- 覆盖：**1 个状态 / 6 个候选-状态行**；只覆盖有 metrics/summary.json 的状态与候选；未度量状态不在分母里，也不外推。
- 隐藏占据 IoU：n=6，均值 0.011，中位 0.011，范围 [0.009, 0.013]
- 漏填率：n=6，均值 0.989，中位 0.989，范围 [0.987, 0.991]
- 过填率：n=6，均值 0.552，中位 0.562，范围 [0.436, 0.617]
- 沿路径顶面 MAE (mm)：n=6，均值 36.301，中位 35.732，范围 [33.044, 40.073]
- 沿路径顶面 P95 (mm)：n=6，均值 217.000，中位 215.800，范围 [198.600, 236.600]
- 后缘位置误差绝对值 (mm)：n=6，均值 48.000，中位 46.000，范围 [46.000, 56.000]
- 后坡落差误差绝对值 (mm)：n=6，均值 3.333，中位 4.000，范围 [2.000, 4.000]

## 6 已知答案

- 有实测记录的状态：**2**；无记录状态：**46**（无记录 ≠ 已运行通过）。
- moon_rock_01_h0v0: 尺度误差 0.308%、旋转 2.107°、表面 P95 6.270 mm、pass=True
- moon_rock_02_h0v1: 尺度误差 0.865%、旋转 0.865°、表面 P95 4.508 mm、pass=True

## 7 逐状态表

| 状态 | H(m) | 配对状态 | FULL 动作/结局 | OBS 动作/结局 |
| --- | --- | --- | --- | --- |
| moon_rock_01_h0v0 | 0.120 | executed_pair | R1/pass | R1/pass |
| moon_rock_01_h0v1 | 0.120 | executed_pair | D1/pass | D1/pass |
| moon_rock_01_h2v0 | 0.224 | executed_pair | A0/safe_stop | A0/safe_stop |
| moon_rock_02_h0v1 | 0.120 | executed_pair | R1/pass | R1/pass |
| moon_rock_02_h2v0 | 0.224 | executed_pair | L2/pass | R1/pass |
| moon_rock_02_h2v1 | 0.224 | executed_pair | L2/pass | L2/pass |
| moon_rock_03_h1v0 | 0.172 | executed_pair | R1/pass | R1/pass |
| moon_rock_03_h2v1 | 0.224 | executed_pair | R1/pass | R1/pass |
| moon_rock_04_h0v1 | 0.120 | executed_pair | L2/pass | L2/pass |
| moon_rock_04_h1v0 | 0.172 | executed_pair | R2/pass | R2/pass |
| moon_rock_05_h1v0 | 0.172 | executed_pair | D1/pass | D1/pass |
| moon_rock_05_h1v1 | 0.172 | executed_pair | S1/physical_failure | S1/physical_failure |
| moon_rock_05_h2v0 | 0.224 | executed_pair | R1/pass | R1/pass |
| moon_rock_05_h2v1 | 0.224 | executed_pair | R2/pass | R2/pass |

## 8 错误分层与限制

- pipeline_failure / provider_unavailable / not_run / invalid_identity 独立标记，不并入物理结局。
- 未完成不缩分母；本报告不把“合同断言通过”当作“隐藏几何被理解对了”。
- 单视角 + 光滑正面存在配准滑动歧义；Lux3D 隐藏面是先验不是测量；月壤是半经验受限模型，不是真实月壤。

## 9 可复现

源表由 `scripts/v3_report.py` 从逐状态原始记录重算；文档由 `scripts/v3_docs.py` 生成；两者都写 report SHA。
