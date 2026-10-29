# 看不见的那一面：生成式 3D 行动前推演

**当前方向**：轮腿机器人只看得到障碍正面。系统把真实仿真 RGB-D 观测送进 Lux3D 生成
候选背面几何，在候选上预演“右绕 / 左绕 / 跨越 / 直行 / 安全回退”等动作，按冻结的
worst-case 规则选一个动作，再在**独立真值**上执行并揭晓。目标不是训练一个策略，而是
把“生成 → 物理化 → 预演 → 决定 → 独立验证”做成可解释、可复现、可审计的闭环。

> 页面是当前主入口；旧的考场与 RL/训练路线已降为历史，数据与报告仍保留在仓库里。


## V6（2026-10-29）观测约束融合与连续回放

V6 用 V5 已有真实资产，**不新增付费 create**：把观测到的可见面作为约束，与 face12k / 镜像父候选融合，得到 H5-F / B3-F；再做同真值、同初态、30 s 的匹配比较。

- 入口：`runs/unseen/delivery_v6/v6_20261029/manifest.json`
- 连续回放页：`runs/unseen/delivery_v6/v6_20261029/media/replay/index.html`
- 当前状态：`docs/UNSEEN_STATUS_V6.md`
- 关键限制：H5-F 可见几何过 strict，但 CoACD 32/64 的占据 IoU 只有 0.28，标 `COLLISION_UNRELIABLE`；H5-F 的 S1 成功不能归因于隐藏几何。第二观察真实触发但两者都保留，worst-case 选 A0；benefit=NOT_ESTABLISHED。

## V6.1（2026-10-30，在途）融合修复与新发现

- 批次入口：`runs/unseen/delivery_v6_1/v6_1_20261029/manifest.json`
- **批次报告页（静态、已用无头浏览器验证）**：`runs/unseen/delivery_v6_1/v6_1_20261029/media/report/index.html`
  （截图：`.../media/report/screenshot.png`）
- 当前状态：`docs/UNSEEN_STATUS_V6_1.md`；交付验收器：`scripts/verify_delivery_v6_1.py`（103/103）
- 三条要点：① 观测壳层曾无上界，把未知区填成实体（face12k 新增 40310 → 修复后 279 体素）；
  ② 误差首次出现在**占据化+网格提取**（S2），不是相机/加载；③ 多假设达到真值上限，但**镜像先验同分**，
  benefit 仍 `NOT_ESTABLISHED`；④ 正面可见面排序会被视角反转（F 第二观察实测）。

## 资料与项目历程

- **当前执行状态**（唯一状态中心）：`docs/UNSEEN_STATUS_V6_1.md`（V6.1 在途）→ `docs/UNSEEN_STATUS_V6.md`
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
.venv/bin/python -m unittest discover -s tests -v      # 现有单元测试
```

页面接口烟测：

```bash
curl -sS http://127.0.0.1:8091/api/cases | python3 -m json.tool
curl -sS 'http://127.0.0.1:8091/api/run?name=pipeline_H5_R03' | python3 -m json.tool
```

## 目录（当前相关）

```text
scripts/app_unseen.py                 只读页面（manifest + registry 驱动）
runs/unseen/page_registry.json        页面运行注册表
runs/unseen/delivery_v5/v5_20261029/  V5 批次：manifest、observations、candidates、cases、soil、verify、media/page
runs/unseen/recovery_r3/              已提交的支持运行（真实 G_R03、六方法、fixture 观察链、开发例）
cases/unseen_v1/                      案例定义与 V5 truth/twin 用例
docs/DEMO_V5.md                       2–3 分钟演示脚本（当前批次证据）
docs/UNSEEN_STATUS_CURRENT.md         研究状态与边界（历史状态文档之一）
```

## 历史：旧考场与 RL/训练路线（保留，不再作为当前主入口）

以下内容保留用于追溯，**不是**当前默认路线，也不代表当前 V5 交付。旧运行目录、
`docs/ROUND*_REPORT.md`、`docs/PG_REPORT.md`、`runs/canonical*/` 等均未删除。

- 旧主线是“条件 → 场景 → 训练 → 共同评估”的 RL/考试路线：`scripts/pipeline.py`、
  `scripts/run_experiments.py`、`scripts/evaluate.py`；控制器是 `hold` / `step` / `adapt`
  手工控制器，不是学出来的技能。
- 旧考场：`scripts/demo.py`、`scripts/analyze.py`、`scripts/replay.py`；`hold/step/adapt`
  的实测边界见 `docs/ROUND3_REPORT.md`。旧结论（任务 M 无可测增益、任务 K 未达 10pp、
  固定原语 0/12）只属于旧路线，不要搬到 V5 上。
- 旧入口 `scripts/app.py --port 8080` 仍保留，但新工作看 `scripts/app_unseen.py`。
- 旧训练/考场数据与报告仍在 `runs/`、`docs/` 中；本 README 不删除任何旧数据。

## 来源与许可

- 机器人模型：[unitreerobotics/unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco)
  （固定提交），按其仓库许可使用。
- 3D 生成：[Aholo Lux3D](https://www.aholo3d.cn)，候选由本项目真实生成任务产生。
- 凸块分解：[CoACD](https://github.com/sarahweiii/CoACD)（MIT）。
