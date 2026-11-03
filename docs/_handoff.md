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
- 工作包 D/E/F：CLIMB、第二技能与软土脱困、主角三案例、约 20 m 连续路线。
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
