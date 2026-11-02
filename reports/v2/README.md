# v2 批次审阅包

这是**可审阅的小结果集**（只含 JSON/Markdown，不含网格与观测栅格）。完整网格在沙箱
`/workspace/lunar-lab/runs/unseen/delivery_v7/v7_20261030_r1/`，不入库。

- 代码与协议：`d1f384fe7`（本目录随后续结果更新）
- 状态入口：[docs/CURRENT_STATUS.md](../../docs/CURRENT_STATUS.md)
- 接续说明：[docs/V2_HANDOFF.md](../../docs/V2_HANDOFF.md)

## 1. 融合缺陷修复（已定稿）

v2 的 `shell & ~dilate6(parent_inside)` 在壳层与父先验之间挖出 1 体素空隙，再用
`largest_component` 二选一。P06·S1 上：

- B1 的父先验 3,569 体素被整块删除（`kept_ratio=0`），只剩壳层；
- C1 的观测壳层 4,927 体素被整块删除，可见面 IoU 0.806、strict 不通过；
- A1 的父先验 4,930 体素被删除。

v3 改为按像素抑制壳层、含父先验组件无条件保留。修复后 A1/B1/C1 的
`kept_ratio` 均为 1.0，strict 通过（A1 0.9236 / B1 0.9300 / C1 0.9252）。
逐体素数字见 [voxel_fate.json](voxel_fate.json)。

**已知答案核查**用的是体素去向，不是 fused strict：真值网格经 align24 后作父先验，
451,068/451,068 体素保留；壳层与无壳层的 freespace 为 0.0668 / 0.0666，说明超限来自
2.5 mm 体素化与等值面提取，不是壳层造成。没有放宽任何阈值。

## 2. B3_F 改标与生成消融（已定稿）

- B3_F = **镜像补全**（`comparison_label=mirror_completion`），不是壳层对照；
- 生成贡献消融 = `fuse_observed --ablate-generated-unknown`：同一候选、同一 parent、
  同一栅格、同一状态与预算，只删除未知区父先验体素；
- 协议修订 A1 rev2 已写入 `plans/v2_protocol.json`。

## 3. 八行主表：两种土壤口径

### 5 点最坏集（`5pt/`）

20 状态 × 非 Lux 六行 + 已完成的 10 个 Lux 状态。**该口径在当前动作库上退化**：
20 个状态里 16 个连真值参考 U_truth 都是 A0，只有 4 个状态真值有可行动作。
三关键状态（P06·S1、P06·S3、P58·S2）的 first/multi/消融也全是 A0。
因此 5 点集保留为敏感性附录，不作为主比较。

### nominal 当前土壤（`nominal/`，生成中）

主比较改用 nominal（与已登记的 v2 结果一致），5 点集作为敏感性。
nominal 规划复用已融合资产，不重复融合；目前 P06·S1 已得到有区分度的结果：
first A1 = D2 通行，multi = A0，待补 A1 消融。

## 4. 三关键状态（5 点，已定稿）

| 状态 | 候选 | fused strict | kept_ratio | first | multi | multi 消融 |
| --- | --- | --- | --- | --- | --- | --- |
| P06·S1 | 6/6 | 5 通过（C2 未过） | 1.0 | A0 | A0 | 待补 |
| P06·S3 | 6/6 | 5 通过（B1/C2 未过） | 1.0 | A0 | A0 | 待补 |
| P58·S2 | 5/6（A2 融合被 OOM 杀） | 5 通过 | 1.0 | A0 | A0 | A0 |

在 nominal 口径下 P06·S1 的 full multi = A0；早期 v3 预演的 multi 消融为 L2 通行，
方向是“生成先验使多候选更保守”。最终数等 nominal 消融补跑后更新。

## 5. 必报的口径问题

20 状态筛选的 C 扫描用 `visible={}` 跑真值动作，正式规划器用真实可见量，D1/D2 的
触发参数不同。用正式口径复算时，P01·S1/P01·S3 等状态的真值参考已变成 A0；主表
U_truth 行按正式可见量记，真值无动作的状态记 `safe_stop_no_reference`，不算
“过度保守”。

## 6. 文件

- `5pt/<STATE>/multi.json`：Lux3D 六候选、first/multi/first_ablation、候选 fused 质量；
- `5pt/<STATE>/nonlux.json`：B1_height / B2_F / B3_F / E25D_block / E25D_fill / U_truth；
- `table/main_table.json|md`：当前部分八行表（5 点，missing 为未完成状态）；
- `key_states/*.multi.json`：三关键状态完整决策矩阵；
- `key_states/truth_*.manifest.json`：已知答案的融合清单；
- `nominal/`：主比较结果，生成中。
