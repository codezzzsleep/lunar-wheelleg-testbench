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

## 完整通行判据 + CLIMB 后轮进展

- 轮式探针改为**完整通行**判据：四轮都越过障碍最远后缘 + 完成下降 + 稳定保持
  （四轮落地、倾角 ≤10°、无终止）。宽平台（宽 0.9 m，face 0.95，far 2.35）：
  - **5 cm：通过**（四轮 grounded，tilt 0.31°，无终止）；
  - **12 cm：翻倒**（60.4°，前缘就过不去）。
  - 注意：此前“12 cm 通过”用的是两块错开窄台，不是宽平台，两者不能混用。
- CLIMB 开发场景：改为加宽、错开、同后缘（2.35 m）的台面；去掉侧向预压与整体前移，
  后轮像前轮一样“抬起 → 前进 → 落下”。
  - 现在 **FR/FL/RR 三条腿都搭台成功**（RR hold 5.0 N，16.2% W，tilt 1.8°）；
  - 停在 `RL_shift`：CoM (1.19, 0.10) 在支撑三角形外 13.6 mm；第一次 shift 后
    有支撑轮丢接触，margin 反而到 −168 mm。按规则**不再调这个结构的增益**。
  - 下一步：换更容易稳定支撑的开发场景（更低台/更宽台），或显式把 CoM 前移，
    再完成 RL 搭台与下降；完整攀越优先于场景筛选。

## 完整攀越：最后一条腿（RL）仍是瓶颈

- 试了更容易支撑的场景：台高从 5 cm 降到 3 cm，加宽台面（0.45 m）、同后缘 2.35 m；
  后轮像前轮一样“抬起-前进-落下”。
- 结果：FR/FL/RR 三条腿全部搭台成功；`RL_shift` 仍失败。3 cm 下 RL 的初始 margin
  在不同 run 间为 **+10.2 mm 到 −9.6 mm**，对最后一次 RR 落腿的细节很敏感；
  原来的大步 shift 会丢支撑轮（margin 到 −168 mm），改成“小步、只一轮”后不再恶化，
  但仍无法稳定到 12 mm。
- 判断：**这是最后一条腿的支撑构型极限**，不是增益问题。继续在这个双窄台上调参
  不会得到稳定完整攀越。
- 下一步：把开发场景改成**分级台面**（后腿有自己的低一级台阶，CoM 更容易落在
  支撑三角形内），或先做一次显式的机身 CoM 前移再抬 RL；完成后再谈场景筛选。

## 四轮横向 CoM 居中（arena 试验）

- 新增 `center_lateral`：四轮都在支撑面上时，用四条腿的雅可比把小步 −y 平移，
  让 CoM 向右回中；小步（−3 mm × 2 轮）可以通过，且不丢四轮接触。
- 效果：`center_lateral` 通过、RR 仍能搭台；**RL_shift 仍失败**。
- 结构性原因：抬左后轮 RL 时，支撑三角形 FR/FL/RR 缺的正是左后角，而 CoM 偏左后；
  向右移会先卸载 FL（左侧支撑），向左移只会更出去。双窄台 + 准静态逐腿抬升
  在这个构型下无解，不是参数问题。
- 下一步（按优先级）：
  1. **分级台面**：后轮用更低的一级（例如 2 cm），改变抬升时的 CoM/姿态；
  2. 或对最后一条腿改用**动态抬腿**（L2 式，边走边抬），不再要求准静态三点支撑；
  3. 或开发场景改成后部带坡道，先拿到一次完整攀越（允许轮式也能过）。

## 后轮助爬与四轮保持（仍未完成）

- 尝试：`center_lateral` / `center_forward` 把 CoM 向右/向前回中；RR 仍能搭台。
  RL 最后一条腿改**轮式助爬**（0.12 m/s，5 cm < 轮半径）：RL 成功爬上（x 1.2013，
  载荷 13.97 N）。
- 但 `hold_all` 失败：FR 48.8%、FL 13.9%、RL 37.2%、**RR 0%**；机身靠 FR/FL/RL
  三点支撑，RR 悬空；把 RR 下压 3 cm 仍是 0（可能悬空更多，或接触落在侧壁）。
- 结论：**四轮同时上台后的“四轮保持”未通过**，完整攀越仍差最后一步。
- 下一步：RR 落地改为闭环（按轮心高度/接触法向逐步下压，直到顶面载荷达标），
  或后部加坡道让 RR 滚上；先拿到一次四轮保持，再做下降。

## 动作闭环改造（按审阅：先测后判，不再用移动中的裕度）

- `shift()` 改为：移动 → 稳定窗口（0.3 s）重测 → **用最终状态判定**；结果里保存
  `before` / `after` 的 CoM、支撑点、各轮载荷与裕度。
- 效果：FR/FL/RR 的 shift 都有可审计的前后数据；RR_shift 从 **−2.4 mm** 改善到
  **+16.5 mm**，四轮载荷也更均衡（8.4 / 9.1 / 6.6 / 6.9 N）。
- 后轮改为轮腿协同：RR 仍准静态搭台；RL 用 `push_last_wheel`（保持接触滚上台，
  其他轮掉载时每 5 步闭环补 4 mm 下压）。
- 目前停在 `RR_hold`：RR lower 在 3 步内触发 5.04 N，但 0.6 s 稳定窗口里又掉到 0；
  还没走到 RL push。下一步把 RR 落地改成**持续载荷闭环**（顶面 ≥5% W 维持 0.2 s
  才停，掉载继续小幅下压），再跑 RL push / hold_all / descend。

### 口径更正

此前把 `RL_shift` 写成“结构性无解”**不准确**；应记为**当前支撑转移策略未完成**。
`shift()` 已改为移动后稳定窗口重测、按最终状态判定（见上一节），后续不再用
“结构无解”下结论，除非两条实现路径都按有限尝试规则失败。

## 回退技能 SIDE_LEVEL 已实现（待独立评估）

- `side_level`：闭环按 roll 调整左右腿长（每 5 步一次，小步 4 mm），把机身滚转拉平，
  让悬空轮落地；设计上用于“四轮上台后 RR 悬空”的收尾，也符合 SPEC D4 的
  SIDE_LEVEL 第二技能。
- 当前 `--rear` 仍保留单腿 hold 安全门，停在 `RR_hold`，所以还没有干净的
  SIDE_LEVEL 评估；强制绕过安全门时 `RL_push` 会倾到 15.03°，不采纳。
- CLIMB 仍按 D5 标未过；下一步做 BODY_CLEARANCE / SIDE_LEVEL 的独立评估，
  以及真实岩石上的完整轮式库（同一完整通行判据）。

## F 连续路线（20 m）第一版

- 为 20 m 路线把地形 span 与场地 x 上限做成可配置（`terrain.make_spec(span=...)`、
  `spec['terrain']['field_x_max']`），默认仍是 4 m，不影响旧场景。
- 路线：24 m 平地 + 3 个 5 cm 台阶（x=4/10/16，0.9 m 宽），纯轮式 0.30 m/s 连续行驶。
- 结果（rigid）：跑到 **x=12.77 m**（已过前两个台阶），随后 **tipped**（tilt 60.5°），
  用时 53.2 s；**未完成 20 m**。
- 结论：连续路线目前只过 2/3 台阶；需要更稳的通过策略（降速/抬头/姿态控制）或
  更缓的台阶，不能把 12.77 m 说成 20 m 通过。

## F 连续路线（20 m）已通过（rigid + nominal）

- 关键修正：原先 hfield 的 span=12.5，机器人在 x≈12.5 驶出地形边缘后翻倒；
  不是台阶问题。改为 **span=25、field_x_max=26** 后，同一条路线直接跑通。
- rigid：x=**23.5482 m**，100.26 s，tilt 8.91°，无终止；
- nominal：x=**23.5375 m**，106.6 s，tilt 8.29°，无终止；
- 三个 5 cm 台阶全部通过，纯轮式慢压，终点稳定 1 s。
