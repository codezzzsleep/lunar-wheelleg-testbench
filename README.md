# 看不见的那一面：生成式 3D 行动前推演

**当前方向**：轮腿机器人只看得到障碍正面。系统把真实仿真 RGB-D 观测送进 Lux3D 生成
候选背面几何，在候选上预演“右绕 / 左绕 / 跨越 / 直行 / 安全回退”等动作，按冻结的
worst-case 规则选一个动作，再在**独立真值**上执行并揭晓。目标不是训练一个策略，而是
把“生成 → 物理化 → 预演 → 决定 → 独立验证”做成可解释、可复现、可审计的闭环。

> 页面是当前主入口；旧的考场与 RL/训练路线已降为历史，数据与报告仍保留在仓库里。

## 交付入口（先读这三份）

- **[docs/DELIVERY.md](docs/DELIVERY.md)** —— 交付说明：结论矩阵、证据等级（A 可引用 / B 机制验证 / C 不可引用）、
  边界与复现命令。**这是唯一该当结论看的地方。**
- **[docs/v8/STATUS.md](docs/v8/STATUS.md)** —— 最新状态（V8；2026-11-11 本机补跑后，§4.1/§4.2 已收口、§3.3 记 BLOCKED）。
- **[docs/v7/STATUS.md](docs/v7/STATUS.md)** —— V7 收尾与 v7.3 重评估（唯一基本闭环的版本）。

其余按归档处理：`docs/README.md` 是文档地图，`docs/archive/` 是历史过程文档（v2 批、轮次报告、
unseen 各版状态、v4–v6 过程报告），**不要**当现行结论引用。

### 一句话现状（2026-11-11）

- **研究结论：`benefit = NOT_ESTABLISHED`**（自 v5 起未变）。V8 的完整故事：保守车 5 眼后卡住；
  乐观车撞；"假设黑影里也能测深处"的对照车 3 眼到终点；"用真值几何当想象的"上界车 1 眼到终点；
  而**真实 Lux3D 想象的车，一次都没能让自检放行出可走路线**（首眼 T1 采纳 2/6、T2 0/4，第二眼 0/3）。
- **反事实这次真跑了**：把被自检拒绝、想得最短的那份想象强行采纳（`--trust T2=C1`，短 0.9 m），
  规划器就在"真值里看不见的那 0.9 m"上看见了空路，`t=89.18 s` 直接撞上石头 —— 说明**自检的拒绝是
  load-bearing 的**，而不是形式主义。
- **V8 已收口**：想象车在两眼上限下 **`stuck`**（2 眼、52.72 s、无碰撞、不再要第三眼）——
  它既没撞也没到，停在半路；瓶颈不是"看第几眼"，而是候选质量（look2 三份候选 0/3 准入）。
  默认判据仍是"重放不逐字节一致就退出 11"；本次用显式 `--accept-replay-drift` 沿用归档 look2 观测，
  跨机位姿差 0.1902 mm 已记进 summary（`runs/v8/main/imagination/summary.json`）。

**2026-11-03 历史交付（v3 口径，非现状）**：`dist/minimal/index.html`（最小可复现交付页）、
`docs/G6_DELIVERY.md`、`docs/G6_STATUS.md`、`docs/FINAL_STATE.md`、
`docs/CURRENT_STATUS.md`（标题仍是 `SPEC_UNSEEN_RECOVERY_002`）。这些文件里的状态矩阵
（A/B/F 通过、C 部分、D 未通过、E 无正例）与 `docs/EVIDENCE_INDEX.md` 的 `runs/v3/*`
证据只对应 v3 批次，不要当作当前结论。

- 五画面作品页：`runs/unseen/delivery_v7/v7_20261030_r1/story/R02.html`（看见 → 想象 → 试走 → 决定 → 真走与揭晓）
- 共同规划入口：`scripts/common_planner.py`（唯一实现，所有比较入口复用）
- 七行主比较：`scripts/v7_family_compare.py`
- 2.5D 高程策略：`scripts/v7_elev25d.py`
- 资格门：`scripts/candidate_qualification.py`
- 演示包：`demo/r1_r03_two_view/run_demo.sh`



## 三个同名“v7”（别混）

- `runs/unseen/delivery_v7/`：**2026-10-30 批次**的数据与页面（`v7_20261030`、`v7_20261030_r1`）；
- `docs/UNSEEN_STATUS_V7.md`：**10-30** 那批的状态文档（R1 修正批），不是现行 V7 规范；
- `docs/v7/SPEC_V7.md` + `docs/v7/STATUS.md`：**11-07 起**的 V7 规范与状态，含 v7.1–v7.3 补丁
  与收尾结论；本文提到“V7”时指这一份。

## V6（2026-10-29）观测约束融合与连续回放

V6 用 V5 已有真实资产，**不新增付费 create**：把观测到的可见面作为约束，与 face12k / 镜像父候选融合，得到 H5-F / B3-F；再做同真值、同初态、30 s 的匹配比较。

- 入口：`runs/unseen/delivery_v6/v6_20261029/manifest.json`
- 连续回放页：`runs/unseen/delivery_v6/v6_20261029/media/replay/index.html`
- 当前状态：`docs/archive/unseen/UNSEEN_STATUS_V6.md`
- 关键限制：H5-F 可见几何过 strict，但 CoACD 32/64 的占据 IoU 只有 0.28，标 `COLLISION_UNRELIABLE`；H5-F 的 S1 成功不能归因于隐藏几何。第二观察真实触发但两者都保留，worst-case 选 A0；benefit=NOT_ESTABLISHED。

## V6.1（2026-10-30，在途）融合修复与新发现

- 批次入口：`runs/unseen/delivery_v6_1/v6_1_20261029/manifest.json`
- **批次报告页（静态、已用无头浏览器验证）**：`runs/unseen/delivery_v6_1/v6_1_20261029/media/report/index.html`
  （截图：`.../media/report/screenshot.png`）
- 当前状态：`docs/archive/unseen/UNSEEN_STATUS_V6_1.md`；交付验收器：`scripts/verify_delivery_v6_1.py`（103/103）
- 三条要点：① 观测壳层曾无上界，把未知区填成实体（face12k 新增 40310 → 修复后 279 体素）；
  ② 误差首次出现在**占据化+网格提取**（S2），不是相机/加载；③ 多假设达到真值上限，但**镜像先验同分**，
  benefit 仍 `NOT_ESTABLISHED`；④ 正面可见面排序会被视角反转（F 第二观察实测）。

## 资料与项目历程

- **当前执行状态**：`docs/v8/STATUS.md`（最新，2026-11-08）与 `docs/v7/STATUS.md`（V7 已收尾）；
  V6.1 时期的交接见 `docs/archive/unseen/UNSEEN_STATUS_V6_1.md` → `docs/archive/unseen/UNSEEN_STATUS_V6.md`（历史）
- **项目历程与决策证据**：`docs/PROJECT_JOURNEY.md`（每阶段：想解决什么、怎么做的、哪条判断被修正、证据等级）
- **外部资料来源登记**：`docs/sources/lux3d/README.md` + 机器可读 `docs/sources/lux3d/source_manifest.json`
- **场景适配分析**：`docs/research/LUX3D_SCENE_FIT.md`（官方说明 / 项目实测 / 项目推断三类分开）

> 资料登记只记录「当时参考了什么、资料说了什么、没有证明什么」。原文与素材**未归档**：
> 2026-10-29 在本机尝试打开两个飞书链接均被重定向到 `accounts.feishu.cn` 登录页，未重新读取。

## 当前入口 / 先看什么

```bash
# 只读页面：默认打开已提交的真实支持运行
.venv/bin/python scripts/app_unseen.py --port 8091
# http://127.0.0.1:8091/
```

常用直达：

```text
http://127.0.0.1:8091/?run=pipeline_H5_R03      # 真实候选 G_R03 完整单例闭环（H5=盲走=3/3）
http://127.0.0.1:8091/?run=H5_R01_face12k       # V5 正式 H5：统一初态 0.05/0.05，L2 2/3
http://127.0.0.1:8091/?run=six_R01_v5           # R01 六方法：H5 无候选，B3/U/宽度规则 S1 3/3
http://127.0.0.1:8091/?run=six_R03_v5           # R03 六方法：六方法均 3/3
http://127.0.0.1:8091/?run=six_R02_v5           # R02 边界：所有非 A0 0/3，H5 no_candidate
http://127.0.0.1:8091/?run=six_R04_v5           # R04 边界：所有非 A0 0/3，H5 no_candidate
http://127.0.0.1:8091/?run=look_loop_R01_v3     # 第二观察 fixture 链（FIXTURE）
http://127.0.0.1:8091/?run=batch:v5_20261029    # V5 批次入口（manifest + formal table）
```

- 运行注册表：`runs/unseen/page_registry.json`
- V5 批次唯一入口：`runs/unseen/delivery_v5/v5_20261029/manifest.json`
- 页面只读 `runs/`、`cases/` 下已落盘产物；打开页面**不会**调用生成 API、不会新建任务。
- 批次 `evaluation/` 下新出现的 `summary.json + records/execution` 会被自动登记；
  没有正式运行时页面显示明确状态，不补造结果。

页面按五个画面组织：

1. **看见**：真实送生成的图、原观测、可见面 mask、深度用途与观察方向。
2. **想象**：真实生成候选的侧视/后侧视/俯视、来源与 task 身份、候选/清理/配准/planning 计数。
3. **试走**：候选 × 动作预演矩阵、失败阶段（tipped / timeout / abort / n/a）。
4. **决定**：选了什么、规则、哪个候选或约束改变了决定。
5. **执行与揭晓**：独立真值、成功/失败、逐初态数值回放、H5 与 B0/镜像/盒子/真值上界的对照。

另单独显示：strict 几何诊断与 planning eligibility、fixture 标签、cache/new 模式、
月壤近似、模拟时间与 wall time、观察不可用/无候选/缺 decision 等状态。

## 验证页面（真实浏览器）

本仓库已用 headless Chromium 实际打开并截图（不是只看接口）：

```bash
python -m py_compile scripts/app_unseen.py
.venv/bin/python scripts/app_unseen.py --port 8091
# 另一个 shell：
FONTCONFIG_FILE=/tmp/fonts.conf \
LD_LIBRARY_PATH=/tmp/sysroot/usr/lib/x86_64-linux-gnu:/tmp/sysroot/lib/x86_64-linux-gnu \
~/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell \
  --headless --no-sandbox --disable-gpu --hide-scrollbars --window-size=1600,2600 \
  --virtual-time-budget=4000 \
  --screenshot=runs/unseen/delivery_v5/v5_20261029/media/page/01_pipeline_H5_R03.png \
  'http://127.0.0.1:8091/?run=pipeline_H5_R03'
```

截图目录：`runs/unseen/delivery_v5/v5_20261029/media/page/`。
`FONTCONFIG_FILE=/tmp/fonts.conf` 指向本机已有的 Noto CJK 字体；没有 CJK 字体的环境
需要先安装中文字体，否则截图会出现方框（这是字体环境问题，不是页面数据问题）。

## 这版是什么 / 不是什么

- **输入是仿真 RGB-D**，不是真实相机；观测包来自 MuJoCo 渲染，深度只用于可见面分割与
  可见量（`x_front / W_vis / H_vis`），不读背面真值。
- **执行是独立仿真**，不是真实机器人，也不是真实月面迁移。页面里的“真值”是同一
  MuJoCo case 的独立物理执行，不是现场传感器。
- **月壤是半经验近似**：Bekker 压实阻力 + 等效库仑牵引；整机仍是刚性接触，
  **几何下陷没有实现**（`soil-acceptance` stage G = `PARTIAL_NOT_IMPLEMENTED`）。
  单轮标定不能直接证明整机几何下陷。
- **候选资格与 strict 几何分开**：strict 是 IoU/P95/freespace 的观测一致性诊断；
  planning eligibility 是独立的工程入场政策。两者都不是安全证明，也不等于收益成立。
- **benefit 当前是 `NOT_ESTABLISHED`**：R03 的 H5 与盲走/镜像同为 3/3；V5 R01 的正式
  H5 是 L2 **2/3**（seed0 30.02 s timeout），低于 B3_mirror / U_truth / 宽度规则的 S1
  **3/3**；而 C_R01_face12k 只是 IoU-only planning eligible，strict 仍失败（P95 11.0 mm、
  freespace 0.5106、hit_part_cap=true）。因此不能写成合格候选或 Lux3D 独有收益。
- 页面不把 fixture 标成 Lux3D；不把预演动画标成真实执行回放；没有回放帧就明确显示
  “未保存回放帧”，只给逐初态数值。

## 当前证据（V5 批次，2026-10-29）

以 `runs/unseen/delivery_v5/v5_20261029/manifest.json` 与页面为准，摘要：

- 真实生成：3 个单图对照任务（R01 az25 / az45 / face12k），累计上界 60 积分；
  ledger 记录 3 个 task_id，实际扣费仍为 unknown（API 不回传）。
- 候选处理：3 个生成/下载；3/3 清理通过；3/3 配准完成；**0 strict pass**；
  **1 planning eligible（IoU-only）**：`C_R01_face12k`（task 4466144，IoU 0.8622、
  P95 11.0 mm > 9.957、freespace 0.5106、hit_part_cap=true），另外 2 个 ineligible。
  strict 与 planning 分列，页面逐候选列出，不隐藏。
- 已落盘的正式运行（`evaluation/`）：
  - 正式 H5 `H5_R01_face12k`：统一初态 0.05/0.05，chosen `L2`，真值 **2/3**
    （seed0 `time_limit` 30.02 s，seed1/2 success 7.48/6.88 s），B0 R1 **0/3**；
    B3_mirror / U_truth / 宽度规则均 `S1` 3/3（mean 6.593）→ H5 无收益；
  - 六方法 R03：六方法均 3/3，H5 与 B0 同分（6.42）；B2/U 的 D1 6.387；
  - 六方法 R01：H5 `no_candidate`，B3_mirror / U_truth 的 S1 3/3，B0 R1 0/3；
  - 六方法 R02 / R04：H5 `no_candidate`，所有非 A0 动作 0/3（能力边界）。
  - **初态更正**：旧 `H5_R01_face12k_init003` 的 yaw=0.03、L2 3/3 已标 SUPERSEDED，
    不与 six 的 0.05/0.05 配对，不用于正式表；正式表见
    `runs/unseen/delivery_v5/v5_20261029/evaluation/formal_table_v5.json`，benefit 见 `runs/unseen/delivery_v5/v5_20261029/evaluation/benefit_summary.json`。
- 真值动作扫描（`cases/`，不是候选闭环）：R01_base 只有 S1 3/3；R01_az25/az45 无
  全初态通过动作；R02/R04 全部非 A0 失败；R03 多个动作 3/3。
- 月壤：单轮/平地/坡面/零牵引/吞吐/整机 stage A–G 已跑；stage G 明确
  `geometry_sinkage_implemented=false`；稳定性 1000 回合仍在补（页面显示实时计数）。
- 统一验收：本批 verify **73/73**（以 `verify/` 与页面 `preflight` 为准）；测试绿灯
  不替代研究收益结论。
- 观察：V5 的 az25/az45 是“不同相对观察方向”的诊断，不是 R01 单视角重复采样；
  R01_base 观测包缺 RGB/depth/mask，页面显式标不可用。
- 第二观察：真实候选的 trigger 运行 `trigger_face12k` 判定“候选一致，不触发观察”；
  fixture trigger 对（`trigger_fixture_pair*`）只验证 trigger 逻辑，**不是真实收益证据**。
  完整第二观察/续行仍是 fixture 链（`look_loop_R01_v3`），不等同真实候选“再看一眼”。

## 快速回归

```bash
.venv/bin/python -m py_compile scripts/app_unseen.py
.venv/bin/python -m unittest discover -s tests -v     # 全套约 15 分钟，约 150 项
.venv/bin/python scripts/check_repo_hygiene.py        # 仓库卫生：补丁清单 / LFS / 大文件直入库 / 产物类路径
sha256sum -c PATCH_SHA256.txt                         # V8 补丁清单，应 11/11 OK
```

- **有 GL 的机器**：加 `MUJOCO_GL=egl` 再跑。
- **没有 GL 的机器**（无 `DISPLAY`、无 root）：跑一次
  `./scripts/setup_local_gl.sh`（自动下载并解包 Mesa 到 `/tmp/glroot`，不需要 root），
  然后 `source <(./scripts/setup_local_gl.sh --export)` 激活，即可用 `MUJOCO_GL=osmesa` 跑渲染。
  不装也能跑测试：`tests/_gl.py` 用子进程探测 GL，没有上下文时 `test_camera` / `test_freespace`
  自动跳过（`OK (skipped=N)`），不会 core dump 中断 suite。
- 总时长约 15 分钟（`test_pipeline` 534 s、`test_trainer` 321 s），其余 11 个模块都是秒级。

页面接口烟测：

```bash
curl -sS http://127.0.0.1:8091/api/cases | python3 -m json.tool
curl -sS 'http://127.0.0.1:8091/api/run?name=pipeline_H5_R03' | python3 -m json.tool
```

## 目录（当前相关）

```text
README.md                  本文件：交付入口 + 现状一句话 + 复现
docs/DELIVERY.md           交付说明：结论矩阵（A/B/C 证据等级）、V8 完整故事、方法学发现、边界
docs/README.md             文档地图：现行 vs 归档、8 份脚本生成物一览、三个"v7"辨析
docs/v8/                   当前主线：SPEC_V8、STATUS、SANDBOX_LOG
docs/v7/                   唯一基本闭环的版本：SPEC_V7、STATUS、REVIEW_V7_R1/R2/R3
docs/archive/              58 篇历史过程文档（v2 批 / 轮次报告 / unseen 各版状态 / v4–v6 过程报告）
scripts/README.md          代次导航：哪一代解决什么问题、现行入口、4 条已知坑
scripts/v8/                V8 主程序：v8_run（路线）、v8_eval（复盘）、v8_replay_diff（重放取证）
scripts/setup_local_gl.sh  没有 GL 的机器上装软件渲染（OSMesa，不需要 root）
runs/README.md             批次索引：8 个主要批次 + 其余 50 个、哪些产物是证据不能删
runs/v8/main/              当前主线全部产物（五台车 + 反事实 + 逐眼观测与候选）
runs/v7/shadow_exp/        V7 影子实验原始行（64 ok / 72，5 cm 余量的唯一出处）
```

## 历史：旧考场与 RL/训练路线（保留，不再作为当前主入口）

以下内容保留用于追溯，**不是**当前默认路线，也不代表当前 V5 交付。旧运行目录、
`docs/archive/rounds/ROUND*_REPORT.md`、`docs/archive/reports/PG_REPORT.md`、`runs/canonical*/` 等均未删除。

- 旧主线是“条件 → 场景 → 训练 → 共同评估”的 RL/考试路线：`scripts/pipeline.py`、
  `scripts/run_experiments.py`、`scripts/evaluate.py`；控制器是 `hold` / `step` / `adapt`
  手工控制器，不是学出来的技能。
- 旧考场：`scripts/demo.py`、`scripts/analyze.py`、`scripts/replay.py`；`hold/step/adapt`
  的实测边界见 `docs/archive/rounds/ROUND3_REPORT.md`。旧结论（任务 M 无可测增益、任务 K 未达 10pp、
  固定原语 0/12）只属于旧路线，不要搬到 V5 上。
- 旧入口 `scripts/app.py --port 8080` 仍保留，但新工作看 `scripts/app_unseen.py`。
- 旧训练/考场数据与报告仍在 `runs/`、`docs/` 中；本 README 不删除任何旧数据。

## 来源与许可

- 机器人模型：[unitreerobotics/unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco)
  （固定提交），按其仓库许可使用。
- 3D 生成：[Aholo Lux3D](https://www.aholo3d.cn)，候选由本项目真实生成任务产生。
- 凸块分解：[CoACD](https://github.com/sarahweiii/CoACD)（MIT）。
