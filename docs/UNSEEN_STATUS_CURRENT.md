# 当前状态入口（唯一）

main 见 `git log`；已推送。旧报告保留原样。

## 1. 本批：真实 Lux3D 批次（6 任务已全部终态）

| 计划项 | task_id | 石头 | GLB 尺寸 (m) | 判定 |
| --- | --- | --- | --- | --- |
| G_R01 | 4463022 | R01 | 0.008 × 0.012 × 0.005 | **degenerate_scale** |
| G_R01_rep2 | 4463124 | R01 | 0.012 × 0.023 × 0.009 | **degenerate_scale** |
| G_R01_rep3 | 4463154 | R01 | 0.013 × 0.022 × 0.009 | **degenerate_scale** |
| G_R02 | 4463077 | R02 | 0.120 × 0.039 × 0.109 | ok，清理通过 |
| G_R03 | 4463082 | R03 | 0.150 × 0.034 × 0.150 | ok，清理通过 |
| G_R04 | 4463091 | R04 | 0.120 × 0.046 × 0.120 | ok，清理通过 |

**关键发现（系统性，非随机）**：R01 输入（窄高石）的三个**独立**生成任务都返回约 1 cm 的
退化几何。这不是单次波动，而是该输入在 G1-Turbo 下的系统性行为。
R01 因此**没有可用候选** —— 而 R01 正是两轮扫描中唯一有动作取舍的案例。

预算：累计 24 任务 / 480 上界，核验扣费仍 `unknown`。未重提失败项、未加第七项。

## 2. 候选处理与工程资格

| 候选 | 清理 | thin_ratio | IoU | P95 mm | freespace | strict | planning_eligible |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G_R02 | ok | 0.316 | 0.745 | 10.7 | 0.472 | 失败 | 否（IoU<0.85） |
| **G_R03** | ok | 0.228 | **0.885** | 7.94 | 0.182 | 失败 | **是** |
| G_R04 | ok | 0.386 | 0.768 | 29.0 | 0.477 | 失败 | 否（IoU<0.85） |

**G_R03 是首个工程合格的真实 Lux3D 候选**（task 4463082）。

## 3. 正式 H5 与六方法（R03 组，真实候选）

单视角闭环（`pipeline_H5_R03/`）：候选 world `9ba49243…`、collision `59ba750d…`（CoACD 2 部件）、
真值 `436b75d2…` 独立；预演后选 **R1**，真值 **3/3**，盲走 **3/3**。

六方法 v4（`six_v4/`，同一真值、初态 0/1/2）：

| 方法 | 自选动作 | 执行 | 成功 | 均代价 |
| --- | --- | --- | --- | --- |
| B0_blind | R1 | 3/3 | 3 | 6.420 |
| B1_height | R1 | 3/3 | 3 | 6.420 |
| B2_box | D1 | 3/3 | 3 | 6.387 |
| B3_mirror | R1 | 3/3 | 3 | 6.420 |
| **H5_lux3d（真实 G_R03）** | **R1** | 3/3 | **3** | **6.420** |
| U_truth | D1 | 3/3 | 3 | 6.387 |
| 宽度规则（诊断） | R1 | 3/3 | 3 | — |

**H5 与盲走、镜像完全相同；真值上限与盒子先验只是略便宜（6.387 vs 6.420）。无收益证据。**

## 4. 阶段预算与终止（任务 A）

- 新协议 `configs/unseen_phase_protocol_v2.json`：总体 30 s，观察 ≤12 s 且计入总成本
- `_check_termination()` 统一倾覆/越界/出场地/超时；`step_drive` 现在返回真实终止
  （此前固定 False）——实测超时 `time_limit`、倾覆 `tipped` 均触发
- 成本口径修正：成功 cost 是**绝对时间**已含观察，不再重复加 `observation_seconds`；
  现分列 `observation_seconds` / `exec_seconds` / `total_seconds`
- 30 s 复跑：R2/S1 从被 12 s 截断变为跑满 30 s 才超时；R1/L1/L2/D1/D2 仍在 11.86 s **物理倾覆**

## 5. 状态合同（任务 B）

- `save_state`：`mj_getState` 全量物理状态 + `data.time`/`env.t` 及偏移 + `ctrl` +
  `xfrc_applied` + `prev_action` + 接触计数 + `passed_at`/`first_contact_t` +
  驾驶符号/历史 + 每个 geom 摩擦 + 土壤状态 + `robot_signature`（关节/执行器映射）+ `state_hash`
- `restore_state`：**重算**哈希并比对；schema/维度/签名不符一律拒绝；
  跨模型只恢复公共 geom 前缀并记录跳过数
- 反例 **12 项通过**：哈希损坏、签名不符、缺字段、维度不符、偷偷 reset、土壤状态
- 直接继续 vs 恢复后继续：reason 相同、`final_x` 3.672 相同、`t_end` 差 0.0

## 6. 统一真值口径与观测协议（任务 C）

- `look_again_loop` 现在先把真值 physicalize 成 world + CoACD，与六方法共用同一 `collision_sha`
  （实测 truth collision `08fba9fe…`、21 部件），不再用单 mesh 凸包
- 停止线与锚点改用观测 `x_front`，不读 case 完整 D/背深
- 观测协议 `observation-protocol/v1`：`observation_protocol()`/`is_usable()` 唯一定义，
  正式闭环复用同一函数；旧 12° 前向门保留为 diagnostic
- 完整链路 `look_loop_R01_v3/`：基线 0.529 m、视线角 11.67°、mask 32501、stable；
  筛选 kept；决策 A0；真值续行 A0→abort、R1→tipped

## 7. 页面

注册 10 个运行（含 `six_v4`、`pipeline_H5_R03`、`look_loop_R01_v3`、`six_dev2`）。

## 8. 自验

`verify_r3` **55/55**；全套单元测试 **130 项通过**（1 skip）。

## 9. 状态判定

- **delivery_status = PARTIAL**：真实批次完成、首个合格候选跑通正式闭环与六方法；
  R01 无候选、行驶观察已达标（10/10）但未与真实候选串成"因分歧而观察"的触发逻辑。
- **evidence_integrity = PASS（限本批覆盖）**
- **capability_status**：生成→清理→配准→CoACD→正式预演→真值执行 全链路成立；
  **R01 组未建立**（生成退化）
- **benefit_status = NOT_ESTABLISHED**：H5 与盲走/镜像同分；宽度规则在 R01 已达上限

## 10. 仍未完成

| 项 | 依赖 |
| --- | --- |
| R01 的真实候选 | 三次独立生成均退化；需换输入表达或换档位，属新付费决策 |
| "因候选分歧触发观察"的实际运行 | 当前候选一致，未触发 |
| 月壤几何下陷、坡面滑转、1000 回合、吞吐 | 按纲领后续 |
| 浏览器像素验证 | 环境无浏览器 |
