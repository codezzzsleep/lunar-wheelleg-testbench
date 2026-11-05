# C1 R2：四档通道重筛与公共评估函数

## 本步问题

按 REVIEW_R2：抽出 C1/窄道/C2 共用评估函数；通道半宽在适用性、预演、真值执行三处统一读场景自身；
绕行偏移由各臂几何决定；在 0.60/0.70/0.80/0.90 m 四档通道重筛；做重复性检查。

## 命令

- `python3 scripts/v5_c1_r2.py --out runs/v5/c1_r2`
- `python3 scripts/v5_c1_r2.py --states rock_07_h0v0 --channels 0.70 --out runs/v5/c1_r2_repeat`

## 实现

- `scripts/v5_eval.py`：公共 `robust_arm`（3 次扰动、3/3、接触核算）+ `contact_of`。
- `stage8_matrix2.make_scene(..., channel_half=)` 把通道写进场景后再建 env；
  适用性 `v3_core.rehearse_on_spec` 读 `spec['channel']['half_width']`；
  `Detour.act` 的横向目标按 `channel_half - ROBOT_HALF_W - 0.05` 截断。
- 真值执行同样从同一场景读取通道。

## 结果表（4 状态 × 4 档）

| 状态 | 0.60 | 0.70 | 0.80 | 0.90 |
| --- | --- | --- | --- | --- |
| rock_07_h0v0 | — | — | — | — |
| moon_rock_05_h2v1 | A0/A0 | A0/A0 | A0/A0 | **I：PERFECT R2 pass 9.04 / OBS A0** |
| moon_rock_06_h1v1 | — | — | — | — |
| moon_rock_02_h0v1 | — | — | — | — |

- 16 个组合中只有 1 个 I 类：`moon_rock_05_h2v1`，channel half 0.90。
- 该组合 `safe_solid = {D1}`，`safe_empty = {R2}`，交集为空，所以 OBS_CONS 退回 A0；
  PERFECT 用真值几何选 R2，真值 pass 9.04 s。
- 0.60–0.80 下同一状态 PERFECT 也退回 A0，说明通道过窄时连真值也没有安全绕行。

## 重复性检查

同一状态同一档（`rock_07_h0v0`, 0.70）跑两次：

| 项 | 第一次 | 第二次 |
| --- | --- | --- |
| PERFECT 动作/结局 | D1/pass | D1/pass |
| OBS 动作/结局 | R1/pass | R1/pass |
| safe_both | BODY,D1,D2,L2,R1,R2 | 完全相同 |
| contacts | 0 | 0 |

## 未做到

- 只筛了 4 个状态 ×4 档；未覆盖 48 个状态。
- 0.60–0.80 没有价值，不能据此判断整个数据集；0.90 的价值尚未在 C2 中转为正例（见 C2_R2_REPORT）。

## 根因（通道过窄时无价值）

- `Detour.applicable` 要求 `channel_half - (W_vis/2 + 0.20) >= 0.36`；W_vis≈0.26 时需 half≥0.69。
  0.60 不满足，任何绕行都不可用；0.70 起可用，但真值上 D1 不一定能过（推力/边界）。
- 0.35 档 D1 预演“成功”是旧代码未传通道造成的假成功，已由公共函数修正。

## 证据

- `runs/v5/c1_r2/width_table.csv`
- `runs/v5/c1_r2_repeat/width_table.csv`
- 每组合每臂：`runs/v5/c1_r2/<state>_<ch>/<arm>/rehearsal_3of3.json`

## 下一步

C2 R2：在 0.90 的 `moon_rock_05_h2v1` 上用该状态 6 份候选跑 FULL；本文的 I 类是否能在 FULL 上保持，
见 `docs/v5/C2_R2_REPORT.md`。

## 追加筛选（4 个状态 × 0.90）

| 状态 | PERFECT | OBS_CONS | 类型 |
| --- | --- | --- | --- |
| moon_rock_03_h2v1 | A0 safe_stop | A0 | 无 |
| moon_rock_04_h0v1 | L1 pass 7.00 | L1 pass 7.00 | 无 |
| moon_rock_07_h2v1 | L1 pass 7.76 | D2 pass 7.46 | 无 |
| rock_07_h1v1 | D2 physical_failure 3.48 | A0 safe_stop | 无 |

- 追加 4 个状态后，0.90 档仍只有 `moon_rock_05_h2v1` 一个 I 类。
- `rock_07_h1v1` 的 PERFECT 也失败（D2 翻车），说明该状态真值上绕行本身不可行，不是 OBS 保守造成的差距。

## 汇总

- 共筛 8 状态 × 0.60–0.90（其中 4 状态只跑 0.90），20 个组合，I 类 1 个、II 类 0 个。
- 该 I 类在 C2 R2 中 FULL 失败（见 C2_R2_REPORT），本轮没有 FULL 正例。
