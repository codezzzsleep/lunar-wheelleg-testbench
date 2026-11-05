# A 线 R3：按几何规划绕行的四档重筛

## 本步问题

按 REVIEW_R3 §3：绕行偏移与回位点由各臂自己的占据足迹算出，在 0.60/0.70/0.80/0.90 m
四档通道上重筛 H_vis ≥ 0.17 的状态，并检查是否出现 I/II 类价值。

## 命令

- `python3 scripts/v5_ka8.py`
- `python3 scripts/v5_a_r3.py --states <list> --channels 0.60,0.70,0.80,0.90 --out runs/v5/a_r3/<shard>`
- `python3 scripts/v5_a_merge.py`

## KA8（truth_v2）

| 量 | 结果 | 判据 |
| --- | --- | --- |
| PERFECT 偏移 | **0.445 m** | 真值半宽 0.145 + 0.30 = 0.445，通过 |
| PERFECT 回位点 | 1.415 m | 足迹最远 x + 0.25 |
| OBS_CONS 回位点 − 0.25 | **1.235 m** | 等于 U_shadow 最远 x，通过 |
| OBS_CONS 偏移 | 0.459 m | 比 PERFECT 多 0.014 |

## 结果表（52/56 组合）

- 14 个 H_vis ≥ 0.17 状态 × 4 档 = 56 组合；已合并 **52** 个；缺 4 个：`moon_rock_05_h1v0` 3 个、`rock_07_h1v0` 1 个（旧沙箱回收，未补跑）。
- **I 类 1 个**：`moon_rock_02_h2v1` @ 0.90
  - PERFECT：D2，pass
  - OBS_CONS：A0，safe_stop
- II 类 0 个。
- 其余组合三臂多在同一动作上通过，或 PERFECT 也退回 A0。

### 每状态几何量（节选）

| 状态 | 通道 | 偏移 PERFECT | 偏移 OBS | 偏移差 | U_shadow 后缘 − 真值后缘 |
| --- | --- | --- | --- | --- | --- |
| moon_rock_05_h1v1 | 0.80 | 0.545 | 0.593 | +0.048 | +0.226 |
| moon_rock_05_h1v1 | 0.90 | 0.545 | 0.593 | +0.048 | +0.226 |
| moon_rock_07_h2v0 | 0.80 | 0.535 | 0.559 | +0.024 | +0.034 |
| moon_rock_02_h2v1 | 0.90 | 0.574 | 0.648 | +0.074 | +0.114 |

- 偏移差与后缘差是同一枚硬币：阴影比真值长多少，OBS_CONS 的绕行就必须多绕多少。

## 价值场景的 C2

`moon_rock_02_h2v1` @0.90：

| 项 | 结果 |
| --- | --- |
| 候选/准入 | 6 / 6 |
| FULL 多数/最坏 | A0 / A0 |
| FULL 执行 | A0，safe_stop，3.00 s |
| OBS_CONS | A0 |
| PERFECT | D2，pass |
| 类型 | 无（FULL 未做出不同决策） |

- FULL 的候选几何在 3/3 扰动与 5 cm 横向余量下没有安全动作，退回 A0；不是“想象偏长选错方向”的问题。

## 未做到

- `moon_rock_05_h1v0` 与 `rock_07_h1v0` 共 4 个组合因旧沙箱回收缺失。
- 只有 1 个 I 类，且其 FULL 没有正例；B 线未完成。

## 根因

- 四档下大部分状态 PERFECT 与 OBS 同动作通过，说明“背面长度”在这些布置里没有改变可行动作；
  0.90 的 `moon_rock_02_h2v1` 是唯一例外，但 FULL 候选几何未提供安全动作。
- 不是通道未统一或绕行几何写死：KA8 与每行 offset/leave 均按各臂几何计算。

## 证据

- `runs/v5/a_r3/a_table_all.csv`
- `runs/v5/a_r3/*/a_table.csv`
- 每组合每臂：`runs/v5/a_r3/<shard>/<state>_<ch>/<arm>/rehearsal_3of3.json`
- `runs/v5/ka8/ka8.json`
- C2：`runs/v5/c2_a/moon_rock_02_h2v1_0.9/result.json`

## B 线状态（R3 §4）

- **B1**：`moon_rock_05_h2v1` 开阔场，公共函数跑 C2：
  - PERFECT D1 pass 7.74 s；OBS_CONS D1 pass 7.74 s；FULL L1 pass 8.78 s，6/6 准入。
  - FULL 决策不同但更慢，不满足 II 类（差值 1.04 s，小于 30% 或 3 s）。B1 的“省时案例”未成立。
- **B2**：未做。旧沙箱在重建两遭遇路线前被回收；新沙箱只迁了三个状态，WP8 路线未运行。
- **B3**：`dist/v5/showcase/manifest.json` 已生成（7 项，含 C0/C3/A/B1/C2 文本证据）；
  GLB 与执行记录未上传 Release `v5-showcase`，因为主机缓存里的 GLB 身份与 WP3 任务的 image_sha 不匹配，
  需要从旧沙箱的生成缓存重新取回，而旧沙箱已销毁。B3 不完整。

## 结论

- A 线按要求完成 52/56 组合；唯一 I 类 `moon_rock_02_h2v1@0.90` 的 FULL 仍为 A0，没有 FULL 正例。
- B1 无 II 类；B2/B3 因沙箱回收缺失。
- 不再调参；本轮到此收口。
