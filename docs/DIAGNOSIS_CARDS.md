# R1 阻断诊断卡（2026-10-31）

每张卡按任务书 §五 的十项填写。**未定位的写未定位，不把 A0 解释成物理不可通行。**

---

## 卡 1 · 两视角更新体的碰撞资格

1. **期望**：更新后的候选同时满足可见双视角（IoU≥0.90、P95≤5 mm、freespace≤0.05）与碰撞（IoU≥0.95、双向 P95≤5 mm），从而进入正式池并重预演。
2. **实际**：可见双视角通过（obs1 0.9803/1.669/0.0126，obs2 0.9837/1.761/0.0108）；碰撞 IoU 0.8832（2.5 mm 并集）与 0.9025（2 mm 并集），均 < 0.95；c2s 从 5.026 mm 降到 4.000 mm。
3. **代码**：`scripts/collision_box_union.py::occupancy_from_mesh`、`scripts/collision_occupancy_metrics.py::exposed_faces / box_surface_distance`、`scripts/v7_update_two_views.py::voxel_intersection`。
4. **最小复现**：
   ```bash
   /opt/lunar/bin/python scripts/collision_box_union.py \
     --mesh runs/.../tv_R03_s1/body_fillholes.ply --out /tmp/c1 --pitch 0.002 \
     --hypothesis-id tv_fh002
   /opt/lunar/bin/python scripts/collision_occupancy_metrics.py \
     --mesh runs/.../tv_R03_s1/body_fillholes.ply --collision /tmp/c1 \
     --out /tmp/c1/metrics.json --eval-pitch 0.003 --parity full
   ```
   输入：`body_fillholes.ply`（310,156 面，watertight=true，由交集体补洞得到）。
5. **原始结果**：2.5 mm → `{"iou":0.8832,"s2c_p95":1.123,"c2s_p95":5.026}`；2.0 mm → `{"iou":0.9025,"s2c_p95":1.0,"c2s_p95":4.0}`；退出码 0。
6. **机器**：CNB 沙箱 8 vCPU / 16 GB；`MUJOCO_GL=osmesa`；峰值 RSS 约 0.7–1 GB。
7. **已尝试**：
   - 原网格直接测 → 非水密，`source_volume_defined=false`，测量无效；
   - 体素填充闭合 → watertight，但凹处被填平，可见 freespace 0.3988/0.2199，形状已变，0.9684 的 PASS 作废；
   - 仅补洞 + PLY → watertight 且形状保持，测量有效，得到上面两个 IoU。
8. **有证据的原因**：并集体素越细，box 并集越贴合表面，但 IoU 提升幅度递减（0.8832→0.9025，步长 0.5 mm 只 +0.019）。
   **仅为猜测**：剩余差距是否来自"box 并集只能表达轴对齐长方体"这一表示限制；未做自适应 box/多层并集验证。
9. **卡点**：需要一个能在 0.95 以上的碰撞表示；当前并集表示未达标。**根因未定位到可修复的单一缺陷。**
10. **不受影响**：可见双视角结论、两视角交集构造、其余候选资格、评价器已知答案。

---

## 卡 2 · 完整状态续接（同场景恢复）

1. **期望**：真值续行在**同一物理场景**内恢复（机器人签名、模型/场景身份、mjstate、时钟、控制、导航、摩擦、土壤内部状态），并可通过哈希校验拒绝篡改。
2. **实际**：`same_scene` 在 R03 上被拒绝（场景签名不符：观测场景与真值场景不是同一 scene），续行**自动降级为 `project`** 并继续，记录 `state_mode=project`。A/B/C/D 四项合同测试通过（同场景拒绝、投射不搬材质、土壤改变签名）。
3. **代码**：`scripts/wheelleg_env.py::restore_state(mode=...)`、`scripts/v7_state_contract_test.py`。
4. **最小复现**：`bash scripts/v7_state_contract_test.py`（产物 `verify/state_contract.json`）。
5. **原始结果**：`{"A_same_scene_ok":true,"B_same_scene_rejected":true,"C_project_ok":true,"C_material_not_transferred":true,"D_soil_changes_scene_sig":true}`。
6. **机器**：本机 8 GB / MuJoCo 3.17.0 / OSMesa。
7. **已尝试**：把真值续行改为显式 `project` 并在记录里标注限制；未尝试构造"真值与观测同场景"的布置。
8. **有证据**：签名不符是真实原因（`scene_sig` 不同）。
   **猜测**：是否值得为真值续行重新搭建同场景布置，取决于是否要求"逐位相同恢复"。
9. **卡点**：本批**没有一次真正的 `same_scene` 真值续行**；所有续行都是 `project`，能力上限按 project 计。
10. **不受影响**：可见几何、矩阵、决策规则。

---

## 卡 3 · 独立验证状态

1. **期望**：验证初态是**新增采集**的独立状态（不同出生状态、不同驾驶过程），不能把驾驶 seed 0/1/2 的快照改名成验证 seed 3/4/5。
2. **实际**：验证状态 3/4/5 是 drive seed 0/1/2 的**重编号**，`independent_of_planning=false`；且 seed 1/2 未停稳，列为 `unsettled`，不进"全部合格"分母。
3. **代码**：`scripts/eval_six.py::run_validation`、`scripts/v7_closed_loop.py`（`validation_continuation` / `validation_state_source`）。
4. **最小复现**：读 `runs/.../observation/validation_states_provenance.json` 与 `verify/r1_report.json` 中的 provenance 字段。
5. **原始结果**：`{"independent_of_planning": false, "n_states": 3, "usable": 1, "unsettled": [1,2]}`（字段名以文件为准）。
6. **机器**：本机。
7. **已尝试**：如实标注来源，不再声称"3 个独立初态"。
8. **有证据**：重编号是事实。**未做**：新采集独立状态。
9. **卡点**：缺**新采集**的停稳状态；需要新的驾驶-停稳-采集流程，属于新实验。
10. **不受影响**：六方法对照可用同一冻结状态集比较，但结论只能写"在同一冻结状态集上"。

---

## 卡 4 · 资产可复现性

1. **期望**：新目录能从仓库内容重建全部正式资产，或至少能取得相同字节的网格。
2. **实际**：代码层可复现（已知答案 8/8、反例中真生产项可通过）；**数据层不可复现**：`*.stl/*.ply` 被 `.gitignore` 排除，原始远端主机已回收，`R02_s2/R04_s2` 的中间网格只在临时机器上存在过。
3. **代码**：`.gitignore`（`runs/**/*.stl` 等）、`scripts/fuse_observed.py`（重建入口）。
4. **最小复现**：
   ```bash
   cd /tmp/clean_repro && git archive HEAD | tar -x
   .venv/bin/python scripts/v7_collision_known_answers.py   # 8/8
   .venv/bin/python scripts/run_r1.py --audit               # 报 7 项输入缺失
   ```
5. **原始结果**：`{"verdict":"PASS","n_pass":8,"n":8}`；audit 输出 `缺少 7 个输入`。
6. **机器**：本机。
7. **已尝试**：把可用的小网格（父候选 align，0.4–1.5 MB）与补洞/闭合版本回传并提交；大 STL 仍排除。
8. **有证据**：缺失清单来自 audit。**未做**：把大资产放到稳定存储。
9. **卡点**：缺一个"大资产的稳定存放 + SHA 清单"机制。
10. **不受影响**：评价器、反例、入口逻辑、报告。

---

## 卡 5 · 同场景续行：签名成立，但直接/恢复对照首帧就分叉

1. **期望**：在同一个 `WheelLegEnv` 实例内完成 驾驶 → 停稳 → 采集 → 续行；保存→恢复→再继续 与 直接继续 **逐帧一致**。
2. **实际**：`same_scene_holds = true`（`scene_sig` 在恢复状态前、采集后、直接续行后、恢复续行后四处相同），
   但两条续行**第 0 帧就分叉**：`max_abs_diff_m = 2.38e-4`；终值差得更多
   （direct `final_x = 15.89 m`，save_restore `final_x = 1.14 m`）。
3. **代码**：`scripts/observe.py::capture_observation`（本次新提取）、
   `scripts/v7_same_env_loop.py::snapshot/restore/run_episode`。
4. **最小复现**：
   ```bash
   MUJOCO_GL=osmesa /opt/lunar/bin/python scripts/v7_same_env_loop.py \
     --case cases/unseen_v1/R03.json \
     --state runs/unseen/delivery_v7/v7_20261030_r1/observation/drive_R03_b/drive_observe.json \
     --action R1 --out runs/unseen/delivery_v7/v7_20261030_r1/evaluation/same_env_R03
   ```
5. **原始结果**：`same_env_report.json`：
   `{"same_scene_holds": true, "observation_seconds": 0.0, "execution_seconds": 18.0,
     "direct": {"final_x": 15.8917}, "save_restore": {"final_x": 1.1382},
     "first_divergence": {"frame": 0, "max_abs_diff_m": 0.000238}}`
6. **机器**：CNB 沙箱 8 vCPU / 16 GB，MuJoCo 3.17.0，OSMesa。
7. **已尝试**：
   - 只存 qpos/qvel/time → 首帧 2.4e-4；
   - 改为 `mj_getState/mj_setState(mjSTATE_INTEGRATION)` + `qacc_warmstart` + `ctrl` + `act` + env 字段（`nav_target_y`、`n_physics`）→ **仍是首帧 2.4e-4**，说明还缺其它影响第一步的量。
8. **有证据**：状态合同不完整（补了 warmstart 也没有消除分叉）。
   **仅为猜测**：`run_episode` 用 `sk.act(None, rs)` 把观测传成 `None`，技能内部可能依赖观测，
   导致两条路径的**输入**就不一致；`direct.final_x = 15.89 m` 已远超目标 2.6 m，像是控制发散而非物理差异。
9. **卡点**：需要先把续行步进换成生产路径（`runner.EpisodeRunner`，带真实 obs），再判断分叉来自状态还是输入。
10. **不受影响**：两视角更新资格、闭环决策与真值续行（走 `project` 模式的那条）、碰撞评价器。
