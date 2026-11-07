# V7 状态

## 2026-11-07

- 安装 `v7_bundle.tar.gz`，sha256 全部匹配；应用 `docs/v7/v3_core_detour_params.diff`；`py_compile` 通过。
- WP1 T1–T6 回归：沙箱上全过（mujoco 3.17.0；本地 4.0 会因机器人签名不兼容失败，已记录）。
- KA9：`0.45 → y_max 0.389`、`0.75 → 0.688`、`0.75/leave 2.3 → 1.09`，与负责人实测一致；`KA9 FAIL` 为横向滞后，记录不阻塞。
- `docs/v6/LUX3D_CALL.md` 已写好并推送（REVIEW_R3 收尾项）。
- §3.1 只看正面一臂：沙箱完成，退出码 0；`final_x=22.0109`、`t_end=96.78 s`、`arrived=true`。
  - E1：OBS_CONS 选 R2，pass；E2：R1，pass。
  - 拉回 `runs/v7/route_obs/`：8568 个文件、189 MB，sha256 清单与沙箱逐文件一致。
  - 联系表：`docs/v7/contact_obs.png`（已检查：岩石有贴图、无空心/碎片，地面与天空正常）。
- §3.4 准备完成：12 个条件（3 岩石 × 4 太阳）的全部 `photo/overlay/obs/inputs/stats/lux_request` 与 `truth_world.stl` 已拉回，195 个文件、209 MB，sha256 与沙箱一致。
  - 深度分割 IoU：0.9793–0.9823（≥0.9，通过）。
  - 只看亮度对照：`iou_naive_vs_render` 0.2653–0.9993，`naive_over_truth_px` 0.999–3.684，与 SPEC 表格一致。
- §3.4 Lux3D：72 个任务一次性提交（12 条件 × 6），**64 成功 / 8 失败**；失败任务按规则重提一次后仍失败，已在各自 `lux_result.json` 记 `status=failed`，流程继续。
  - GLB：`assets/v7/lux/<task_id>/tex_mesh.glb`，共 64 个、481 MB（LFS）。
  - 请求与结果文件：12 个条件各自的 `lux_request.json` / `lux_result.json`。
- §3.4 评估完成（沙箱，退出 0）：72 行评估写入 `eval_rows.json`，12 条件汇总写入 `summary.json`。原文如下：

```json
{
  "A_naive|high_side": {
    "n": 6,
    "admitted": 4,
    "median_abs_rear_m": 0.051,
    "median_footprint_ratio": 0.661,
    "median_hidden_iou": 0.6508
  },
  "A_naive|low_behind": {
    "n": 6,
    "admitted": 4,
    "median_abs_rear_m": 0.036,
    "median_footprint_ratio": 0.737,
    "median_hidden_iou": 0.6954
  },
  "A_naive|low_front": {
    "n": 6,
    "admitted": 2,
    "median_abs_rear_m": 0.048,
    "median_footprint_ratio": 0.603,
    "median_hidden_iou": 0.4548
  },
  "A_naive|low_side": {
    "n": 6,
    "admitted": 2,
    "median_abs_rear_m": 0.024,
    "median_footprint_ratio": 0.581,
    "median_hidden_iou": 0.4796
  },
  "B_depth|high_side": {
    "n": 5,
    "admitted": 3,
    "median_abs_rear_m": 0.034,
    "median_footprint_ratio": 0.781,
    "median_hidden_iou": 0.7083
  },
  "B_depth|low_behind": {
    "n": 5,
    "admitted": 3,
    "median_abs_rear_m": 0.046,
    "median_footprint_ratio": 0.781,
    "median_hidden_iou": 0.6601
  },
  "B_depth|low_front": {
    "n": 6,
    "admitted": 4,
    "median_abs_rear_m": 0.041,
    "median_footprint_ratio": 0.841,
    "median_hidden_iou": 0.7509
  },
  "B_depth|low_side": {
    "n": 6,
    "admitted": 2,
    "median_abs_rear_m": 0.019,
    "median_footprint_ratio": 0.768,
    "median_hidden_iou": 0.7277
  },
  "B_naive|high_side": {
    "n": 4,
    "admitted": 2,
    "median_abs_rear_m": 0.073,
    "median_footprint_ratio": 0.746,
    "median_hidden_iou": 0.5207
  },
  "B_naive|low_behind": {
    "n": 4,
    "admitted": 2,
    "median_abs_rear_m": 0.058,
    "median_footprint_ratio": 0.81,
    "median_hidden_iou": 0.6287
  },
  "B_naive|low_front": {
    "n": 6,
    "admitted": 0,
    "median_abs_rear_m": 0.136,
    "median_footprint_ratio": 0.363,
    "median_hidden_iou": 0.1798
  },
  "B_naive|low_side": {
    "n": 4,
    "admitted": 0,
    "median_abs_rear_m": 0.174,
    "median_footprint_ratio": 0.418,
    "median_hidden_iou": 0.1892
  }
}```
- §3.2 有想象一臂：沙箱完成，退出码 0；`final_x=22.0086`、`t_end=140.52 s`、`arrived=true`。
  - E1 look1：Lux3D 6/6 成功，准入 5/6，分支 accept，执行 R1，pass（t=52.7）。
  - E2 look1：Lux3D 6/6 成功，准入 0/6 → 侧移 0.42 m 第二眼（yaw 2.8°）。
  - E2 look2：两视图 `imgs` 3 个任务（组合图）成功，仍 0/3 → 回退 OBS_CONS，执行 R1，pass（t=138.24）。
  - 联系表：`docs/v7/contact_full.png`（已检查：三行观测均有贴图、无空心/碎片，地面与天空正常）。
  - 拉回 `runs/v7/route_full/`：21365 个文件、424 MB，sha256 清单与沙箱逐文件一致。
- V7.1 补丁已安装（sha256 通过、`py_compile` 通过），提交 `eccf3716c`；route_full 的 E2 look2 已标记作废（`runs/v7/route_full/INVALID_E2_LOOK2.md`）；LUX3D_CALL §6 已改为真实两图规程。
- `route_full_r2`：E1 look1 复用命中（`look1_lux_reused`）；E2 look1 未命中复用——A/B/C 输入图 sha256 与旧运行不同（相机位姿有微小差异），按规程记为未命中并提交 6 个新任务继续，不拼图。
