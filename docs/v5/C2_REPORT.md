# C2 核心闭环（首个正例）

## 本步问题

在 C1 的 I 类价值场景上，用该状态自己的 v3 Lux3D 候选，经过配准→C0 准入→FULL 融合→
预演矩阵→多数/最坏决策→真值执行，FULL 是否与 OBS_CONS 决策不同且结果更好。

## 命令

- `python3 scripts/v5_c2.py --states moon_rock_05_h2v1`

## 结果表

| 场景 | 候选/准入 | FULL 决策 | FULL 结局 | OBS_CONS | PERFECT | 类型 |
| --- | --- | --- | --- | --- | --- | --- |
| `moon_rock_05_h2v1` | 6 / **6** | **D1**（多数=最坏=D1，轮子优先） | **pass，6.68 s** | R1，tipped，3.68 s | D1，pass，6.68 s | **I 类** |

- FULL 决策与 OBS_CONS 不同：**是**（D1 vs R1）。
- FULL 结局与真值上限一致（同为 D1/pass 6.68 s），且明显优于 OBS 的翻车。
- 多数规则与最坏规则选择相同（D1），没有第二个需要执行的分支。

### 准入指标（6/6 通过，C0 门槛）

| 候选 | 尺度比 | 隐藏占比 | 壳相接 | 空地侵入 | 轮廓 IoU |
| --- | --- | --- | --- | --- | --- |
| A1 | 0.991 | 0.849 | 0.841 | 0.095 | 0.904 |
| A2 | 1.000 | 0.867 | 0.898 | 0.065 | 0.933 |
| B1 | 1.000 | 0.830 | 0.925 | 0.111 | 0.905 |
| B2 | 0.982 | 0.847 | 0.843 | 0.096 | 0.921 |
| C1/C2 | 0.98–1.0 | 0.83–0.85 | 0.84–0.90 | ≤0.11 | 0.90–0.92 |

## 未做到

- 第二个 I 类场景 `rock_07_h1v1` 没有可用的 6 份候选（目录里只有 candidate.json，无 mesh）。
  按 C2 条款补生成 6 个任务，提交后 6 个任务全部返回 `status=4`；ledger 显示
  首次原因是 `GENERATION_CONCURRENCY_LIMIT_EXCEEDED`，并发释放后重试仍被缓存判为失败。
  该场景本轮没有 FULL 结果，不冒充。
- 能耗与机身接触字段尚未从 exec 记录回填；决策文件与逐格矩阵已保存，但逐步记录仍在沙箱。

## 根因

- 补生成失败根因：Lux3D 账号并发上限触发，任务创建后服务端 status=4；不是图像或代码错误。
- 需要等并发窗口、清缓存后重试一次，或改用该状态已有的 `candidate.json` 对应 GLB（若存在）。

## 证据

- `runs/v5/c2/moon_rock_05_h2v1/result.json`
- `runs/v5/c2/moon_rock_05_h2v1/candidates.json`
- `runs/v5/c2/moon_rock_05_h2v1/FULL/decision_majority.json`、`decision_worst.json`、`decision_chosen.json`
- `runs/v5/c2/core_table.csv`
- 沙箱逐步记录：`runs/v5/c2/moon_rock_05_h2v1/{PERFECT,OBS_CONS,FULL}/exec/run/record/`

## 下一步

- 补 `rock_07_h1v1` 的候选（等并发窗口）并跑 C2；或先用 `moon_rock_05_h2v1` 做 C3 重评与素材。

## `rock_07_h1v1` 补生成重试结果（第二次）

- 并发窗口已释放（WP3 全部结束）后，用新 identity + `retry_of` 重提 6 个任务。
- 6 个任务均成功 create，但随即返回服务端 `status=4`（failed），不是并发错误。
- 该状态的输入变体图整体偏暗（A1 均值 89.8/255、最大 151），推测为服务端内容拒收；
  没有继续第三次调用（SPEC 只允许一次重试）。
- 因此该场景仍无候选，C2 只有 `moon_rock_05_h2v1` 一个正例；核心闭环已达成 ≥1 场景要求。
