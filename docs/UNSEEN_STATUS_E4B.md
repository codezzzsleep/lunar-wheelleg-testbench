# E4 接续（d3820b1 复核后）

基线 `d3820b1` → 当前见 `git log`。

## 0. 审查指出的问题：处理状态

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| P0-1 | 候选被当作自己的隐藏真值 | **已修**：真值取 `cases/unseen_v1/planA.json` 的 `drop` 背面，`h5_loop` 强制校验 `truth_sha != candidate_sha`，相同即退出 |
| P0-2 | 绕过统一动作库 | **已修**：删除自写控制循环，改用 `runner.EpisodeRunner` + `skills.make_skill` |
| P0-3 | 忽略终止、计时错误 | **已修**：只认 `env.step` 的 terminated/truncated 与 runner 的 out_of_field；计时用 `env.t`，同时记控制步/物理步 |
| P0-4 | 三个 seed 不是三个初态 | **已修**：保留真实 `init_perturbation`，保存 qpos/qvel 与哈希，校验互不相同 |
| P0-5 | 加载器未完整执行政策 | **已修**：逐段重算 SHA、缺文件即拒绝、精确组匹配；6 项负例回归 |
| P1 | 真实 H5 未接正式入口 | **部分**：`h5_loop` 已走正式执行器，但 `unseen_pipeline` 的 H5 分支与保姿态碰撞链未接 |
| 次要 | align24 增量 yaw 组合顺序 | **未修**（只影响元数据解释，不影响已核实的 M 与世界顶点） |

## 1. 旧结果重新分类（保留，不删）

`h5_A4`、`h5_fixture`、`h5_fixture_easy` 已写入 `reclassified.status = generated_self_replay`：

- 可作为**旧执行器诊断**；
- **不能**算独立隐藏真值闭环（其 `truth_asset_sha` 与候选 world SHA 完全相同）；
- 撤回"共同真值 3/3""三个不同初态""A0 已验证停稳"的表述。

## 2. 修正后的 A4 单例（`runs/unseen/recovery_r3/h5_A4_truth/`）

| 项 | 值 |
| --- | --- |
| 候选 world SHA | `7646be25…` |
| 真值 SHA | `2afba6f8…`（`planA` 的 `drop` 背面，**不同**） |
| 初态 | 3 个，qpos 哈希 `639c6856 / 5a4af5ce / 7d11b410`，**互不相同** |
| 预演（候选上） | R1/R2/L1/L2 各 3/3 成功，A0 3/3 abort |
| 决策 | 选 **R1**，`decision.json` SHA `b8422660…`，执行前落盘 |
| 执行（独立真值） | H5 3/3 success，接触 `wheel`，5.8–5.9 s，294 控制步 / 3240 物理步 |
| 盲走对照 | B0 3/3 success，**与 H5 完全相同** |

**诚实结论**：这个真值案例上盲走本来就能过，A4 的假设没有带来可测差别。
H5 与 B0 成功数相同（3/3 vs 3/3），没有收益证据。链路成立，收益不成立。

## 3. 加载器负例（`tests/test_candidate_store.py`，6 项通过）

缺 world → 拒绝；缺 clean → 拒绝；B 组计划请求 A 组 → 拒绝；
world SHA 被改 → 拒绝；clean SHA 被改 → 拒绝；结构合格 → 进入加载列表。

## 4. 未完成

| 项 | 真实依赖 |
| --- | --- |
| `unseen_pipeline` 接 H5 + 保姿态 CoACD | 需要把 candidates 送进正式入口与碰撞链 |
| 六方法小矩阵 | 需要每方法各自的 planning 实现 |
| 页面 | 需要接本批记录 |
| 月壤 MuJoCo 单轮 | 需要软接触标定实验 |
| 上传包 / 主动观察 | 需裁剪与第二视角实现；付费需用户确认 |
| align24 yaw 元数据 | 组合顺序 `R_real @ R_axis.T` |

预算：历史 15/15、300/300、剩 0、核验 unknown；本批未新增付费任务。
