# 会话交接（SPEC_UNSEEN_RECOVERY_002）

> 本块由人工维护；`scripts/v3_docs.py` 生成 `CURRENT_STATUS.md` 时置顶拼接。
> 它是交接说明，不是第二份状态文档；数字口径仍以 v3 唯一源表为准。
> 最近更新：2026-11-03 19:45 +0800。


## STAGE003（2026-11-03 晚，窄目标批次）

- 场景：两块 5 cm 错开台（face 0.95/1.13，far 2.35，宽 0.45），nominal；rigid 仅定位。
- S1：末段 RR 诊断——快照里 RR 是台缘接触（轮底高于台面 10.7 mm、6.2 N），
  停驱动后 RR/FL 同时掉零，机身落在 FR+RL 对角；不是几何不可达。
- S2：结构 A 成功序列——FL 实测方向下放 → level_roll → body_down（同时下放最低载轮）
  → preload_min → 1 s 稳定窗口 → descent；rigid 与 nominal 均 **24/24**。
- S4：三个冻结初态 **3/3**（qpos dfea15f0 / 264be46e / 7e321110；qvel 相同，已注明）。
- S5：轮式 R1 0.30 / R2 0.15 各 3 初态 **6/6 通过**（14.6–28.3 s，tilt ≤0.06°）；
  腿式 56.8–58.7 s、tilt 3.5–4.35°。**本场景轮式也过且更便宜，不宣称腿式增量价值。**
- 回放：`runs/v3/stage003/replay/{leg_state1,wheel_state1_r1,side_by_side_state1}.mp4`
  （1757 帧/58.6 s；300 帧/10 s；并排 1920×1080）。
- 离线包：`dist/stage003_bundle.tar.gz`（7.8 MB，sha256 3347bf9b…）；新目录解包
  MANIFEST 273/273 通过，`./run_replay.sh wheel` exit 0。
- **记录修复（追加）**：记录器采样入队改深拷贝；重采 `fix_leg_state1|2|3`、`fix_s5_wheel2`；
  旧记录标 `RECORD_DEFECT`；回放与离线包按修复后记录重建（sha256 355f3627…）。
- 记录：50 Hz qpos/qvel/关节目标/力矩/接触（contacts jsonl）；相位只有 result.json
  边界、轮模式只有 brake 标志——缺口已在 `runs/v3/stage003/record_check.json` 标注。
- 不声称：20 m 路线、软土脱困、Lux3D 增量价值。


## STAGE004（2026-11-04 凌晨，有限修正后收口）

- CLIMB 参数化接口：完成（开发 24/24、4 cm 24/24、far_x 未知安全停下）；但**新 CLIMB
  尚未接入 FULL/OBS 对照**（它不在动作库里，投票无法预演它）。
- 真实扫描适配边界：8 个 `moon_rock_*` 顶带 y 宽 0.05–0.15 m、30 个 posed 最宽 0.26 m，
  双前轮构型不成立；这是**技能适配边界**，不能概括为“真实岩石不能用腿”。
- 冻结动作集为 R1/R2/D1/D2/L1/L2（无 S1）；旧 05 的 S1 失败来自非冻结动作，已作废重算。
- 修正后的三配置（truth / OBS / FULL，同一 V、动作集、状态、土壤、预算）：
  - 04_h1v0：R2 pass / R2 pass / R2 pass；
  - 01_h2v0：L2 pass 8.36 s / A0 safe_stop / A0 safe_stop（FULL 仍用不上背面）；
  - 05_h1v1：D1 pass 7.54 s / L1 pass 7.92 s / L1 pass 7.92 s。
  FULL vs OBS 仍 0/3 决策差异。
- 初态扰动已改为“环境恢复→读真实 qpos→施加 dx/dy/yaw→save_state”；两个扰动初态重采，
  state_hash 与实际执行快照一致；零扰动结果保留。
- 筛选口径差异：旧 screen 的 obs-only V sha `445074e0…`，当前共享 V sha `0bd97be1…`；
  旧 OBS 决策 04 L2/05 L2 翻车，新 OBS 为 04 R2/05 L1 通过——旧口径夸大了背面敏感性。
## STAGE004 追加：CLIMB 正式接入与 G2 边界（2026-11-04 凌晨）

- G1（commit 91cac0f74）：`run_climb_episode` 把 Stage003 状态机接进正式矩阵；开发场景
  CLIMB 预演 57.4 s 全过、进入投票；轮式更便宜（D1 7.32 s）按规则被选中并执行 pass。
- 协议：`configs/stage4_protocol.json`（动作含 CLIMB、120 s、多数为主/最坏附加），
  动作集由配置读取，脚本不再复制常量；`aggregate` 支持显式 options。
- G2：三个冻结真实配置 × 三臂（truth / 共享 V / 候选 FULL）全部**不满足 CLIMB 适用性**：
  04 顶带 0.26 m、01 0.064 m、05 0.054 m（需 ≥0.40），顶高 0.17–0.21（上限 0.15），
  且顶面不平；V 的后缘保持未知。
- 背面确实改变了**参数**：OBS 的 far_x=None、descent=None；truth/FULL 的 far_x 已知
  （04 truth 1.540 vs FULL 1.498；05 truth 1.451 vs FULL 1.459）、plan_id 不同；
  但三配置全部被适用性拒绝，**没有改变动作或结局**（G3 无合格配置，不执行）。
- 这是“当前双前轮搭顶构型不适配现有扫描件”的适配边界，不是“真实岩石不能用腿”。

## STAGE004 最终追加：G1 双验证 + 决策先行确认（2026-11-04 凌晨）

- G1a：开发场景正式矩阵（120 s），CLIMB 预演 57.4 s 全过、进入投票；轮式更便宜 → D1
  7.32 s 被选中并执行 pass。G1b：动作集只留 CLIMB/A0 时，CLIMB 被正式选中并执行 57.4 s pass。
- 决策先行确认（三个主配置，decision 先写、绑 matrix SHA + 实际快照哈希 + 动作集，再执行）：
  - 04：R2 / R2，均 pass 9.42 s；
  - 01：A0 / A0，均 safe_stop 3.60 s；
  - 05：L1 / L1，均 pass 7.92 s（旧 S1 失败为冻结集外动作，已作废）。
- 三个主配置 FULL vs OBS **0/3 决策差异**；04 第三个初态（−2 cm/−1°/OBS L2）存在决策差异，
  但两臂都 pass 且 FULL 更慢（9.46 vs 7.12 s），**不构成收益**。
- CLIMB 计划参数固定规则写入协议：FULL 用一个规范融合占据（A1）出参数，所有候选复用同一
  参数；OBS 用共享 V；truth 仅参考。

## STAGE005 边界：组合岩石未形成可用承载面（2026-11-04 凌晨）

- 共用入口已真实支持 CLIMB：候选碰撞 + project 恢复、真值 same_scene，行内带
  `plan_id`/`geometry_id`；same_scene 与 project 的 45 s 分歧定位为 warmstart 状态，
  统一清零后两者同为 63.32 s 通过。
- 组合岩石（CC0 Poly Haven 扫描件，2/3/5 块）用 4 mm 占据 + 4 mm box-union 碰撞：
  - V0 两块：覆盖 0.312 m、缺口 0.144 m、顶长 0.144 m，CLIMB physical_failure；
  - V1 三块：覆盖 0.244 m、缺口 0.048 m，CLIMB abort；
  - 主配置五块：覆盖 0.456 m **达标**，但缺口 0.092 m、轮位坡度超限，CLIMB physical_failure；
  - 主配置收紧间距 0.06 m：覆盖 0.356 m、缺口 0.044 m、FR 平整面积 0.166，仍不合格。
- 适用性门（覆盖率 ≥0.40、缺口 ≤0.01、轮位平整面积 ≥0.6、坡度 ≤0.15、顶长 ≥0.20、
  top_z 0.02–0.15）三项全不通过；**缺口不算承载面**，未用总宽度冒充适用。
- 结论：现有 boulder 扫描件的顶面是窄穹顶，单靠缩放/并排无法构成连续、可承载的
  0.4 m 平台；这是**组合构型/资产适配边界**，不是“真实岩石不能用腿”，也不转入单轮技能。
- 未做：真实高分辨率图与 Lux3D 候选（无合格场景）；组合场景的 FULL/OBS 对照。

## STAGE006：BODY_CLEARANCE 可用，Lux3D 未评估（2026-11-04）

- 平地标定 2/4/6 cm 全部稳定：实际机身高 0.0198/0.0398/0.0595，底盘净空增益
  0.0197/0.0396/0.0594，倾角 ≤0.06°，四轮载荷 ≥7.4 N，关节余量 ≥0.41 rad。
- 岩石尺寸变体（冻结，moon_rock_05 窄轴朝机器人）：
  - 0.279 m：两臂都过、仅轮子擦碰，无机身接触 → 不构成能力对照；
  - 0.30 m：普通 R2 记录到 6 次机身-岩石接触；BODY_CLEARANCE 完整几何参考与 OBS
    两臂都是 **0 次机身接触、到达共同终点 2.6 m、稳定退出**；
  - 0.32 m：BODY 在 6 cm 抬升下仍被挡（59 次机身接触），超出当前抬升范围。
- 统一任务终点（2.6 m）后的同任务用时：R2 6.50 s（6 次机身接触）、D1 6.56 s（0）、
  BODY 完整几何参考 30.06 s（0）、BODY OBS 30.16 s（0）。此前 19.38 s 与 28.58 s
  是不同停止点，不能直接比较。
- FULL 更名为“完整几何参考（后缘来自真值）”；OBS 保持抬高到计划事件，不强迫提前降身。
- 逐控制步记录：抬升/保持/行驶/降身/恢复共用同一记录与安全检查入口，control.jsonl
  带连续步号、控制目标、阶段与接触；机身接触/倾角/终止检查覆盖所有阶段；失败阶段
  不会继续执行降身/行驶。
- 结论：BODY_CLEARANCE 真实可用且干净；**Lux3D 未评估**，项目总体收益 NOT_ESTABLISHED。
  未删任何可行动作，绕行 D1 仍然更便宜。

## STAGE007 作品整合：窄通道布局冻结（2026-11-04）

- 布局：moon_rock_05，高 0.30 m，位于 (1.0, 0)；两侧背景障碍墙 y=±0.55、
  0.50×0.50×0.32 m，内侧面 ±0.30 m；占据 grid sha `dc6c1de6…`，4 mm 占据 +
  4 mm box-union 碰撞；共同终点 2.6 m、预算 120 s。
- 参考几何矩阵（真值）：R1 失败、R2 机身接触、D1 翻倒、D2 失败、L1 翻倒、L2 机身接触；
  **只有 BODY_CLEARANCE 干净通过（30.06 s，0 次机身接触，reached/safe_pass）**，
  被多数规则选中并真值执行 pass。
- 结论：窄通道里硬质背景墙使绕行不可用，抬身成为唯一可行动作；场景具备能力对照意义。

## STAGE007 作品整合结果：Lux3D 候选未复现 BODY 干净通过（2026-11-04）

- 冻结窄通道（0.30 m 岩石 + 两侧墙，内侧面 ±0.30 m）下，参考几何只有 BODY_CLEARANCE
  干净通过（2.6 m 终点 30.06 s，0 次机身接触）；轮式因墙封死绕行而失败。
- 用该布局的带纹理目标图跑 6 个真实 G1-Turbo 候选，FULL（完整几何参考）/OBS（仅前缘
  0.10 m）两臂筛选：**6/6 候选的 BODY 都在 `drive_to_lower` 卡到 120 s、0 次机身接触**，
  即轮子被生成岩石挡住，而不是机身；参考岩石的干净通过没有迁移到生成候选。
- 4632618 让轮式 R2/D1 通过（绕行成立），说明该候选不构成窄通道；4632621 出现 FULL 失败、
  OBS 通过，但原因是 OBS 把未知后缘截成 0.10 m 前带、障碍变简单，不是规划更好。
- 按约定边界：BODY 干净通过未在生成候选上复现，控制研究到此结束；参考场景的结论保留，
  不开启新技能分支。
- 交付：`runs/v3/stage007/stage007_pack.tar.gz`（参考场景并排回放、带纹理场景/目标图、
  候选表、README）；时间分列：API 观测 2–5 min/任务（无逐任务时间戳）、预演 wall ~8 min、
  BODY 物理 120.022 s × 12 臂。
- 表述：项目总体收益仍 NOT_ESTABLISHED；FULL 一律写“完整几何参考（后缘来自真值）”。

## STAGE008 恢复与保全（2026-11-04）

- 新沙箱 `cnb-b5t-1k6hgejmv-001` 接管：scripts/configs/plans/docs、assets/v3、vendor（go2w）、
  stage005-007 运行数据齐全；Python 2.5.4 numpy / 3.17.0 mujoco / 5.2.0 trimesh / 1.18.1 scipy；
  参考 BODY 复跑 30.06 s / OBS 30.16 s，与旧记录逐项一致。
- 逐分块校验：50 个记录索引中 48 个通过（候选 6×2×4 动作全部数组/接触 SHA 匹配）；12/12
  碰撞 manifest 通过（parts 齐全、n_boxes 一致）。缺失的是旧 `stage6/fix` 两条参考轨迹的
  数组分块与接触文件（旧沙箱释放前未取回）——新复跑已生成新 run（`runs/v3/stage008/ref_repro`）
  并校验通过；旧索引保留 missing 标记。
- 原始资产归档：cnb 远端独立分支 `archive/stage008`（commit `fa66c604`），含 6 个原始 GLB、
  候选资产、参考轨迹与清单；main 分支不含大包。
- 定位更正：`stage7_candidates` 的结果只作“原始候选几何适配诊断”，它不是正式 FULL/OBS：
  未使用真实共享 V、OBS 只是生成模型前 10 cm 截断、没有独立真值执行。正式链见下一步。
## STAGE008 正式单案例（2026-11-04）

- 建立重建观测（固定 layout2、共同 S0、规划相机）：mask 115,858 px、可见前缘 x=0.834、
  W_vis 0.2746、H_vis 0.2990；共享 V 壳层 60,996 体素（2 mm 栅格）。
- 融合：参考真值 + 6 个 GLB（应用节点变换、统一朝向/0.30 m、复用 v3_fuse 列射线实心化），
  FULL = V∪(P∩U)、OBS_ONLY = V，合同断言全部通过（diff⊂U、自由区无占据、带一致）。
- 参考诊断（正对照）：FULL 与 OBS 两臂 BODY 均 pass（112.8 s / 114.22 s，0 次机身接触）；
  FULL 选 BODY，OBS 选 D2（7.46 s）。
- 六候选正式预演（先落决策）：FULL 臂 4/6 选 BODY（76.96 / 113.32 / 113.2 / 30.32 s），
  4632621 与 4632624 选 D2；OBS 臂 6/6 选 D2（预演场景内 7.46 s）。BODY 在 12/12 臂全 pass、
  0 次机身接触。
- 接线修正中：OBS 臂的真值执行必须用完整几何场景，而不是 OBS 自己的 V 场景；正在重跑
  `case_*_obs_truth`，完成后再给最终 FULL/OBS 决策与结局差异表。
- 早期 `stage7_candidates` 仅作几何适配诊断，不作正式比较。
## STAGE008 正式单案例结果（2026-11-04）

正式链：重建观测（固定 S0/相机，标 reconstructed）→ 共享 V（60,996 体素，sha ed44fbe6…）
→ 应用 GLB 节点变换并复用 v3_fuse：FULL=V∪(P∩U)、OBS_ONLY=V → 同一 S0/动作集/2.6 m 终点/
120 s → 决策先落盘 → **完整几何场景独立真值执行**。

| 案例 | FULL 决策/真值 | OBS 决策/真值 |
| --- | --- | --- |
| 参考（诊断父先验） | BODY pass 112.8 s | D2 physical_failure 5.9 s |
| 4632564 | BODY pass 76.96 s | D2 physical_failure 40 s |
| 4632603 | BODY pass 113.32 s | D2 physical_failure 5.84 s |
| 4632618 | BODY pass 113.2 s | D2 physical_failure 40 s |
| 4632621 | D2 pass 11.26 s | D2 pass 11.26 s |
| 4632624 | D2 pass 7.18 s | D2 pass 7.18 s |
| 4632627 | BODY pass 30.32 s | D2 physical_failure 40 s |

- 决策差异 **5/7**；FULL 真值执行 **0 失败**，OBS 真值执行 **5 失败**（其 D2 在完整几何上过不去）。
- BODY 在 12/12 正式预演臂中 pass、0 次机身接触；OBS 预演里 D2 都显示 7.46 s 通过，但在完整几何
  真值上失败——这是“完整几何改变决策”的真实证据，也是 OBS 只看到前缘的代价。
- 注意：参考诊断 BODY 112.8 s 与旧 layout2 30.06 s 不同，原因是正式链的 V 壳层 + 融合栅格使
  接触更“毛”，正对照仍通过；该差异已记录，不归因 Lux3D。
- 交付：可运行包 `stage008_runnable.tar.gz`（sha 见 pack_manifest，sim/replay 在新目录实测）、
  展示包 `stage008_demo.tar.gz`；均推送到 `archive/stage008`（commit b7b8140）。
## STAGE008 修正：单一真值场景 + 共同 S0（2026-11-04）

- 唯一真实执行场景：真实扫描岩石 + 两侧墙 + 地面 + nominal，4 mm 占据，冻结 SHA
  `0f8706f4…`；碰撞 `truth_coll`；共同 S0 `8c287b84…` 只在该场景采集一次。
- 重建观测在真实场景 S0 采集（mask 115,858 px），共享 V sha `ed44fbe6…`，只建一次。
- 六个 GLB 先应用节点变换，再走**已验观测配准入口**（silhouette+depth ICP，mask IoU
  0.49–0.56，可见中位误差 5.6–11.5 mm），随后 `FULL=V∪(P∩U)`、`OBS=V`。
- BODY 方案固定：可见前缘由观测给出，隐藏后缘来自**首候选**（1.065 m → lower_at 1.165 m，
  plan `005f113f5e67e4c9`），不使用真值后缘；OBS 方案保持抬高到 2.45 m（plan `4e74d6988d7f7d01`）。
- 六候选 FULL 矩阵多数聚合（阈值 3）：BODY 5/6、D2 2/6 → 选 **BODY_CLEARANCE**
  （decision_sha `45564c10…`）；OBS 单矩阵：BODY 1、其余 0 → 也选 **BODY_CLEARANCE**
  （decision_sha `1149cf32…`）。
- 两条决策都在**同一真实场景**恢复同一 S0 执行：FULL BODY pass 114.24 s、OBS BODY pass
  114.40 s，均 0 次机身接触、`safe_pass=true`、到达 2.6 m；OBS 决策重复执行一次结果完全一致。
- 结论：修正后 FULL 与 OBS **决策与结局一致**，差异只在降身计划；此前 `formal_final.json`
  的“决策差异 5/7”作废，文件保留并标 `PENDING_CORRECTION`。
- 可运行包 v2（sha `be114bd3…`）在新目录实测：3 s 启动、完整缓存案例（聚合→决策校验→真值执行→
  回放）均通过；归档分支 `archive/stage008` 提交 `6da3075a`。
## 最新结论（截至第 37 轮，2026-11-03 晚）

- **A 控制接口 / B 基础周期 / F 20 m 路线：通过**。
- **C 预演保真：部分**（五臂均 physical_failure；A-B 第 72 步分叉，残差已解释）。
- **D 腿式能力：未通过**。CLIMB 未完成；D3 原始初态 1/2、扰动初态 2/3。
- **E 主角对照：无正例**。14 例中仅 FULL 成功 0、仅 OBS 成功 0、选择不同 1。
- 交付入口：`dist/minimal/index.html`、`docs/G6_DELIVERY.md`、`docs/G6_STATUS.md`、
  `docs/BOUNDARY.md`、`docs/EVIDENCE_INDEX.md`。
- 数据回传：**已完成**（`states/` 7.0 GB、`generation/cache` 4.7 GB 均在本机）。

## 代码基准

- 实际 HEAD / origin/main：`ddbb9cb66`（2026-11-03 晚）。
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
  `generation/cache`（4.7 GB）与全量 `states/`（7 GB）**已完成同步**（后台任务已结束）。
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

## SIDE_LEVEL 独立评估尝试（未得到干净结果）

- 静态垫块场景（右侧 8–15 mm 小垫块）在 reset/settle 阶段就把机器人掀翻
  （roll −71.5° / −131.6°），不是 SIDE_LEVEL 的动作问题，而是场景/初始落点问题。
- 脚本保留在 `scripts/v3_side_level.py`，标 WIP；**不要把它的输出当作
  SIDE_LEVEL 通过/失败结论**。第二技能仍为“已实现、未验证”。
- 不再为此新开场；若后续要验证，应让机器人先在平地稳定，再横向驶上垫块，
  而不是在垫块上出生。

### SIDE_LEVEL 第二次尝试（同样未得到干净结果）

- 改为“先在平地稳定，再向前驶上右侧 1.5 cm 垫块”，仍在中途被掀翻
  （roll −106.7°，pitch −51.7°），没有进入 SIDE_LEVEL 动作的干净评估。
- 判断：当前 0.28 m 轮距 + PD 腿的被动柔度，在单侧 1.5 cm 高差上也会失稳；
  这是场景/平台稳定性问题，不是 SIDE_LEVEL 算法本身。
- 决定：停止为该技能新开场；SIDE_LEVEL 保持“已实现、未验证”，
  不写通过/失败结论。若以后要验证，应换更宽的支撑面或先做侧向姿态控制。

## 路线速度边界

- 0.30 m/s：rigid 23.5482 m / tilt 8.91°；nominal 23.5375 m / tilt 8.29° → 通过。
- **0.35 m/s**：rigid 23.5649 m，**tilt 10.52°**，超过 10° 判据 → 判失败（虽然位置越过了终点）。
- 结论：这条 20 m 路线在 0.30 m/s 有裕度，0.35 m/s 已到姿态边界；
  不能把 0.35 m/s 的“位置到了”当作通过。

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
