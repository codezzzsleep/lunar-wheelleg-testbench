# V6 结果总表（截至 M1/M2，M3 未执行）

每个数字注明来源与样本数；M3 未执行，相关行为空并标注。

## M1 想象自检

| 数字 | 值 | 来源 | 样本 |
| --- | --- | --- | --- |
| 候选总数 | 122 | `runs/v6/m1/checkup_all.csv` | v3 75 + WP3 yaw0 47 |
| 准入通过 | 74 | 同上 | 122 |
| 坏想象（|rear|>5 cm 或 P95>80 mm） | 68 | `runs/v6/m1/selfcheck.json` | 122 |
| 通过组 rear 中位数 | −0.002 m | `selfcheck.json` | 74 |
| 通过组 path P95 中位数 | 56.1 mm | 同上 | 74 |
| 拒绝组 rear 中位数 | −0.117 m | 同上 | 48 |
| 拒绝组 path P95 中位数 | 97.0 mm | 同上 | 48 |
| 敏感度 / 特异度 / 精确率 | 0.426 / 0.167 / 0.392 | 同上 | 122 |
| shell_contact 与 |rear| Spearman | −0.644 | 同上 | 122 |
| contour_iou 与 |rear| Spearman | −0.584 | 同上 | 122 |

## V5 定量结论（沿用）

| 数字 | 值 | 来源 | 样本 |
| --- | --- | --- | --- |
| A 线组合数 | 52（目标 56） | `runs/v5/a_r3/a_table_all.csv` | 13 状态×4 档 |
| A 线 I 类 | 1（moon_rock_02_h2v1@0.90） | 同上 | 52 |
| A 线 II 类 | 0 | 同上 | 52 |
| 该 I 类 C2 FULL | A0，safe_stop 3.00 s | `runs/v5/c2_a/.../result.json` | 6 候选 |
| B1 FULL / OBS | L1 8.78 s / D1 7.74 s | `runs/v5/b1/.../result.json` | 6 候选 |
| OBS_CONS 偏移 − PERFECT 偏移 | 1.4–7.4 cm | `docs/v5/A_R3_REPORT.md` | 52 |

## M2 轮腿

| 数字 | 值 | 来源 | 样本 |
| --- | --- | --- | --- |
| leg-only 组合 | 0 | `runs/v6/m2/leg_only.csv` | 52 聚合组合 |
| 最接近的腿式选择 | 6 | 同上 | 6 |
| A4 轮式 / 抬身 | 8.82 s / 21.12 s | V4 WP7 记录（未重测） | 1 |

## M0 Lux3D

| 数字 | 值 | 来源 | 样本 |
| --- | --- | --- | --- |
| 任务总数 | 234 | `dist/v6/lux3d_manifest.json` | 234 |
| 已恢复 | 75 | 同上 | 75 |
| 失联 | 159 | 同上 | 159 |
| 已上传 GLB | 见 Release `v6-showcase` | `/tmp/v6upload.log` | 75 |

## M3 连续路线

| 数字 | 值 | 说明 |
| --- | --- | --- |
| 两臂结局 | 未执行 | 依赖 M0 缺失的现场 Lux3D 调用 |
| 各遭遇用时 | 未执行 | — |

## 全部 Lux3D 调用（已知子集）

| 数字 | 值 | 来源 |
| --- | --- | --- |
| 主机 ledger 任务 | 5 | `runs/v3/generation/ledger.jsonl` |
| WP3 first36 ledger 任务 | 34 | `runs/v4/wp3/ledger_first36.jsonl` |
| 成功率（first36） | 34/36 downloaded（2 rejected） | 同上 |
| 平均耗时 | 未统计（时间戳不全） | — |

## 未做到

- M3 未执行；M4 素材包与重放检查未做；M0 159 任务失联；M1 缺 96 份 ±25°；M2 WP7 未重跑。
- 上述缺口的共同根因：旧沙箱回收导致输入图、GLB、逐动作预演记录与 API 密钥丢失。
