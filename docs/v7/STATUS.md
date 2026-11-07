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
- V7.1 补丁安装提交 `eccf3716c`（含作废标记与 LUX3D_CALL §6）；`route_full_r2` 第二眼真实两图与结果提交 `edea14392`。
- `route_full_r2`：E1 look1 复用命中；E2 look1 未命中（输入图 sha256 与旧运行不同），提交 6 个新任务：4 成功、2 失败（C1/C2 重提一次仍失败），准入 **0/6**。
- E2 look2 真实两图任务（`lux3d_client.submit_img_to_3d_multi`，`api_field=imgs`、`n_images=2`）：
  - M1 `task_id=4833278`，status=3（ok）；
  - M2 `task_id=4833341`，status=3（ok）；
  - M3 `task_id=4833387`，status=3（ok）；
  - 准入 **0/3**。
- E2 分支：look1 `reject_all`、look2 `reject_all` → 回退 OBS_CONS，执行 **R1**，真值结局 **pass**（t=138.24，wheel contact）。
- 全程：`final_x=22.0088`、`t_end=140.46 s`、`arrived=true`，退出码 0。
- 联系表：`docs/v7/contact_full_r2.png`（已检查：三行观测有贴图、无空心/碎片，地面与天空正常）。
- v7.2 补丁提交 `f5d534879`；真值检查提交 `e090003c0`。
- 真值检查（沙箱）：
  - E1 look1：`v5_scale_ratio=1.0571`，`v72_scale_ratio=1.0000`；
  - E2 look1：`v5_scale_ratio=1.1132`，`v72_scale_ratio=1.0000`；
  - E2 look2：`v5_scale_ratio=1.1132`，`v72_scale_ratio=1.0000`。
- **重新决策：与 REVIEW_V7_R2 §0.3 不一致，按 §2.2 停下，未运行影子实验重评估、未重跑路线。**
  - `summary.json` 的 `compare`：
    - `E1: {"v72_action": "D2", "executed": "R1", "same": false}`
    - `E2: {"v72_action": "R1", "executed": "R1", "same": true}`
    - `all_same: false`
  - 准入数与 §0.3 一致：E1 采纳 3/6（B1、B2、C1）；E2 look1 拒绝 0/4；E2 look2 采纳 1/3（M2）。
  - 唯一差异：E1 的 v7.2 选择是 **D2**（`full_chosen` 与 `obs_chosen` 均为 D2、`worst_rule` 也是 D2），而 §0.3 预期与实际执行均为 **R1**。
  - 输出已拉回 `runs/v7/route_full_r2_v72/`（17644 文件、305 MB，sha256 与沙箱逐文件一致）。
- v7.3 补丁提交 `b3b89dd05`；清单修正提交 `920635891`（根 `PATCH_SHA256.txt` 归 V8，V7.3 在 `docs/v7/PATCH_SHA256_v73.txt`）。
- §2.1 可复现性检查（沙箱，两次）：
  - `--span 32`：`rep0=rep1`（三种扰动 identical），`rep0=ref0`（三种 identical）；与 `ref1` 扰动 0 不同（7.04 s 成功 vs 60 s 卡住），扰动 1/2 数值上也有 10⁻⁷ 级差异但结局均为成功。
  - `--span 4`：`rep0=rep1`（三种 identical）；`rep0=ref1`（三种 identical）；与 `ref0` 扰动 0 不同（卡住 vs 成功），扰动 1/2 数值差异、结局同为成功。
  - `platform`：python 3.12.16、x86_64、8 核、mujoco 3.17.0、numpy 2.5.4。
- §2.2 按路线条件重新决策（`route_full_r2_v73`，退出码 0）：
  - `rehearsal_ground_span_m: 32.0`；
  - `compare`: `E1 {v72_action: R1, executed: R1, same: true}`，`E2 {v72_action: R1, executed: R1, same: true}`，`all_same: true`；
  - E1：采纳 3/6，`full_chosen=R1`、`worst_rule=R2`、`obs_chosen=R2`；E2 look1 拒绝 0/4，look2 采纳 1/3（M2），`full_chosen=R1`。
- 结论（照 REVIEW_V7_R3 §3 抄录）：
  > E1 直行（R1）的预演判定依赖预演地面的高度场尺寸：路线条件（32 m）下 R1 在 2/3 份准入候选里安全，决策为 R1，与实际执行相同；4 m 地面下只在 1/3 份里安全，决策为 D2。两种地面都是平的，差别只在数值层面，说明这个临界动作的安全判定不稳健。V7 到此收尾，不重跑路线。
