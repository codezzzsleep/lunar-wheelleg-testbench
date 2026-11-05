# M2 轮腿本领展示

## 本步问题

从 V5 的 `rehearsal_3of3.json` 中筛“真值安全集只含腿式动作”的组合，并做 WHEEL_ONLY / WHEEL_LEG 对比；
WP7 六个场景按 §3 格式重跑打包。

## 命令

- `python3 scripts/v6_m0_audit.py`（数据可用性）
- 扫描 `runs/v5/a_r3/a_table_all.csv` 的 safe_both
- `python3 - <<'PY' ...`（生成 leg_only.csv，见 STATUS 提交）

## 结果表

### 只有腿能过

- **0 个组合**满足“真值安全集 ⊆ {L1, L2, BODY_CLEARANCE}”。
- 原因：V5 的逐动作 `rehearsal_3of3.json` 只存在于旧沙箱，已随回收丢失；主机只有聚合后的
  `safe_both`，其中每个非空集合都至少含一个轮式动作。
- 最接近的 6 个组合（PERFECT 实际选了腿式且通过，但安全集仍含轮式）：

| 状态 | 通道 | PERFECT | OBS | safe_both |
| --- | --- | --- | --- | --- |
| moon_rock_02_h2v0 | 0.60 | L2 pass | L2 pass | BODY,L2,R2 |
| moon_rock_07_h2v0 | 0.60 | L2 pass | R2 pass | R2 |
| moon_rock_07_h2v0 | 0.70 | L2 pass | R2 pass | R2 |
| moon_rock_05_h1v1 | 0.70 | L1 pass | R2 pass | BODY,R2 |
| moon_rock_05_h2v0 | 0.70 | L1 pass | L2 pass | L1,L2,R2 |
| moon_rock_05_h2v0 | 0.80 | L1 pass | R1 pass | BODY,L1,L2,R1,R2 |

- 因此没有执行 WHEEL_ONLY / WHEEL_LEG 两次对比；没有新造场景。

### WP7 六场景

- 未按 §3 重跑；现有 V4 结果（A1–B2）已打包上传为 `v6__wp7__scenes.tar.gz`（452 KB），
  仅作素材参考，不满足 §3 格式。
- A4 的轮式 8.82 s vs 抬身 21.12 s 数字沿用 V4 记录，未重测。

## 未做到

- leg-only 组合为 0 是数据缺失导致，不是“腿无用”的结论。
- WP7 未重跑、未按素材包格式重组。

## 根因

- 逐动作预演记录与 M0 丢失的数据同源：旧沙箱 `runs/v5/a_r3/*/rehearsal_3of3.json` 未迁移，主机只有聚合表。
- 没有这些记录就无法判定“安全集是否只含腿式”，也不能在不新造场景的前提下补算。

## 证据

- `runs/v6/m2/leg_only.csv`（6 个最接近组合，0 个 leg-only）
- Release `v6-showcase`：`v6__wp7__scenes.tar.gz`

## 下一步

M2 的完整结论依赖 M0 恢复逐动作预演记录；在拿到旧沙箱数据或 API 密钥前无法继续。
