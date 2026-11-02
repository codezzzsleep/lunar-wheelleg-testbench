# v2 现状与下一步（给下一次继续用）

最后更新：2026-11-02 深夜 · 起点 `84a3c33b8` · 批次进行中

## 已经确定的

1. **融合缺陷与修复**：v2 的 `shell & ~dilate6(parent)` + `largest_component`
   会把壳层和父先验隔开再二选一；P06·S1 B1 父先验 3,569 体素被删、C1 壳层
   4,927 体素被删。v3 改为按像素抑制壳层 + 含父先验组件无条件保留；
   B1/C1 kept_ratio 均回到 1.0，fused strict 通过。
2. **已知答案**：真值网格走 align24 后融合，父先验 451,068/451,068 保留；
   壳层/无壳层 freespace 0.0668/0.0666 → 2.5 mm 体素化本身就有此误差，
   不是壳层造成，不许用放宽阈值掩盖。
3. **B3_F = 镜像补全**，不是壳层对照，也不能替代生成消融。
   生成消融：`fuse_observed --ablate-generated-unknown`（同候选/同栅格/同预算，
   只删未知区父先验）。
4. **主表土壤**：冻结 5 点集 p0..p4（`soil_c/soil_c.json` 的 points），
   与 20 状态筛选一致；nominal 仅诊断，三档仅敏感性。
5. **筛选口径不一致（必报）**：C 扫描用 `visible={}` 跑真值，正式规划用真实
   可见量；已发现 P01·S1、P01·S3 真值参考在正式口径下为 A0。U_truth 行按正式
   可见量记，真值无动作的状态不能算过度保守。

## 正在跑（沙箱后台，断点续跑）

- `scripts/v2_batch20.py --only C`：20 状态 × 6 候选融合/碰撞/5 点规划 +
  A1 生成消融；输出 `runs/.../v3batch/<state>/multi.json`。
- `scripts/v2_batch20.py --only D`：20 状态 × 非 Lux 六行 5 点规划；
  输出 `v3batch/<state>/nonlux.json`。
- `v2_multi.py --rock P58 --state S2 ... --soils points --ablate`：
  第三关键状态的完整消融；输出 `v3batch/P58_S2/`。
- 旧 v3 结果在 `v3batch_pre_final/`，不参与主表。

## 完成后立刻做

1. `python scripts/v2_main_table.py --states <v2_main_states.json> --root .../v3batch --out .../v3table`
   → 八行主表 `main_table.json/.md`；
2. 修复 `multi_done` 判为失败的候选（OOM 可能留下 `fusion_invalid`），重跑该状态；
3. 主表 Lux3D 行带 `strict.pass` / `kept_ratio` / `first_ablation`（多候选消融
   只在 P06·S1/P06·S3/P58·S2 与“full multi 通过”的状态上补）；
4. 更新 `CURRENT_STATUS.md`、本文件，统一汇报；生成素材页（八行表 + 壳层/
   消融对比 + 体素去向图）。

## 不能声称的

- 多候选提升判断能力；
- Lux3D 在 2.5D/镜像补全解决不了的状态上取胜；
- 生成先验有增量（P06·S1 的 full multi 与消融结果方向相反，需完整批次复核）。

## 关键文件

- 协议：`plans/v2_protocol.json`（A1 rev2）
- 状态清单：`runs/.../v2_main_states.json`
- 融合：`scripts/fuse_observed.py`（v3），`configs/unseen_v7_r1_fusion_gapfill.json`
- 多候选：`scripts/v2_multi.py`；非 Lux 六行：`scripts/v2_nonlux_rows.py`
- 批处理：`scripts/v2_batch20.py`；主表：`scripts/v2_main_table.py`
- 依赖锁：`requirements-lock.txt`
