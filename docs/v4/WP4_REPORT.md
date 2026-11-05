# WP4 真实想象价值报告（首轮）

- 问题：真实候选能否在 len_short/len_mid 上让 FULL 获得接近 PERFECT 的收益。
- 判定：FULL 必须过同一准入并在真值执行；零合格按合同回退 OBS_CONS 并保留分母。
- 回归：`runs/v4/regress/20261105T025035.json`（T1–T6 全过，切换沙箱后未重跑，正式仿真批次前将复跑）。

## 结果

| 场景 | arm | 选择 | 结局 | t_end | 接触 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| len_short | FULL | BODY | pass | 11.78 | 0 | 0/23 候选准入 → 回退 OBS_CONS，引用同一次执行 |
| len_short | OBS_CONS | BODY | pass | 11.78 | 0 | unknown_hold，speed 0.4 |
| len_short | PERFECT | D2 | pass | 7.28 | 0 | 真值补全上限 |
| len_short | OBS_OPT | BODY | pass | 11.78 | 0 | 未知当空地 |
| len_mid | FULL | BODY | pass | 11.78 | 0 | 同上，回退 OBS_CONS |
| len_mid | OBS_CONS | BODY | pass | 11.78 | 0 | 同上 |
| len_mid | PERFECT | D2 | pass | 7.24 | 0 | 真值补全上限 |
| len_mid | OBS_OPT | BODY | pass | 11.78 | 0 | 同上 |

- 差距拿回比例 = (OBS − FULL)/(OBS − PERFECT) = **0**（FULL 即 OBS）。
- 真实候选未带来任何决策或执行优势；不是正例。PERFECT 的信息价值在 WP6 提速后只剩约 4.5 s。
- 候选失败原因：看到 WP3 首组的空地侵入 29–55%、轮廓 IoU 0.49–0.78，均远超准入容差。

## 说明

- 旧 6 份与首组 17 份都按 §2.4 重评，**0 份通过**；分母保留（23 份评估）。
- 未用旧慢版 OBS 基线虚增差距；WP6 提速后 FULL/OBS/PERFECT 共用 speed 0.4 计划。
- 无正例可冻结主角；不宣称“长石下想象已有收益”。
