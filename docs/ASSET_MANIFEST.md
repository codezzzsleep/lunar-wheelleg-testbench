# 资产封存清单（下一批任务书 §1）

沙箱 `/workspace/r1` 中的不可替代输入已回传本机仓库；派生大文件不入库，但都有确定性重建脚本。

## 1. 已持久保存（入库）

| 类别 | 路径 | 说明 |
| --- | --- | --- |
| 正式观测（4 配置） | `runs/unseen/delivery_v7/v7_20261030_r1/scan_obs2/<config>/` | 图像、深度、`observation.json`、相机快照、可见点 |
| 单视角/旧案例观测 | `runs/unseen/recovery_r3/obs_R03` | 两视角候选的 obs1 |
| 共同观察后状态 | `common_states/<config>/<soil>/seed<N>/` | `acquisition.json`、`state_snapshot.json`、`state_snapshot_s0.json`、逐方法决策 |
| 父候选与任务身份 | `runs/unseen/delivery_v7/v7_20261030/candidates/` | V7_R01_s1/s2、V7_R02_s1/s2、V7_R03_s1/s2、V7_R04_s1/s2 |
| 有效融合配置 | `configs/unseen_v7_r1_fusion_gapfill.json`、`configs/unseen_v7_r1_fusion_offset1.json` | 含 `shell_gap_fill` 语义与哈希 |
| canonical occupancy | `refuse_R01_s1/occ.npz`、`refuse_R02_s0.9/occ.npz`、`priors_R03/{B2F,B3F}/occ.npz`、`fine_R02_s0.9/occ.npz`、`fusion_diagnostics/tvocc_R03_s1_v3/occ.npz` | 与各自 `manifest.json` 的 `world_sha` 绑定 |
| 独立真值输入 | `runs/unseen/recovery_r3/stone_materials/*.stl`、`scan_assets/<config>/body{,_world}.stl`、`demo/.../inputs/truth_collision` | 真值几何与碰撞盒 |
| 决策与执行原始记录 | `matrix_all/matrix.jsonl`、`evaluation/*/decision*.json`、`evaluation/*/trajectory.jsonl`、`verify/*.json` | 逐键记录、决策 SHA、轨迹 |

## 2. 不入库但可确定性重建

| 类别 | 重建方式 |
| --- | --- |
| 共同状态的观测栅格（`observation/*.npy|*.png`，约 200 MB） | `scripts/v7_acquire_states.py --plan plans/r1_states_plan.json` |
| 扫描观测（`scan_obs2`） | `scripts/v7_scan_observations.py --cases ... --scales ...` |
| 派生 STL / box 并集 | `scripts/v7_rebuild_from_occ.py`、`scripts/collision_box_union.py`（输入为已入库 `occ.npz`） |
| 融合网格 | `scripts/fuse_observed.py`（输入为已入库观测 + 父候选 + 配置） |

## 3. 未持久保存（如实说明）

- 沙箱 `/workspace/r1` 中 `refuse_*`、`priors_*`、`fine_*` 的**融合网格 STL 与 box 分片**未回传（合计约 400 MB），
  仅保留 `occ.npz`、`manifest.json`、`effective_config.json` 与碰撞测量；需要时按上表重建。
- 沙箱上 `fine_R02_s0.9`（1.25 mm 对照）保留 `occ.npz` 与 `manifest.json`，网格未回传。

## 4. 3280c741 矩阵的状态

`matrix_all/` 标记为 **实现待更正（implementation pending correction）**：

- 保留原始 `matrix.jsonl` / `summary.json`，不删除不利记录；
- "216 键齐全"与"46/126/44 重算一致"保留；
- **暂停使用**以下科学解释：U_truth 固定动作、代价恒为 9e9、空可见量导致的动作退化；
- 更正后的结果另建目录，不改写本目录。
