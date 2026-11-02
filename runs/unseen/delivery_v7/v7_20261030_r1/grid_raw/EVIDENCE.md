# 原始证据包（本轮 168 条）

| 内容 | 路径 | 数量 |
| --- | --- | --- |
| 逐格预演矩阵 | `*/<state>/<family>/plan_matrix.jsonl` | 147 |
| 决策（CP.write_plan 产出） | `*/<state>/<family>/plan_decision.json` + `plan.json` | 147 |
| 执行轨迹 | `*/<state>/<family>/trajectory.jsonl.gz` | 168 |
| 观测（含相机、可见量） | `*/<state>/obs/observation.json` + `rgb.png` + `mask.png` | 21 |
| 碰撞资产清单 | `*/<state>/*_coll/manifest.json(.gz)` | 147 |
| 状态快照（起始 qpos/qvel + 哈希） | `table.json` 的 `applied`/`state_hash` 字段 | 21 |

**未入库但可重建**：`depth.npy` / `visible_points.npy`（约 5 MB/状态，由快照重跑 `capture_observation` 重建）、
`h5_raw_parent/body.stl`、`h5f_fused/`（由 GLB + 观测 + `configs/unseen_v7_r1_fusion_gapfill.json` 重建）、
碰撞 `parts/`（由 manifest 的 boxes 与 `collision_box_union` 重建）。

重建命令：
```bash
python scripts/v7_rock_families.py --rocks <Pxx> --states <S1|S2|S3> --out <dir>
```
