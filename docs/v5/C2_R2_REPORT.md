# C2 R2：0.90 m 通道上的 FULL（负结果）

## 本步问题

用公共评估函数（3/3 扰动、接触核算、双几何 OBS_CONS 交集、通道统一）在 C1 R2 的唯一 I 类
`moon_rock_05_h2v1`（channel half 0.90）上跑 FULL，检查 FULL 决策是否与 OBS 不同且满足 I/II。

## 命令

- `python3 scripts/v5_c2_r2.py --state moon_rock_05_h2v1 --channel 0.9 --tasks none --out runs/v5/c2_r2/moon_rock_05_h2v1_0.9`

## 结果表

| 项 | 结果 |
| --- | --- |
| 候选 / 准入 | 6 / **6** |
| FULL 多数 / 最坏 | **L1 / L1** |
| FULL 真值执行 | **L1，out_of_bounds，6.04 s** |
| OBS_CONS | A0，safe_stop，3.00 s |
| PERFECT | R2，pass，9.04 s |
| OBS_OPT | R2，pass，9.04 s |
| 类型 | 无（FULL 失败） |

- 决策确实与 OBS 不同（L1 vs A0），但不满足 I/II：FULL 没有通过。
- FULL 与 PERFECT 也不同（L1 vs R2）；PERFECT 证明该场景真值有解。

## 失败类型

- `execution_run.json`：`reason=out_of_bounds`，`max_tilt` 低，`contacts=0`。
- 记录里 max|y| = **0.905 m**，最后一帧越过 0.90 m 边界；不是翻车，也没有机身接触。
- L1 是抬前腿慢过，不是绕行；它在 FULL 候选几何的预演里 3/3 成功，真值里被真实岩石推挤后横向漂出边界。

## 根因

- **预演几何与真值几何的接触差异**：FULL 的候选几何在隐藏区没有真实岩石的侧向凸起，
  L1 沿该几何直行不会被推；真值里同一动作被岩石侧向推挤，横向漂到 0.905 m 越界。
- 不是“想象偏长导致选直行”（该说法已作废），也不是通道没统一（本轮已统一）。
- 不是候选后缘误差问题：6 份候选 rear_err 与隐藏 IoU 已记录，但失败发生在横向接触，不在纵向长度。

## 证据

- `runs/v5/c2_r2/moon_rock_05_h2v1_0.9/result.json`
- `runs/v5/c2_r2/moon_rock_05_h2v1_0.9/FULL/decision_majority.json`、`decision_worst.json`
- `runs/v5/c2_r2/moon_rock_05_h2v1_0.9/FULL/exec/execution_run.json`
- `runs/v5/c2_r2/moon_rock_05_h2v1_0.9/FULL/exec/record/run/`（qpos 逐帧）

## 结论

在本轮四档筛选中，唯一的 I 类场景上 FULL 仍然失败；按 REVIEW_R2 的要求如实报告，
不通过改门槛、不用真值挑候选来制造正例。若要继续，应针对“候选几何缺少侧向凸起导致
L1 被推”的问题改进候选评估或动作安全边界，而不是调整通道或后缘门槛。
