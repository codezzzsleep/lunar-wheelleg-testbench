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
