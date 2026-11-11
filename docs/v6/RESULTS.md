# V6 结果总表（截至 M1/M2，M3 未执行）

> **⚠ 2026-11-11 更正（REVIEW_2026-11-11 追加）**：本文件自相矛盾——原第 1/3/53–58 行称 M3「未执行」，与原第 75 行起的「## M3 连续路线（三遭遇，R2 重跑）」章节冲突；以后者为准，但 M3 的连续性在 E2 处中断（E2 第二眼未在连续时间线内实时重拍，0/4 准入）。
> 引用本文件结论前请先读 `docs/REVIEW_2026-11-11.md` 与 `docs/DELIVERY.md`；现行结论以 `docs/DELIVERY.md` 的结论矩阵为准。
> 依据：原第 118 行引用的 `runs/v6/m3/E2/admission_second.csv` 4 行全 `admitted=False`（0/4）；`final_x=13.51、62.38 s、success=false` 是**已废弃的 R1 两臂包**数字（`REVIEW_R1` §4.5 判两臂 qpos 逐帧相同、查明前不得引用），现行 R2 包为 x=22.01、59.76 s、success。
> 另：`runs/v6/m1/selfcheck.json` 记 n=206，而本表 M1 侧统计对象为 122+96=218 行，差 12 行无解释。

每个数字注明来源与样本数；M3 未执行，相关行为空并标注。

## M1 想象自检

| 数字 | 值 | 来源 | 样本 |
| --- | --- | --- | --- |
| 主结论样本 | 已验证 122（v3 75 + WP3 yaw0 47） | `runs/v6/m1/semantics.json` | 122 |
| 参考样本 | ±25° 96 份（未验证） | 同上 | 96 |
| 通过（坏/好） | 74（29/45） | 同上 | 122 |
| 拒绝（坏/好） | 48（39/9） | 同上 | 122 |
| 坏想象被拒比例 | 0.574 | 同上 | 122 |
| 好想象被留比例 | 0.833 | 同上 | 122 |
| 通过组坏想象比例 | 0.392 | 同上 | 122 |
| 拒绝组坏想象比例 | 0.813 | 同上 | 122 |
| 通过组 rear 中位数 | −0.016 m | `selfcheck.json` | 206 |
| 通过组 path P95 中位数 | 58.0 mm | 同上 | 206 |
| 拒绝组 rear 中位数 | −0.136 m | 同上 | 206 |
| 拒绝组 path P95 中位数 | 118.5 mm | 同上 | 206 |

| shell_contact 与 |rear| Spearman | −0.685 | 同上 | 206 |
| contour_iou 与 |rear| Spearman | −0.653 | 同上 | 206 |

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
| 已恢复/重建 | 241 | 同上 | 241 |
| 失联 | 15 | 同上 | 15 |
| 已上传 GLB | 75 旧 + 22 v3 重建 + 144 WP3 | Release `v6-showcase` / LFS | 241 |

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


## M3 连续路线（三遭遇，R2 重跑）

> 旧 R1 两臂 qpos 相同的包已废弃；以下为 R2 重建后的结果。


| 项 | FULL | OBS_CONS | 来源 | 样本 |
| --- | --- | --- | --- | --- |
| E0 0.08 m 小石 | 直接过 | 直接过 | `runs/v6/m3/E0/result.json` | 1 |
| E1 准入 | 1/6 | 1/6 | `runs/v6/m3/E1/admission_local.csv` | 6 |
| E1 决策 | R1 | L2 | `runs/v6/m3/E1/{full,obs}/result.json` | 各 1 |
| E1 单独执行 | pass 52.48 s | pass 52.44 s | 同上 | 各 1 |
| E2 第一眼 | 0/6 准入 | 0/6 | `runs/v6/m3/E2/admission_local.csv` | 6 |
| E2 第二眼 imgs | 0/4 准入 | 0/4 | `runs/v6/m3/E2/admission_second.csv` | 4 |
| 连续路线终点 | x=22.01，59.76 s | x=22.00，56.16 s | `runs/v6/m3/route2/run_*/result.json` | 各 1 |
| 结局 | success | success | 同上 | 各 1 |
| 重放 | 3154 帧，0.804 mm，20 障碍 | 2808 帧，0.804 mm，20 障碍 | `dist/v6/showcase_manifest.json` | 各 1 |

- 两臂都在 E2 全拒后 A0 停车；E1 动作不同、结局相同。

## Lux3D 调用统计

来源：`runs/v3/generation/ledger.jsonl`，命令 `python3 scripts/v6_m0_update.py` 与手工统计。

| 指标 | 数值 | 说明 |
| --- | --- | --- |
| 唯一任务 id 上传 | 180 | v3 + WP3 + rebuild + M3 |
| 唯一任务下载成功 | 171 | 成功率 **95.0%** |
| failed | 8 | 服务端失败 |
| uncertain | 12 | 轮询超时/状态不明 |
| upload_failed | 5 | 创建前上传失败 |
| 平均耗时 | 949.6 s | 含轮询等待 |
| 中位耗时 | 387.0 s | 同上 |

- 统计包含 M1 的 144 份 WP3、M0 的 22 份 v3 重建、M3 的 6+6+6 次现场调用。


## 已知限制（不隐藏）

| 项 | 状态 | 来源 |
| --- | --- | --- |
| M1 逐视角 KA6 | 13/15 通过，中位 IoU 0.994；moon_rock_05 因渲染网格与 truth_v2 不一致失败 | `runs/v6/m1/view_ka.csv` |
| M1 逐视角 KA1/KA5 | 13 视角试跑 0/13；视角级 V/U 为深度反投影近似，KA1 scale 1.118、KA5 切面为空 | `runs/v6/m1/view_ka15.csv` |
| M0 失联任务 | 15 个（v3 9 + C2 6），原输入图与任务号均缺失 | `dist/v6/lux3d_manifest.json` |
| M3 E2 第二眼 | 已单独拍摄并准入（0/4），未在连续时间线内实时重拍 | `runs/v6/m3/E2/admission_second.csv` |
| M2 leg-only | 0 个；V5 逐动作 rehearsal 文件随旧沙箱丢失 | `runs/v6/m2/leg_only.csv` |
