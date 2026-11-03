# 能力边界（D/E 的诚实结论）

## D：腿式能力

- **CLIMB 未通过**。两条实现路径都停在“四轮在台上稳定保持/下降”之前：
  - 准静态逐腿：`runs/v3/climb/rear_easy3_partial_r1`（RL_shift）、
    `runs/v3/climb/rear_center_partial_r1`；
  - 轮腿协同 push：`runs/v3/climb/rear_wheelassist_partial_r1`（hold_all，RR 0 N）。
  - 最小失败报告：`runs/v3/climb/CLIMB_failure_report.json`、`docs/D_FAILURE_REPORT.md`。
- **D3 不成立**：唯一候选 `moon_rock_04_h2` 上，S1 只在 h2v0 通过（unified），
  h2v1 的 S1/L1/L2 全部翻倒；腿式通过率 1/2，不是 3/3。
- 第二技能：SIDE_LEVEL 已实现但未获干净评估；BODY_CLEARANCE 未实现。
- 不宣称腿式相对轮式有价值。

## E：FULL / OBS_ONLY 主角对照

- 14 个已有决策案例：双方成功 12、仅 FULL 成功 0、仅 OBS 成功 0、选择不同 1。
- 唯一选择不同的 `moon_rock_02_h2v0`：FULL 选 L2 成功 6.30 s，OBS 选 R1 成功 6.26 s；
  背面信息改变了选择，但没有改变结果，轮式还略便宜。
- 两个边界案例：`01_h2v0` 双方 A0 abort；`05_h1v1` 双方 S1 物理失败。
- 按 SPEC G5：没有正例，如实结束这次研究尝试，展示系统边界；
  详见 `docs/E_CASES.md`、`docs/E_PRESCAN.md`。

## 使用建议

- 引用本项目时：A/B/F 可标“通过”；C 标“部分”；D 标“未通过（CLIMB）”；E 标“无正例”。
- 不要把 S1 的 1/2 或 20 m 纯轮式路线当作腿式价值证据。
