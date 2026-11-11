# 交付说明（DELIVERY）

**用途**：验收用的一页纸加细则——项目证明了什么、没证明什么、证据在哪、怎么复现。
**读法**：路径相对仓库根，已用 `test -f` 逐一验证；「§x」是该版本规范文档的章节号（V8 见 `docs/v8/SPEC_V8.md`）。证据等级 **A**＝可直接引用；**B**＝机制验证（有产物，但结论属推导或样本内统计）；**C**＝不可引用。

## 1 一句话结论

**证明了**：在"极地走廊 + 三块石头 + 三台车"的仿真里，"正面看见 + 背面生成想象"没有把原本"过不去"的情形变成"过得去"（`runs/v8/main/`）；而"信了被自检拒绝的想象"会直接撞车——自检的拒绝是关键支撑，不是装饰（`runs/v8/main/counterfactual_T2_C1/summary.json`）。
**没证明**：三维重建（Lux3D）带来任何净收益。全项目收益口径仍为 `NOT_ESTABLISHED`（`docs/CURRENT_STATUS.md:131`）。

## 2 结论矩阵

| 版本 | 问题 | 结论 | 等级 | 证据 |
| --- | --- | --- | --- | --- |
| V8 §2 | 保守车能否自己走过走廊 | 不能：5 眼后 `stuck`（142.2 s）；乐观车 `collision`；黑影可测深对照 `arrived`；真值想象上界 `arrived` | A | `runs/v8/main/`（各车 `summary.json`） |
| V8 §3.2 | 生成与采纳率 | 首眼 T1 采纳 2/6（B2、C2）、T2 0/4；第二眼 0/3；两次决策均 `imagined_blocked` | A | `runs/v8/main/imagination/looks/look1/T1/decide/target_decision.json`、`docs/v8/STATUS.md` |
| V8 §3.3 | 两眼上限下会停车吗 | **会，已跑成真实运行**：`stuck`、2 眼、52.72 s、无碰撞、不再要第三眼（look2 的 T2 候选 0/3 准入）。默认仍严格：重放不一致即退出 11；本次用显式 `--accept-replay-drift` 沿用归档 look2 观测，位姿差 0.1902 mm 已记入 `summary.replay_drift_accepted` | A（附该口径） | `runs/v8/main/imagination/summary.json`、`.../look2/REPLAY_DIFF.json`、`docs/v8/STATUS.md` |
| V8 §4.1 | 想象与真值差多少 | 13 行比较：采纳 2、拒绝 11（其中 10 份"想短了"）；被采纳的背面误差 0.00–0.35 m | A | `runs/v8/main/eval.json` |
| V8 §4.2 | 采纳被拒候选会怎样 | 真实运行：规划期余量 −0.23 m，t=89.18 s 撞 `obstacle1`，`collision` | A | `runs/v8/main/counterfactual_T2_C1/` |
| V7 §3.4 | 自检能否挡住坏想象 | 72 个任务 64 成功 / 8 失败；成功样本里 IoU<0.5 的 32 份采纳 0，≥0.6 的 31 份采纳 21；样本内最大背面误差 5.0 cm | A（样本内） | `runs/v7/shadow_exp/eval_rows.json` |
| V7 §3.1–3.2 | 路线能否闭环 | 只看正面 22.0109 m / 96.78 s、有想象 22.0088 m / 140.46 s，均 `arrived`；但两次观测采纳 0/6、0/3，最终回退正面规划器执行 R1 | A | `runs/v7/route_full_r2/result.json` |
| V7 §2.2 | 决策是否稳健 | 不稳健：预演地面尺寸 32 m→4 m（都是平地）使 E1 直行从"2/3 安全、选 R1"翻成"1/3 安全、选 D2" | B | `docs/v7/REVIEW_V7_R3.md:60-64` |
| V6 M3 | 连续路线能否跑通 | 现行 R2 包两臂都到 x≈22.0 成功结束（22.0113 m / 59.76 s；22.0014 m / 56.16 s）；差别在 E1 选动作（full=R2 / obs=R1），不在结局 | A | `runs/v6/m4/units/M3_route2_full/runs/full/result.json` |
| V6 文档 | M3 到底跑没跑 | `RESULTS.md` 开头"M3 未执行"属**文档没更新**（同文后段有完整 M3 数字）；`runs/v6/m1/selfcheck.json` 记 n=206 而 M1 表 218 行，差 12 行无解释 | C | `docs/v6/RESULTS.md` |
| V5 | C2 有正例 | 已被自身 R3 推翻（FULL=A0，无存活正例）；C4/C6 无目录、无报告 | C | `docs/v5/A_R3_REPORT.md` |
| V4 WP8 | 20 m 路线成功 | 只有文字：目录仅 `manifest.json` 与 `scene.json`，manifest 却列了 67 个文件 | C | `runs/v4/wp8/route_v2/manifest.json` |

> V6 的 R1 包（`M3_route_obs`、`M3_route_full`）两臂逐帧相同（x=13.5067 m、62.38 s），已作废、不得引用（`runs/v6/m4/units/M3_route_obs/runs/obs/result.json`、`docs/v6/REVIEW_R1.md:139`）。

## 3 V8 的完整故事

同一场景、同一初始位姿，五台车（`runs/v8/main/`）：

| 车 | 设定 | result | looks | 时间 |
| --- | --- | --- | --- | --- |
| `conservative` | 保守：看不见的格子一律当障碍（不用 Lux3D） | `stuck` | 5 | 142.2 s |
| `optimistic` | 乐观：看不见的格子一律当空地 | `collision`（t=80.94 s 撞 `obstacle1`） | 1 | 83.44 s |
| `imagination` | 真实 Lux3D 候选 + 自检 + 第二眼 | `stuck`（停在半路，未要第三眼） | 2 | 52.72 s |
| `conservative_seedark` | 对照：假设黑影里也能测深 | `arrived` | 3 | 147.26 s |
| `imagination_truth` | 上界：真值几何当完美想象 | `arrived` | 1 | 115.88 s |

**余量口径**：`runs/v8/main/optimistic/summary.json` 无 `drive_margin_m` 字段；−0.23 m 出自 `plan` 事件的 `margin_vs_truth.drive_margin_m`，是规划期量，非实测碰撞深度。

**候选质量**（`eval.json`，13 行，`incomplete_runs=["imagination"]`）：首眼 T1 生成 6/6、采纳 B2 与 C2（背面误差 0.35 m、0.00 m；占地 IoU 0.60、0.714）；首眼 T2 生成 4/6、采纳 0/4；第二眼（两图）生成 3/3、采纳 0/3。11 份拒绝中 10 份标记"想短了"，最极端 −0.9 m。

**反事实**：取被拒里想得最短的 `look1/T2/C1`（−0.9 m；C2 同为 −0.9，按 id 取 C1），用 `--trust T2=C1` 强行采纳并真跑（复用首眼观测与生成结果，无新 API 调用）：规划期余量 −0.23 m（与真值重叠 23 cm），t=89.18 s 撞 `obstacle1`（`runs/v8/main/counterfactual_T2_C1/`）。

## 4 方法学发现

1. **临界判定不稳健**：同一物理、仅改预演地面的数值尺寸（32 m vs 4 m，都是平地），同一动作的安全性就从 2/3 变成 1/3，决策从 R1 变成 D2。这类判定不能只报一次结果（`docs/v7/REVIEW_V7_R3.md:60-64`）。
2. **跨机重放会漂移，但结论不变**：同机逐位可复现；换机后第二眼停车位姿差 dx=0.1902 mm、
   dy=0.0923 mm、dyaw=0.008483°，RGB 平均绝对差 1.5608（192 万像素里 28,438 个像素差 >8），
   深度中位数差 0.83 mm、p90 8.93 mm —— 于是"逐字节相同才复用"的判据跨机失效（工程约束，不是实验失败）。
   同一次本机复跑里，乐观车仍在 t=80.84 s 撞（归档值 80.94 s）、规划期余量仍是 −0.23 m：
   **数值漂 ≤0.1 s / ≤1 cm，结论不变**（`docs/DELIVERY.md` 第 6 节的命令可自行复现）。
3. **5.0 cm 不是性能保证**：它是 n=21 的**样本内最大值**，无留出集、无安全系数，只能说明自检没有放进明显偏长的想象（`runs/v7/shadow_exp/eval_rows.json`）。

## 5 明确边界与未做

| 类别 | 条目 |
| --- | --- |
| 做不了 | 生成新的 Lux3D 候选：本机所有补跑都**没有**产生 API 调用（无 `AHOLO_API_KEY`，复用命中即用归档结果）。因此"换一批候选会不会更好"无法在本机回答 |
| 没做 | 留出检验集（故 5.0 cm 只算样本内）。`docs/EVIDENCE_INDEX.md` 已重生成（143 条，`runs/v3` 全覆盖、0 死链），但**只覆盖 v3**；v4–v8 的证据就是本文件第 2 节这张矩阵 |
| 不可引用 | V4 WP8 的 20 m 路线；V6 的 R1 包与 `RESULTS.md` 的"M3 未执行"；V5 C2 的正例；任何"想象带来了收益"的说法 |

## 6 怎么复现

仓库根执行（本机无 GPU、无 root 亦可）：

```bash
# 0) 没有 GL 的机器先装软件渲染（不需要 root），然后按提示 source 激活
./scripts/setup_local_gl.sh
source <(./scripts/setup_local_gl.sh --export)      # 导出 LD_LIBRARY_PATH 与 MUJOCO_GL=osmesa

# 1) 复跑一台车（写到 /tmp，避免覆盖已归档的 runs/v8/main）
.venv/bin/python scripts/v8/v8_run.py --policy optimistic --out /tmp/v8_repro

# 2) 复盘（候选与真值的比较）
.venv/bin/python scripts/v8/v8_eval.py --run runs/v8/main

# 3) 回归与卫生
.venv/bin/python -m unittest discover -s tests      # 约 15 分钟；无 GL 时两个渲染模块自动跳过
.venv/bin/python scripts/check_repo_hygiene.py
sha256sum -c PATCH_SHA256.txt                       # 11/11
```

有 GPU/EGL 的机器把第 0 步换成 `export MUJOCO_GL=egl` 即可。原归档运行用的是
`--out runs/v8/main`（见 `docs/v8/SPEC_V8.md`）。

第 0 步做的事（供审计）：`scripts/setup_local_gl.sh` 用 `apt-get download`（不需要 root）取
`libosmesa6`/`libglvnd0`/`libglapi-mesa`/`libglx-mesa0`/`libgl1-mesa-dri`/`libllvm20`，
`dpkg -x` 解到 `/tmp/glroot`，再建一个 64×64 的 Renderer 渲染一帧自检；`--export` 只打印环境变量。
它不改系统、不需要 sudo。
补丁校验 `sha256sum -c PATCH_SHA256.txt` → **11/11**（已复验）。测试规模：当前收集 **147** 项；2026-11-11 在本机完整跑过一次——**exit 0、15 分 22 秒**（无 GL 时 `test_camera`/`test_freespace` 共 11 项自动跳过）。

## 7 交付清单

| 类别 | 可点击路径 |
| --- | --- |
| 本说明 | [DELIVERY.md](DELIVERY.md) |
| V8 状态与规范 | [STATUS.md](v8/STATUS.md)、[SPEC_V8.md](v8/SPEC_V8.md)、[SANDBOX_LOG.md](v8/SANDBOX_LOG.md) |
| V8 证据 | [eval.json](../runs/v8/main/eval.json)、[REPLAY_DIFF.json](../runs/v8/main/imagination/looks/look2/REPLAY_DIFF.json)、[反事实摘要](../runs/v8/main/counterfactual_T2_C1/summary.json)、[反事实事件](../runs/v8/main/counterfactual_T2_C1/events.jsonl)、[轨迹](../runs/v8/main/counterfactual_T2_C1/traj.npz)、[乐观车摘要](../runs/v8/main/optimistic/summary.json) |
| V8 工具 | [v8_run.py](../scripts/v8/v8_run.py)、[v8_eval.py](../scripts/v8/v8_eval.py)、[v8_replay_diff.py](../scripts/v8/v8_replay_diff.py) |
| V7 状态与复审 | [STATUS.md](v7/STATUS.md)、[REVIEW_V7_R3.md](v7/REVIEW_V7_R3.md) |
| V7 证据 | [eval_rows.json](../runs/v7/shadow_exp/eval_rows.json)、[route_obs](../runs/v7/route_obs/result.json)、[route_full_r2](../runs/v7/route_full_r2/result.json)、[span32](../runs/v7/determinism_e1_span32/summary.json)、[span4](../runs/v7/determinism_e1_span4/summary.json) |
| V6 证据 | [M3 full](../runs/v6/m4/units/M3_route2_full/runs/full/result.json)、[M3 obs](../runs/v6/m4/units/M3_route2_obs/runs/obs/result.json)、[决策](../runs/v6/m4/units/M3_route2_full/runs/full/decision.json)、[selfcheck](../runs/v6/m1/selfcheck.json) |
| 仅存档 | [WP8 manifest](../runs/v4/wp8/route_v2/manifest.json)、[V6 RESULTS](v6/RESULTS.md)、[V5 A_R3](v5/A_R3_REPORT.md) |
| 状态与索引 | [CURRENT_STATUS.md](CURRENT_STATUS.md)、[EVIDENCE_INDEX.md](EVIDENCE_INDEX.md)、[REVIEW_2026-11-11.md](REVIEW_2026-11-11.md) |
| 校验 | [PATCH_SHA256.txt](../PATCH_SHA256.txt) |
