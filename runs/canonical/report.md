# 运行报告

- 运行目录：`canonical`　suite：`canonical`
- 输入：`results.jsonl`（记录 2520 条，无法解析 0 行）
- 代码提交：`659c1c74dc30`（未提交修改：True）
- 模型提交：`1eb6642e3f3f`
- 版本：`{'mujoco': '3.17.0', 'numpy': '2.5.4', 'trimesh': '5.2.0', 'coacd': 'unknown', 'manifold3d': 'unknown'}`

## 1. 任务计数

| 计划 | 执行 | 预检失败 | 未接触 | 接触(任意机体) | 接触(轮子) |
| --- | --- | --- | --- | --- | --- |
| 2520 | 2520 | 0 | 513 | 2007 | 1951 |

结果分布（分母 = 已执行 2520）：`{'stuck': 78, 'tipped': 754, 'completed': 1682, 'timeout': 6}`

## 2. 分形状 × 分考生

方块、圆柱、斜坡、生成网格分别统计；三个考生分别统计，不合并成单一比例。

| shape | 来源 | 考生 | 姿态 | 执行 | 接触(任意) | 接触(轮) | 完成 | 完成率 | 结果分布 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| box | procedural | adapt | high | 168 | 134 | 133 | 94 | 56% | {'completed': 94, 'tipped': 73, 'timeout': 1} |
| box | procedural | adapt | low | 168 | 134 | 129 | 84 | 50% | {'completed': 84, 'tipped': 79, 'timeout': 4, 'stuck': 1} |
| box | procedural | hold | high | 168 | 134 | 129 | 82 | 49% | {'completed': 82, 'tipped': 86} |
| box | procedural | hold | low | 168 | 134 | 118 | 80 | 48% | {'completed': 80, 'tipped': 69, 'stuck': 19} |
| box | procedural | step | high | 168 | 134 | 128 | 85 | 51% | {'completed': 85, 'tipped': 83} |
| box | procedural | step | low | 168 | 134 | 129 | 81 | 48% | {'completed': 81, 'tipped': 86, 'stuck': 1} |
| cylinder | procedural | adapt | high | 84 | 66 | 63 | 58 | 69% | {'completed': 58, 'tipped': 17, 'stuck': 9} |
| cylinder | procedural | adapt | low | 84 | 66 | 63 | 59 | 70% | {'completed': 59, 'tipped': 21, 'stuck': 4} |
| cylinder | procedural | hold | high | 84 | 66 | 63 | 59 | 70% | {'completed': 59, 'stuck': 15, 'tipped': 10} |
| cylinder | procedural | hold | low | 84 | 66 | 63 | 57 | 68% | {'completed': 57, 'stuck': 12, 'tipped': 15} |
| cylinder | procedural | step | high | 84 | 66 | 64 | 57 | 68% | {'completed': 57, 'tipped': 25, 'stuck': 2} |
| cylinder | procedural | step | low | 84 | 66 | 64 | 58 | 69% | {'completed': 58, 'tipped': 20, 'stuck': 6} |
| mesh | lux3d | adapt | high | 84 | 65 | 65 | 62 | 74% | {'tipped': 21, 'completed': 62, 'timeout': 1} |
| mesh | lux3d | adapt | low | 84 | 64 | 64 | 64 | 76% | {'completed': 64, 'tipped': 20} |
| mesh | lux3d | hold | high | 84 | 65 | 65 | 60 | 71% | {'tipped': 24, 'completed': 60} |
| mesh | lux3d | hold | low | 84 | 64 | 62 | 59 | 70% | {'stuck': 6, 'tipped': 19, 'completed': 59} |
| mesh | lux3d | step | high | 84 | 65 | 65 | 63 | 75% | {'tipped': 21, 'completed': 63} |
| mesh | lux3d | step | low | 84 | 64 | 64 | 61 | 73% | {'tipped': 23, 'completed': 61} |
| ramp | procedural | adapt | high | 84 | 70 | 70 | 72 | 86% | {'completed': 72, 'tipped': 12} |
| ramp | procedural | adapt | low | 84 | 70 | 70 | 81 | 96% | {'completed': 81, 'tipped': 3} |
| ramp | procedural | hold | high | 84 | 70 | 70 | 72 | 86% | {'completed': 72, 'tipped': 12} |
| ramp | procedural | hold | low | 84 | 70 | 70 | 81 | 96% | {'completed': 81, 'stuck': 3} |
| ramp | procedural | step | high | 84 | 70 | 70 | 72 | 86% | {'completed': 72, 'tipped': 12} |
| ramp | procedural | step | low | 84 | 70 | 70 | 81 | 96% | {'completed': 81, 'tipped': 3} |

![完成率](figures/completion_by_shape_controller.png)


## 3. 同尺寸对照（box vs 生成网格）

仅列出同时存在 box 与 mesh 的 (相对高度, 考生, 姿态) 组合。格式为「完成数/执行数」。

| 相对高度 | 考生 | 姿态 | box | mesh |
| --- | --- | --- | --- | --- |
| 0.40 | adapt | high | 12/12 | 12/12 |
| 0.40 | adapt | low | 12/12 | 12/12 |
| 0.40 | hold | high | 12/12 | 12/12 |
| 0.40 | hold | low | 12/12 | 12/12 |
| 0.40 | step | high | 12/12 | 12/12 |
| 0.40 | step | low | 12/12 | 12/12 |
| 0.47 | adapt | high | 12/12 | 12/12 |
| 0.47 | adapt | low | 12/12 | 12/12 |
| 0.47 | hold | high | 12/12 | 12/12 |
| 0.47 | hold | low | 12/12 | 12/12 |
| 0.47 | step | high | 12/12 | 12/12 |
| 0.47 | step | low | 12/12 | 12/12 |
| 0.50 | adapt | high | 12/12 | 12/12 |
| 0.50 | adapt | low | 12/12 | 12/12 |
| 0.50 | hold | high | 12/12 | 12/12 |
| 0.50 | hold | low | 12/12 | 12/12 |
| 0.50 | step | high | 12/12 | 12/12 |
| 0.50 | step | low | 12/12 | 12/12 |
| 0.60 | adapt | high | 12/12 | 12/12 |
| 0.60 | adapt | low | 12/12 | 12/12 |
| 0.60 | hold | high | 12/12 | 12/12 |
| 0.60 | hold | low | 12/12 | 12/12 |
| 0.60 | step | high | 12/12 | 12/12 |
| 0.60 | step | low | 12/12 | 12/12 |
| 1.76 | adapt | high | 5/12 | 7/12 |
| 1.76 | adapt | low | 3/12 | 5/12 |
| 1.76 | hold | high | 2/12 | 7/12 |
| 1.76 | hold | low | 2/12 | 5/12 |
| 1.76 | step | high | 2/12 | 7/12 |
| 1.76 | step | low | 2/12 | 5/12 |
| 3.06 | adapt | high | 3/12 | 3/12 |
| 3.06 | adapt | low | 2/12 | 4/12 |
| 3.06 | hold | high | 2/12 | 2/12 |
| 3.06 | hold | low | 2/12 | 3/12 |
| 3.06 | step | high | 3/12 | 3/12 |
| 3.06 | step | low | 2/12 | 3/12 |
| 3.31 | adapt | high | 3/12 | 4/12 |
| 3.31 | adapt | low | 3/12 | 7/12 |
| 3.31 | hold | high | 2/12 | 3/12 |
| 3.31 | hold | low | 2/12 | 3/12 |
| 3.31 | step | high | 2/12 | 5/12 |
| 3.31 | step | low | 2/12 | 5/12 |

## 4. 怎么读这张表

- 完成率的分母是**已执行 trial**，其中包含未接触障碍物的场景；"接触后完成率"需要另取分母，本文未做该条件统计。
- 横向偏移是**确定性网格**，不是随机采样；本表的完成率只描述这张网格，不能外推为随机月面或现实任务的成功概率。
- 同一资产的多个偏移不是多个独立的形状家族。
- 三个考生是手工控制器：`hold` 锁死站姿只转轮，`step` 执行固定抬腿序列，`adapt` 用本体感觉在"抬腿/加大力矩"之间二选一。都不能读作"学会了越障"。
- 障碍物是**静态刚性体**，不滚动、不翻倒；地面刚性，摩擦未标定。

## 5. 未做的事

- 未做形状家族留出测试，**不能**声称"对未见过物体泛化"。
- 未做训练对照，**不能**声称生成资产对训练有帮助。
- 未独立定义"有效难度"，**不能**声称"同难度下无差异"。