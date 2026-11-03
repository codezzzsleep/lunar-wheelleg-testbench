# 会话交接（SPEC_UNSEEN_RECOVERY_002）

> 本块由人工维护；`scripts/v3_docs.py` 生成 `CURRENT_STATUS.md` 时置顶拼接。
> 它是交接说明，不是第二份状态文档；数字口径仍以 v3 唯一源表为准。
> 最近更新：2026-11-03 17:15 +0800。

## 代码基准

- 实际 HEAD / origin/main：`f8ce2a1b7`。
- 审阅基线 `a984c8818` 因作者署名校验被重写为 `f8ce2a1b7`：tree/blob/message 逐字节不变，
  只有 32 个提交的 author/committer 从 `lunar-lab <lunar@local>` 改为
  `codezzzsleep <codezzzsleep@gmail.com>`。两者 `HEAD^{tree}` 相同（`0be7eaf…`）。
  旧 SHA 不再在 main 上；引用旧基准时请注明映射关系。
- 本轮实验代码身份：以包含本文件的提交为准；每次运行前记录 `git rev-parse HEAD`
  与代码树 SHA，脏工作区另存 patch 及 SHA。

## 沙箱与后台任务

- 当前有效沙箱：`cnb-ljh-1k6fm0sla-001.3a63e40a-b641-47b3-819f-dcf271429eef-07q@cnb.space`
  （8 核 / 16 GB / 512 GB；MuJoCo 3.17、ffmpeg、tmux、git-lfs 3.8）。
- 沙箱工作目录 `/workspace/lunar-lab`；其 git HEAD 仍是 `d1345d0`（2026-10-31）+ 193 个
  未提交改动。**代码权威在宿主 main**，同步方向为宿主 → 沙箱，`runs/` 不允许被 `--delete`。
- 当前无 tmux 常驻任务、无运行中的重任务；本文件不声称任何后台进程仍在运行。
- 旧地址 `cnb-qho-…`、`cnb-qbi-…` 已失效，不复用。
- 数据回传：`runs/v3/states/*/{decision,metrics,state.json,state_snapshot.json}`、
  `runs/v3/screen`、`selected.json/txt`、`states_index.json`、
  `generation/{tasks.json,ledger.jsonl}`、`control/`、`assets/v3/rocks` 已回传本机；
  `generation/cache`（4.7 GB）与全量 `states/`（7 GB）在后台继续同步。
- 密钥只从环境变量注入，不在仓库、文档、命令行或打包内；本文件不记录路径。

## 本轮已完成（工作包 A）

- A1：`step_command` 改为每个物理子步重算 PD；`step_drive` 与 `brake_step`
  走同一物理循环（每子步控制更新、土壤钩子、接触与计时）。
- A2：显式轮模式 `velocity | brake | coast`；旧调用语义保持不变；实际模式写入
  `_last_wheel_modes` 与状态快照。
- A3：`joint_velocity_targets_rad_s` 正确保存，不再记录为 None；维度与 NaN 校验。
- A4：`step_command` 每子步复用 `_check_termination`，终止后立即停止推进本控制步。
- A5：状态快照升为 `env-state/v2`，加入控制状态（关节目标、速度目标、轮目标、
  轮模式、终止信息）；`env-state/v1` 旧快照仍可恢复，缺字段显式按空值处理。
- 自检：`scripts/v3_selftest_command.py`（A6 短核查，宿主可跑；站姿误差、子步计数、
  轮三模式、终止、save/restore 一致性）。

## 本轮已完成（工作包 B）

- B2 阶段机：`scripts/v3_basic_cycle.py`，STAND → SHIFT_SUPPORT → 抬轮 → HOLD →
  LOWER_UNTIL_CONTACT → LOAD_TRANSFER → RETURN_BODY，每阶段有进入条件、最大时间与失败原因。
- B1 测量：整机重心用 `subtree_com(base_link)`；支撑点来自真实轮-地接触点；
  支撑多边形与 10 mm 裕度；逐轮法向载荷；轮底对地间隙；roll/pitch、速度、跟踪误差。
- B3 支撑转移：逐腿 3 关节雅可比 + 阻尼最小二乘，支撑轮基本不动、机身/重心横移；
  没有给三个支撑髋同一个经验偏置。
- B5 阈值全部写进结果并由 `ok` 强制：HOLD 1.2 s、倾角 ≤5°、速度 ≤0.03 m/s、
  角速度 ≤0.1 rad/s、摆动轮 <2% 重力、三支撑各 ≥5%、裕度 ≥10 mm、
  跟踪 ≤0.15 rad、落轮持续承载 ≥0.2 s 后才回位。
- B6 实跑（沙箱）：FR 在 rigid 与 nominal 各 3 个连续周期；FL/RR/RL 在 nominal 各 3 个周期。
  全部阶段通过，无终止。
- 数字（nominal，逐周期）：HOLD 倾角 1.36–1.52°、裕度 11.6–16.7 mm、
  抬轮 24.9–25.2 mm、跟踪 0.014–0.016 rad；rigid 同类。
- 运行目录：`runs/v3/basic_cycle/{rigid_r1, nominal_r1, nominal_FL_r1,
  nominal_RR_r1, nominal_RL_r1}`，每个含 result.json、frames.npz、record/、
  run_manifest.json、effective_config.json、status.json。
- **B 的限制（未过 G3 的部分）**：目前只用 `reset(seed=0)` 一个初态；
  SPEC B6 要求的“三个真实不同轻微初态 + 实际 qpos/qvel 哈希”尚未做。
- 过程说明：B 实现阶段做了多轮代码修正（目标裁剪、持续接触阈值），
  属于实现修正而非参数扫描；下一轮起按 B6 在每次试验前写“假设—只改什么—看哪个信号”。

## 尚未完成

- 工作包 C：预演保真五条件对照；`v3_isolation5.py` 的 `env_before` 仍在 restore 之前采样。
- 工作包 D：D1 两条前腿搭台已通过（修正分母后重新确认）；`--rear` 目前停在 `RR_shift`
  （支撑裕度不足），后轮搭台/下台未完成；D2 完整轮式库对照（5 cm 台低于轮半径）与 D4 未做。
- 工作包 E/F：主角三案例、约 20 m 连续路线。
- v3 旧记录的 `runs/v3/report/revalidation.json` 生成于 14:59，早于最终 14 状态批次
  （run_id 15:09–15:17）；不得再用它给 14 个状态标 `revalidated`。要重标须重跑并生成新记录。
- `dist/v3_bundle` 仍是 12:29 旧批次，页面数字与当前源表不一致；按新口径重建前不得对外引用。

## 下一条可执行命令

```bash
# A6 命令合同（宿主可跑）
.venv/bin/python scripts/v3_selftest_command.py
# B 基础周期（沙箱；已有结果见 runs/v3/basic_cycle/）
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_basic_cycle.py \
    --soil nominal --swing FR --cycles 3 --record --out runs/v3/basic_cycle/nominal_r1
```

沙箱重任务必须用独立 `run_id`、独立输出目录、PID/日志/退出码落盘，
不覆盖已有 `result.json`；重任务并发上限 2（V0 / V1 各一）。

## 本轮已完成（工作包 C 的首轮五条件对照）

- C1 修正：`runner.run_from_state(..., pre_step_hook=...)` 在 `restore_state` 完成、
  第一条控制命令之前采样；`env_before` 不再采在恢复前。旧 `env-state/v1` 与新 `v2`
  快照都可续行。
- C2 记录：真值臂编译后共 54 个 geom、其中 34 个 mesh geom（机器人 33 + 真值物体 1），
  即**物理真值是一块 mesh geom，MuJoCo 按凸包参与接触**；凹扫描件不等于凹网格接触。
  细盒 1400 geom、粗盒 393 geom、T-as-parent 2846 geom。
- C3 五条件（state `moon_rock_04_h1v0`，动作 L2，每臂重复 2 次）：
  A 真值 mesh / same_scene；B 真值 mesh / project；C 真值源占据细盒；
  D 同一源占据 12.17 mm 粗盒；E 生产 T-as-parent 细盒。
  五臂全部 `physical_failure`；A/B 首次分叉在第 **72** 步，B 与 C/D/E 在第 **92** 步。
- C1 对照：A/B 恢复后 qpos/qvel/ctrl/xfrc/土壤/双时钟/计数哈希**全部相同**；
  仅 `qacc_warmstart` 与 `geom_friction` 不同（project 不搬材质，符合设计）。
- 重复性：五臂各重复 2 次，outcome 与 final_x 完全一致（deterministic=True）。
- 结论范围：本轮只支持“72 步分叉与恢复模式相关、92 步分叉与碰撞表示相关”，
  还不能声称“72 步只由 warmstart 引起”或“92 步全部来自盒碰撞”；需要 warmstart
  受控开关与接触事件对照。
- 产物：`runs/v3/isolation5_r3/`（result.json、qpos_*.npy、粗盒 manifest）。

## 本轮完成（C4 受控 warmstart + C5 三状态回归）

- C4 四臂（同真值，只切 warmstart；各重复 2 次）：
  `A_ws_keep` / `A_ws_zero` / `B_ws_keep` / `B_ws_zero`。
  - A keep vs A zero：第 **71** 步分叉；A keep vs B keep：第 **72** 步；
    A zero vs B zero：第 **185** 步。
  - B 的 project 恢复把 `qacc_warmstart` 清零（norm 0）；A 保留（norm 0.0231）。
  - **结论**：此前 72 步分叉由 warmstart 解释；清零后残余的 185 步分叉来自
    4 个轮 geom 的 sliding friction 差（最大 5.57e-4；project 不搬材质）。
    这修正了“72 步只由 warmstart、其余全由盒碰撞”的粗糙说法。
- C5 三状态回归（`moon_rock_01_h0v0`、`moon_rock_04_h1v0`、`moon_rock_05_h1v1`），
  五臂 × 2 次：
  - 01 五臂全 `pass`；04 五臂全 `physical_failure`；05 五臂全 `physical_failure`；
  - 同状态内五臂结局同类，未出现“某表示预测安全、真值执行失败”的未解释情况；
  - 重复性全部 deterministic；01 的 A/B 仍在 72 步分叉、B 与盒臂在 95–96 步分叉；
  - 05 的 A/B 无分叉（该快照 warmstart 与摩擦本就一致），盒臂在 100–101 步分叉。
- 产物：`runs/v3/isolation5_c4_r1/`、`runs/v3/isolation5_r3_01h0v0/`、
  `runs/v3/isolation5_r3_05h1v1/`（result.json + qpos_*.npy）。

## 本轮完成（D1 第一里程碑：FR 前轮搭台）

- 场景：平地 + 5 cm 高、0.5 × 0.27 m 窄台，横向偏置只盖住 FR 轮迹
  （开发用已知几何；正式执行不得读台沿真值参数）。
- 阶段：APPROACH → 速度斜坡 BRAKE → SHIFT_SUPPORT（16.1 mm）→ LIFT_FR
  （轮心 0.1626 m，高于台面 + 轮半径 25 mm）→ ADVANCE_TO_LEDGE（FR 轮心 x=1.02）
  → LOWER_FR（持续载荷触发）→ HOLD_FRONT。
- 结果：rigid、nominal 各通过，nominal 两次重复；7/7 阶段检查通过；
  HOLD 时 FR 载荷 4.29 N（13.8% 重力），倾角 1.29°，无终止。
- **限制**：只完成一个前轮的搭台；还没有抬 FL、身体前移、后轮跟上、后坡下降。
  不是完整 CLIMB，不能据此宣称腿式价值；单初态、开发几何。
- 过程中修掉的实现问题：速度目标被 coast 模式吃掉；硬刹车导致后轮卸载；
  载荷统计只算地面、漏掉障碍物接触；两前轮 x 相同，台沿必须窄且偏置。

## 本轮完成（D1 第二里程碑：两条前腿依次搭台）

- 场景：两块错开的窄台（FR 台沿 x=0.95，FL 台沿 x=1.13，高 5 cm），
  先抬的 FR 不会被 FL 的台面挡住。
- 逐腿：SHIFT → LIFT（轮心高于台面 + 轮半径 + 25 mm）→ ADVANCE → LOWER
  （持续载荷触发）→ 0.6 s 稳定 → HOLD；支撑多边形包含障碍物接触点。
- 结果：rigid + nominal ×2 全部 **13/13** 检查通过；
  HOLD_BOTH：FR 21.2–22.2% W，FL 5.1–5.6% W，倾角 1.08–1.22°，无终止。
- **限制**：FL 刚过 5%，左右载荷不对称；身体前移、后轮跟上、后坡下降仍未做；
  单初态、开发几何。不是完整 CLIMB，不能据此宣称腿式价值。
- 过程中修掉：宽台先抬 FR 会被 FL 撞住 → 改为两前轮各一块错开的窄台；
  支撑多边形只算地面 → 加入障碍物接触点；落轮后立即判载 → 加 0.6 s 稳定窗口。

## D1-3 尝试（`--rear` 实验路径，未通过）

- 目的：两条前轮上台后，身体前移、后轮 RR/RL 依次搭台、四轮承载。
- 结果（rigid，单次）：RR 搭台通过（hold 4.04 N，5.4% W，倾角 1.8°）；
  RL 在 shift 阶段支撑裕度只有 3.7 mm，lift 时倾角 15.3° 触发终止；
  长台面下 FL 载荷 3.6–3.8% W，低于 5%。
- 结论：**不能直接抬最后一条腿**；需要先做前轴预压/CoM 前移（或分段台面），
  让三条支撑腿的裕度和载荷先稳定，再抬 RL。
- 默认路径（不带 `--rear`）仍是里程碑 2 的短台面两前轮流程，已复跑通过 13/13。

## D1-3 第二轮（前轴侧向预压，`--rear`，仍未通过）

- 改动：两条前轮上台后，先做**侧向预压**（机身 +y 平移 10 mm），再身体前移、后轮搭台。
- 结果（rigid，沙箱）：`preload_front` 通过、`hold_both` 通过（FL 载荷升到 ≥5%）、
  `advance_body` 通过、RR 搭台通过；RL 的 shift 仍失败，RL lift 倾角 15.08° 终止。
- 判断：**不要再调这一个结构**。最后一条腿抬起时，三条支撑腿都在 5 cm 台上、
  支撑多边形太窄；方向应改为改变场景/顺序（后轮用 2.5 cm 二级台阶或后坡坡道），
  而不是继续加增益。
- 产物：`runs/v3/climb/rear_attempt_r2/`（status=partial）。

## D1 审阅修正（质量分母 / 阶段前置 / 台面 vs 侧壁）

- **质量分母**：`bc.robot_mass()` 改为 `base_link` 子树质量；`total_weight()` 不再把静态台块算进去。
  机器人 19.1264 kg / 30.985 N；两块短台曾把分母抬到约 52.9 N，长台约 74.7 N。
  平地 B 包不受影响（场景无静态物体）。旧 `front2_*` / `rear_attempt_*` 的 `frac`
  用错了分母，**已作废**；引用 `front3_*` / `rear_gated_r1`。
  修正后：front3 的 FR 36–38% W、FL **8.8–9.7% W**（不是 5.6%），倾角 1.08–1.22°。
- **阶段前置**：每个阶段必须上一阶段 `ok`；失败立即停止并写 `blocked_at`。
  `rear_gated_r1` 停在 `RR_shift`（裕度不足），**不再进入 RL_lift**，无倾覆。
- **台面 vs 侧壁**：`contact_load(kind='top'|'wall'|'any')` 按接触法向区分（|n_z|≥0.7 记 top）；
  只有 top 计入承载与支撑多边形，侧壁碰撞单独记录，不再可能把"顶住侧壁"算成"搭上顶面"。
- 尚未解决：前轮在台上时 `RR_shift` 的支撑裕度 <12 mm。需要针对该构型重新设计后轮支撑转移；
  5 cm 台低于 8.6 cm 轮半径，必须跑完整轮式库对照，不能预设轮式过不去。

## D2 先行检查：5 cm 台纯轮式可通过（关键负结果）

- 纯轮驱动、无腿动作、同一两块 5 cm 错开窄台：
  - **0.30 m/s → final x = 1.5516**，越过两块台，倾角 11.4°，无终止；
  - 0.10 m/s → 0.754，未过。
- 结论：5 cm 台低于 **8.6 cm 轮半径**，轮式可以过；**当前开发场景不能证明腿式价值**。
  D3 必须把障碍抬到轮半径以上（例如 0.12 m）或换真实岩石，再做完整轮式库对照。
- D1 现状：两前轮搭台仍成立（front3 13/13）；后轮 `RR_shift` 在“前轮已在台上”
  构型下失败（FR 顶面接触丢失，支撑点只剩 FL+RL），已按阶段前置停止，不再硬抬。
  窄台 + 侧向预压这个结构先不再调参；下一步换更宽/分级的台面或抬高障碍。
- 另外修掉一个真实缺陷：MuJoCo `contact.frame` 行主序、法向在第一行
  （实测 `[0,0,1, 0,1,0, -1,0,0]`）；此前按列取法向，把台面接触误判成侧壁。

## D 场景标定：平地台阶的轮/腿能力窗口（重要负结果）

- 轮式基线（纯轮速、无腿动作）：
  - 5 cm：0.30 m/s 通过，0.10 m/s 失败；
  - **12 cm：0.30 / 0.50 m/s 通过**（倾角 20–21°）；
  - 18 cm / 24 cm：0.30 / 0.50 均以倾角 60° 翻倒失败。
- 腿式前轮搭台：
  - **12 cm 通过**（FR 轮心 0.2324、FL 0.2295；hold 28.9% / 18.2% W；倾角 0.37°）；
  - 18 cm 在 `FR_lift` 停住（轮心只到 0.2392，目标 0.291）；腿的抬升上限约 0.239 m。
- 结论：平地垂直台阶**没有**“轮式过不去、腿式够得着”的窗口——轮式到 ~12 cm 仍能
  动态爬过，腿式可达 ~13 cm；18 cm 轮式翻、腿式也够不着。**D 的主角场景必须换类型**：
  真实岩石的窄高落脚点/带唇口的台沿，或软土（D4），而不是平地高台阶。
- 12 cm 前轮流程仍是有效的控制能力证据；后轮支撑转移问题未解决。

# 当前状态（唯一入口）

> 唯一源表：`runs/v3/report/v3_results.json`　SHA256 `091b4104216279974b424d2ec81270817048bc6e4db4fdcdcd4f6d3f93fe3130`　生成时点 `2026-11-03T15:19:20+0800`
> 三份文档（CURRENT_STATUS / V3_FINAL_REPORT / V3_RESULTS_TABLE）都由该表生成；数字口径见表中 `definitions`。

## 一、当前结论（口径见源表）

| 项 | 值 |
| --- | --- |
| 状态目录 | 48 |
| 已筛选 | 48 |
| 完整真值可通行 | 44 |
| 隐藏敏感 | 23 |
| 入选（计划分母） | 22 |
| 分层 | {"action_only": 18, "none": 25, "action_and_outcome": 5} |

| 计划状态分类 | 数量 |
| --- | --- |
| executed_pair | 14 |
| one_arm_only | 0 |
| not_run | 8 |
| pipeline_failure | 0 |
| invalid_identity | 0 |

### 逐方法结局与误判

| 指标 | FULL | OBS_ONLY |
| --- | --- | --- |
| pass | 12 | 12 |
| safe_stop | 1 | 1 |
| physical_failure | 1 | 1 |
| 风险低估 | 1 | 1 |
| 过度保守 | 1 | 1 |
| 参考未评估 | 0 | 0 |
| 有效执行 | 14 | 14 |

- 有效配对：**14** 个（定义：两臂 decision+execution 齐全、action 与 decision 一致、state_mode=same_scene、同一 state_hash、轨迹可读且首尾时间可核）。
- 结局更好：FULL 0 / OBS_ONLY 0 / 相同 14。
- 这只陈述**当前已测配对计数**，不能据此推出“总体没有变差”或“方法有效”。

| 状态 | FULL | OBS_ONLY | 更好 | FULL 动作 | OBS 动作 |
| --- | --- | --- | --- | --- | --- |
| moon_rock_01_h0v0 | pass | pass | same | R1 | R1 |
| moon_rock_01_h0v1 | pass | pass | same | D1 | D1 |
| moon_rock_01_h2v0 | safe_stop | safe_stop | same | A0 | A0 |
| moon_rock_02_h0v1 | pass | pass | same | R1 | R1 |
| moon_rock_02_h2v0 | pass | pass | same | L2 | R1 |
| moon_rock_02_h2v1 | pass | pass | same | L2 | L2 |
| moon_rock_03_h1v0 | pass | pass | same | R1 | R1 |
| moon_rock_03_h2v1 | pass | pass | same | R1 | R1 |
| moon_rock_04_h0v1 | pass | pass | same | L2 | L2 |
| moon_rock_04_h1v0 | pass | pass | same | R2 | R2 |
| moon_rock_05_h1v0 | pass | pass | same | D1 | D1 |
| moon_rock_05_h1v1 | physical_failure | physical_failure | same | S1 | S1 |
| moon_rock_05_h2v0 | pass | pass | same | R1 | R1 |
| moon_rock_05_h2v1 | pass | pass | same | R2 | R2 |

### 隐藏区误差覆盖

- 覆盖：**1 个状态 / 6 个候选-状态行**；只覆盖有 metrics/summary.json 的状态与候选；未度量状态不在分母里，也不外推。
- 隐藏占据 IoU：n=6，均值 0.011，中位 0.011，范围 [0.009, 0.013]
- 漏填率：n=6，均值 0.989，中位 0.989，范围 [0.987, 0.991]
- 过填率：n=6，均值 0.552，中位 0.562，范围 [0.436, 0.617]
- 沿路径顶面 MAE (mm)：n=6，均值 36.301，中位 35.732，范围 [33.044, 40.073]
- 沿路径顶面 P95 (mm)：n=6，均值 217.000，中位 215.800，范围 [198.600, 236.600]
- 后缘位置误差绝对值 (mm)：n=6，均值 48.000，中位 46.000，范围 [46.000, 56.000]
- 后坡落差误差绝对值 (mm)：n=6，均值 3.333，中位 4.000，范围 [2.000, 4.000]

### 已知答案

- 有实测记录的状态：**2**；无记录状态：**46**（无记录 ≠ 已运行通过）。
- moon_rock_01_h0v0: 尺度误差 0.308%、旋转 2.107°、表面 P95 6.270 mm、pass=True
- moon_rock_02_h0v1: 尺度误差 0.865%、旋转 0.865°、表面 P95 4.508 mm、pass=True

## 二、本批已落实的合同

1. 共同观测 V：栅格只由公共观测决定，V 一次落盘并哈希绑定；`FULL = V ∪ (P∩U)`、`OBS_ONLY = V`（同一数组）；消融后不做清理/补洞；自由区不被占据。
2. 配准：24 朝向粗搜索 + 投影式多尺度鲁棒 ICP + 局部坐标下降；已知答案两个形状通过（见上）。
3. 决策：候选级矩阵 → 多数票（≥⌊n/2⌋+1）→ 预登记代价最低；相同几何只算一票、任务分母保留。
4. 执行：两臂各自 `restore_state(S0, mode=same_scene)` 后独立执行；未完成不缩分母，分类见上表。

## 三、未完成与下一步

- 有效配对只覆盖部分计划状态；其余按 one_arm_only/not_run/pipeline_failure/invalid_identity 分类保留在分母里。
- 隐藏误差只覆盖有 metrics 的状态与候选，不外推。
- 下一步（按 SPEC 优先级）：P0-A 数据发布（凭据受限，先备包）→ §5 全轨迹记录 → V0 逐层追踪与缓存修复 → V1 逐腿三关节控制与 CLIMB/第二技能/软土脱困 → V2 三项成本 → V3 背面敏感 → V4 六候选三支 → V5 20m 连续路线 → A–G/H 生产。

## 四、产物位置

| 产物 | 路径 |
| --- | --- |
| 结果源表 | `runs/v3/report/v3_results.json` |
| 结果 CSV | `runs/v3/report/v3_table.csv` |
| 协议 | `plans/v3_protocol.json` |
| 入口 | `scripts/run_v3.py` |
| 素材包 | `dist/v3_bundle/`（仅旧批次，待按新口径重建） |

# 归档：v2 及更早
v2 的主表与“修复前 H5_F 不检验本方法”的定级保留在 `docs/V2_*.md` 与 `runs/unseen/...`，不参与 v3 分母；其工程结论（融合入口缺陷、组件清理会删壳层、freespace 超限来自体素化）已并入 v3 实现合同。
