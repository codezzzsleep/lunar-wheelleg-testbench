# WP2 确认阶段报告（进行中）

问题：统一终点下，PERFECT 是否只在“想象有收益”的场景省时，OBS_CONS 是否始终安全？
判定：三臂都必须在真值场景 pass 且 0 机身接触；PERFECT 相对 OBS_CONS 至少省 30 s 才算价值场景。

命令：`python3 scripts/v4_wp2.py`（六场景 × PERFECT/OBS_CONS/OBS_OPT，真值执行，统一终点）
结果：`runs/v4/wp2/confirm_table.csv` / `.json`；18/18 行 pass、18/18 零机身接触。

| 场景 | PERFECT | OBS_CONS | OBS_OPT | 价值 |
| --- | --- | --- | --- | --- |
| ref | BODY 113.42 s | BODY 113.52 s | BODY 113.38 s | 无 |
| len_short | **D2 7.28 s** | BODY 113.92 s | BODY 113.74 s | **省 106.6 s** |
| len_mid | **D2 7.24 s** | BODY 112.90 s | BODY 112.74 s | **省 105.7 s** |
| len_long | BODY 113.40 s | BODY 113.52 s | BODY 113.38 s | 无 |
| rear_low | BODY 113.42 s | BODY 113.52 s | BODY 113.38 s | 无 |
| rear_high | BODY 69.52 s | BODY 65.86 s | BODY 65.80 s | 无（PERFECT 反而慢） |

代价项（t_end、路程、能耗、停车次数、接触）均已记录；能耗为关节/轮 |τ·ω| 积分。

未完成：三岩石 × 三类未知（低石/高石/半遮挡）× 三臂的扩展与 ≥6 价值场景筛选。

## 扩展阶段（结论：不满足 ≥6 价值场景，触发 SPEC §6 停止条件）

- 三岩石 × 三类未知：`moon_rock_01_h1v0`、`moon_rock_03_h1v0`、`rock_07_h2v1`；
  每岩石构造低石、高石、半遮挡三种只改 U 的变体。
- 第一路径（按高度/侧向裁切 U）18 次真值执行：所有可跑场景 pass、0 接触；
  PERFECT 相对 OBS_CONS 最大省时 **0.7 s**，无 ≥30 s 价值场景。rock_07 三变体均 A0 安全停止。
- 第二路径（后部 U 内开低/中/侧向缺口）在 moon_rock_03 上 3 变体：PERFECT 仍只省 0.6–0.7 s。
- 加上确认阶段的 len_short、len_mid，共 **2 个价值场景**，达不到 SPEC 要求的 6 个。
  按 §6“WP2 找不到 6 个价值场景，立即停下并回报”，**不进入 WP3**，不放宽判定、不人工制造收益。
- 证据：`runs/v4/wp2/ext/screen_table.csv`、`runs/v4/wp2/ext2/screen_table.csv`。
