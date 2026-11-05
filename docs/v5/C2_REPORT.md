# C2 核心闭环（窄道 0.35，负结果）

## 本步问题

在 C1 窄道 I 类场景 `rock_07_h0v0`（channel half 0.35）上，用该状态曝光归一化后的
6 份 Lux3D 候选跑完整闭环，FULL 是否做出与 OBS_CONS 不同且更好的决定。

## 命令

- `python3 scripts/v5_c2.py --states rock_07_h0v0 --channel 0.35 --tasks runs/v5/c2/rock_07_h0v0/tasks_exposed.json --out runs/v5/c2_narrow`

## 结果表

| 项 | 结果 |
| --- | --- |
| 每状态 KA1/KA5/KA6 | true / true / true |
| 候选 / 准入 | 6 / **6** |
| FULL 多数 / 最坏 | R1 / R1（轮子优先） |
| FULL 真值执行 | **R1，physical_failure，4.30 s** |
| OBS_CONS | **R2，pass，8.42 s** |
| PERFECT | R2，pass，8.42 s |
| 类型 | **无**（FULL 比 OBS 差） |

### 候选想象质量

| 候选 | admitted | rear_err (m) | top_err (m) | path_p95 (mm) | 隐藏 IoU |
| --- | --- | --- | --- | --- | --- |
| A1 | true | +0.070 | −0.002 | 91 | 0.615 |
| A2 | true | +0.060 | −0.004 | 91 | 0.638 |
| B1 | true | +0.048 | −0.002 | 89 | 0.700 |
| B2 | true | +0.046 | −0.002 | 88 | 0.706 |
| C1 | true | +0.054 | −0.002 | 91 | 0.679 |
| C2 | true | +0.052 | −0.002 | 89 | 0.685 |

- 6/6 候选都把隐藏区后缘**多想象 4.6–7.0 cm**（rear_err 正），路径高度误差 P95 88–91 mm，
  隐藏 IoU 只有 0.62–0.71。
- 后果：FULL 认为右侧有足够空间，选 R1；真值里右侧被真实岩石挡住，R1 翻车。
- OBS_CONS 选 R2，真值通过；PERFECT 也是 R2/pass。

## 未做到

- 没有找到 FULL 决策不同且满足 I/II 类的场景；本场景 FULL 反而比 OBS 差。
- 只跑了这一个窄道价值场景；0.475 宽度无价值，开阔场无价值。
- 预演矩阵已存 `runs/v5/c2_narrow/rock_07_h0v0/full/<候选>/matrix_rows.jsonl`，未逐格展开报告。

## 根因（按 REVIEW_R2 第 1 条改写）

- **R1 是直行，不是“右侧”**。FULL 选 R1 的原因是它在**预演**里为所有候选返回成功、代价最低；
  想象偏长只会让 FULL 更谨慎，不会让它主动选直行。
- **预演没有执行通道边界**：`make_scene` 把通道写死为 1.2 m，适用性、预演都用这个值；
  真值执行才用场景的 0.35 m。于是 D1（横向偏移约 0.43 m）在预演里被记为成功，
  真值里必然越界；同一份 R1 在开阔场三臂都通过 6.74 s，在 0.35 m 窄道里越界失败。
- **失败类型已用轨迹确认**：`execution_run.json` 的 reason 是 `out_of_bounds`，
  `max_tilt` 仅 0.27 rad，final x=2.095；记录里 max|y|=0.353 m，最后一帧越过 0.35 m 边界。
  不是翻车，也不是机身接触（contact=wheel）。
- **C1 与 C2 规则不一致**：C2 没有三次扰动预演、没有双几何交集；同一场景两个结论。
- 因此本文原“候选隐藏区偏长导致 FULL 选错”的说法作废；想象偏长是真实存在的
  （rear_err +4.6–7.0 cm），但不是本次 FULL 失败的直接原因。

## 证据

- `runs/v5/c2_narrow/rock_07_h0v0/result.json`
- `runs/v5/c2_narrow/rock_07_h0v0/candidates.json`
- `runs/v5/c2_narrow/rock_07_h0v0/FULL/decision_majority.json`、`decision_worst.json`
- `runs/v5/c2_narrow/rock_07_h0v0/{PERFECT,OBS_CONS,FULL}/exec/run/`
- `runs/v5/c1_narrow035/narrow_table.csv`（价值来源）

## 下一步

SPEC §5.3 触发：C2 的唯一价值场景上 FULL 比 OBS_CONS 差且根因明确（候选隐藏区系统性偏长）。
按要求停下回报，不再扩大 C2；若继续，应先修候选的隐藏区偏长（例如加后缘约束/校准），
或换用后缘误差在 3 cm 内的候选，而不是改门槛。
